from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
from pathlib import Path
import re

from fastapi import Request, Response

from backend.app.core.exceptions import AssetExpiredError, AssetNotFoundError, InvalidRangeError
from backend.app.schemas.edit_session import AudioDeliveryDescriptor


_BYTE_RANGE_RE = re.compile(r"^bytes=(\d*)-(\d*)$")


@dataclass(frozen=True)
class ByteRange:
    start: int
    end: int

    @property
    def byte_length(self) -> int:
        return self.end - self.start + 1


class AudioDeliveryService:
    def build_descriptor(
        self,
        *,
        asset_id: str,
        audio_url: str,
        asset_path: Path,
        sample_rate: int,
        expires_at: datetime | None = None,
    ) -> AudioDeliveryDescriptor:
        audio_file_path, _ = self._resolve_audio_file(asset_path)
        stat = audio_file_path.stat()
        etag_source = f"{asset_id}:{stat.st_size}:{stat.st_mtime_ns}"
        return AudioDeliveryDescriptor(
            asset_id=asset_id,
            audio_url=audio_url,
            sample_rate=sample_rate,
            byte_length=stat.st_size,
            etag=hashlib.sha1(etag_source.encode("utf-8")).hexdigest(),
            expires_at=expires_at,
        )

    def parse_range(self, range_header: str | None, file_size: int) -> ByteRange | None:
        if range_header is None:
            return None
        if file_size <= 0:
            raise InvalidRangeError("Range request is invalid for an empty audio asset.")
        if "," in range_header:
            raise InvalidRangeError("Multiple byte ranges are not supported.")

        matched = _BYTE_RANGE_RE.fullmatch(range_header.strip())
        if matched is None:
            raise InvalidRangeError("Range header must use the format 'bytes=start-end'.")

        start_text, end_text = matched.groups()
        if not start_text and not end_text:
            raise InvalidRangeError("Range header must specify a start or end offset.")

        if start_text:
            start = int(start_text)
            end = file_size - 1 if not end_text else min(int(end_text), file_size - 1)
            if start >= file_size or start > end:
                raise InvalidRangeError("Requested byte range is not satisfiable.")
            return ByteRange(start=start, end=end)

        suffix_length = int(end_text)
        if suffix_length <= 0:
            raise InvalidRangeError("Suffix byte range must be greater than zero.")
        if suffix_length >= file_size:
            return ByteRange(start=0, end=file_size - 1)
        return ByteRange(start=file_size - suffix_length, end=file_size - 1)

    def build_streaming_response(
        self,
        *,
        request: Request,
        asset_path: Path,
        content_type: str,
        etag: str,
        expires_at: datetime | None = None,
        download: bool = False,
    ) -> Response:
        if expires_at is not None and expires_at <= datetime.now(timezone.utc):
            raise AssetExpiredError("Audio asset has expired.")

        audio_file_path, download_filename = self._resolve_audio_file(asset_path)
        file_size = audio_file_path.stat().st_size
        byte_range = self.parse_range(request.headers.get("range"), file_size)
        body = self._read_bytes(audio_file_path, byte_range)
        headers = {
            "Accept-Ranges": "bytes",
            "ETag": etag,
            "Content-Length": str(len(body)),
        }
        if download:
            headers["Content-Disposition"] = f'attachment; filename="{download_filename}"'

        status_code = 200
        if byte_range is not None:
            status_code = 206
            headers["Content-Range"] = f"bytes {byte_range.start}-{byte_range.end}/{file_size}"

        return Response(content=body, media_type=content_type, headers=headers, status_code=status_code)

    def _resolve_audio_file(self, asset_path: Path) -> tuple[Path, str]:
        candidate = asset_path
        if candidate.is_dir():
            audio_file_path = candidate / "audio.wav"
            filename = f"{candidate.name}.wav"
        elif candidate.suffix:
            audio_file_path = candidate
            filename = candidate.name
        else:
            audio_file_path = candidate / "audio.wav"
            filename = f"{candidate.name}.wav"

        if not audio_file_path.exists():
            raise AssetNotFoundError(f"Audio asset not found: {audio_file_path}")
        return audio_file_path, filename

    @staticmethod
    def _read_bytes(audio_file_path: Path, byte_range: ByteRange | None) -> bytes:
        with audio_file_path.open("rb") as file_handle:
            if byte_range is None:
                return file_handle.read()
            file_handle.seek(byte_range.start)
            return file_handle.read(byte_range.byte_length)
