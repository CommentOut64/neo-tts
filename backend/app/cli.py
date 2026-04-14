from __future__ import annotations

import argparse
import os
import sys
import threading

import uvicorn


def _parse_bool_env(raw_value: str | None, *, default: bool) -> bool:
    if raw_value is None:
        return default
    normalized = raw_value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default


def _start_stdin_watchdog() -> None:
    """Electron 场景下的 stdin 生命线。

    Electron 以 stdio=["pipe","ignore","ignore"] 启动本进程，
    当 Electron 正常退出或被强杀时 stdin 管道断开，本线程检测到 EOF 后
    立即终止进程，避免后端成为孤儿。
    """

    def _watch() -> None:
        try:
            sys.stdin.read()
        except Exception:
            pass
        os._exit(0)

    thread = threading.Thread(target=_watch, daemon=True)
    thread.start()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="GPT-SoVITS rebuild backend CLI")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=18600)
    parser.add_argument("--reload", action="store_true")
    return parser


def main() -> None:
    distribution_kind = os.environ.get("NEO_TTS_DISTRIBUTION_KIND", "")
    # Windows 打包态下 stdin.read() 在匿名管道场景可能阻塞主启动链路，
    # 默认关闭 watchdog，避免后端卡死在“无日志、无健康响应”的状态。
    enable_watchdog = _parse_bool_env(
        os.environ.get("NEO_TTS_STDIN_WATCHDOG_ENABLED"),
        default=False,
    )
    if distribution_kind in ("installed", "portable") and enable_watchdog:
        _start_stdin_watchdog()

    args = build_parser().parse_args()
    uvicorn.run(
        "backend.app.main:create_app",
        factory=True,
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_config=None,
    )


if __name__ == "__main__":
    main()
