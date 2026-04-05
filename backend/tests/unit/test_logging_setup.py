from __future__ import annotations

import logging
from pathlib import Path
import time

from backend.app.core.logging import configure_logging, get_logger


def _list_log_files(log_dir: Path) -> list[Path]:
    return sorted(log_dir.glob("*.log"))


def _read_latest_log_file(log_dir: Path) -> str:
    files = _list_log_files(log_dir)
    assert files
    return files[-1].read_text(encoding="utf-8")


def test_configure_logging_writes_session_log_file_with_expected_format(tmp_path: Path):
    configure_logging(project_root=tmp_path, force=True)

    get_logger("job_queue_service").info("任务队列心跳线程已启动")

    log_dir = tmp_path / "logs"
    assert log_dir.exists()
    files = _list_log_files(log_dir)
    assert len(files) == 1
    assert files[0].name.startswith("backend_")
    content = _read_latest_log_file(log_dir)
    assert "[INFO] [job_queue_service] 任务队列心跳线程已启动" in content


def test_configure_logging_intercepts_standard_logging_records(tmp_path: Path):
    configure_logging(project_root=tmp_path, force=True)

    logging.getLogger("legacy.worker").warning("旧式 logging 也要写入统一日志")

    content = _read_latest_log_file(tmp_path / "logs")
    assert "[WARNING] [legacy.worker] 旧式 logging 也要写入统一日志" in content


def test_configure_logging_filters_successful_health_access_logs(tmp_path: Path):
    configure_logging(project_root=tmp_path, force=True)

    logging.getLogger("uvicorn.access").info('127.0.0.1:52371 - "GET /health HTTP/1.1" 200')

    content = _read_latest_log_file(tmp_path / "logs")
    assert "GET /health" not in content


def test_configure_logging_keeps_health_logs_at_warning_or_higher(tmp_path: Path):
    configure_logging(project_root=tmp_path, force=True)

    logging.getLogger("uvicorn.access").warning('127.0.0.1:52371 - "GET /health HTTP/1.1" 503')

    content = _read_latest_log_file(tmp_path / "logs")
    assert '[WARNING] [uvicorn.access] 127.0.0.1:52371 - "GET /health HTTP/1.1" 503' in content


def test_configure_logging_force_reconfiguration_reuses_recent_session_log_file_within_30_seconds(
    tmp_path: Path,
):
    configure_logging(project_root=tmp_path, force=True)
    first_logger = get_logger("job_queue_service")
    first_logger.info("第一次启动日志")
    first_files = _list_log_files(tmp_path / "logs")
    assert len(first_files) == 1

    time.sleep(0.01)

    configure_logging(project_root=tmp_path, force=True)
    second_logger = get_logger("job_queue_service")
    second_logger.info("第二次启动日志")
    second_files = _list_log_files(tmp_path / "logs")

    assert len(second_files) == 1
    assert first_files[0].name == second_files[0].name
    content = second_files[0].read_text(encoding="utf-8")
    assert "第一次启动日志" in content
    assert "第二次启动日志" in content


def test_configure_logging_force_reconfiguration_creates_new_session_log_file_after_30_seconds(tmp_path: Path):
    configure_logging(project_root=tmp_path, force=True)
    first_logger = get_logger("job_queue_service")
    first_logger.info("第一次启动日志")
    first_files = _list_log_files(tmp_path / "logs")
    assert len(first_files) == 1

    stale_timestamp = time.time() - 31
    first_files[0].touch()
    import os

    os.utime(first_files[0], (stale_timestamp, stale_timestamp))

    configure_logging(project_root=tmp_path, force=True)
    second_logger = get_logger("job_queue_service")
    second_logger.info("第二次启动日志")
    second_files = _list_log_files(tmp_path / "logs")

    assert len(second_files) == 2
    assert second_files[0].name != second_files[1].name
    assert "第一次启动日志" in first_files[0].read_text(encoding="utf-8")
    assert "第二次启动日志" in second_files[-1].read_text(encoding="utf-8")
