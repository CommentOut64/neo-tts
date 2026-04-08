from __future__ import annotations

import time
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException, Request

from backend.app.core.logging import get_logger


reference_audio_logger = get_logger("reference_audio_upload")


def validate_reference_audio_filename(filename: str | None, *, field_name: str = "ref_audio_file") -> str:
    if not filename:
        raise HTTPException(status_code=400, detail=f"{field_name} is required when using multipart/form-data.")

    suffix = Path(filename).suffix.lower()
    if suffix not in {".wav", ".mp3", ".flac"}:
        raise HTTPException(status_code=400, detail=f"{field_name} must use one of: .flac, .mp3, .wav.")

    return Path(filename).name


def store_temporary_reference_audio(*, request: Request, filename: str, payload: bytes) -> Path:
    settings = request.app.state.settings
    temp_dir = settings.managed_voices_dir
    if not temp_dir.is_absolute():
        temp_dir = settings.project_root / temp_dir

    write_started = time.perf_counter()
    target_dir = temp_dir / "_temp_refs" / uuid4().hex
    target_dir.mkdir(parents=True, exist_ok=False)
    target_path = target_dir / Path(filename).name
    target_path.write_bytes(payload)
    reference_audio_logger.debug(
        "临时参考音频写盘完成 path={} size_bytes={} elapsed_ms={:.2f}",
        target_path,
        len(payload),
        (time.perf_counter() - write_started) * 1000,
    )
    return target_path
