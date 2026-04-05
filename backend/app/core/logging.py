from __future__ import annotations

from datetime import datetime
import logging
import time
import sys
from pathlib import Path

from loguru import logger

_DEFAULT_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_LOG_FORMAT = "{time:HH:mm:ss.SSS} [{level}] [{extra[component]}] {message}"
_CRASH_LOOP_WINDOW_SECONDS = 30
_configured_log_dir: Path | None = None
_configured_log_file: Path | None = None


def _ensure_component(record: dict) -> None:
    component = record["extra"].get("component")
    if component:
        return
    name = record.get("name") or "app"
    record["extra"]["component"] = name.rsplit(".", maxsplit=1)[-1]


_base_logger = logger.patch(_ensure_component)


def _should_skip_std_logging_record(record: logging.LogRecord) -> bool:
    if record.name != "uvicorn.access":
        return False
    message = record.getMessage()
    return "GET /health " in message and record.levelno < logging.WARNING


class InterceptHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        if _should_skip_std_logging_record(record):
            return
        try:
            level: str | int = _base_logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        frame = logging.currentframe()
        depth = 2
        while frame is not None and frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back
            depth += 1

        _base_logger.bind(component=record.name).opt(depth=depth, exception=record.exc_info).log(
            level,
            record.getMessage(),
        )


def get_logger(component: str):
    return _base_logger.bind(component=component)


def _pick_log_file(log_dir: Path) -> tuple[Path, bool]:
    now = time.time()
    existing_files = sorted(log_dir.glob("backend_*.log"), key=lambda item: item.stat().st_mtime, reverse=True)
    if existing_files:
        latest_file = existing_files[0]
        age_seconds = now - latest_file.stat().st_mtime
        if age_seconds <= _CRASH_LOOP_WINDOW_SECONDS:
            return latest_file, True

    session_stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S_%f")
    return log_dir / f"backend_{session_stamp}.log", False


def configure_logging(project_root: Path | None = None, *, force: bool = False) -> Path:
    global _configured_log_dir, _configured_log_file

    root = (project_root or _DEFAULT_PROJECT_ROOT).resolve()
    log_dir = root / "logs"
    should_reconfigure = force or _configured_log_dir != log_dir or _configured_log_file is None
    if not should_reconfigure:
        return log_dir

    log_dir.mkdir(parents=True, exist_ok=True)
    log_file, reused_existing_file = _pick_log_file(log_dir)

    _base_logger.remove()
    _base_logger.add(
        sys.stderr,
        level="INFO",
        format=_LOG_FORMAT,
        colorize=True,
        backtrace=False,
        diagnose=False,
    )
    _base_logger.add(
        str(log_file),
        level="DEBUG",
        format=_LOG_FORMAT,
        colorize=False,
        retention="14 days",
        encoding="utf-8",
        delay=True,
        backtrace=False,
        diagnose=False,
    )

    intercept_handler = InterceptHandler()
    logging.root.handlers = [intercept_handler]
    logging.root.setLevel(logging.NOTSET)

    for name in ("uvicorn", "uvicorn.error", "uvicorn.access", "fastapi"):
        std_logger = logging.getLogger(name)
        std_logger.handlers = [intercept_handler]
        std_logger.propagate = False

    for noisy_name in ("numba", "matplotlib", "httpx"):
        logging.getLogger(noisy_name).setLevel(logging.WARNING)

    _configured_log_dir = log_dir
    _configured_log_file = log_file
    if reused_existing_file:
        _base_logger.bind(component="logging").warning(
            "检测到 30 秒内重复启动，继续写入最近日志文件 file={}",
            log_file,
        )
    else:
        _base_logger.bind(component="logging").info("日志已切换到新的启动会话文件 file={}", log_file)
    return log_dir
