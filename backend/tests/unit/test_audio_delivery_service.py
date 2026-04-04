from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import Request
import pytest

from backend.app.core.exceptions import AssetExpiredError, InvalidRangeError
from backend.app.services.audio_delivery_service import AudioDeliveryService


def _build_request(range_header: str | None = None) -> Request:
    headers: list[tuple[bytes, bytes]] = []
    if range_header is not None:
        headers.append((b"range", range_header.encode("ascii")))
    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": "/audio",
        "raw_path": b"/audio",
        "query_string": b"",
        "headers": headers,
        "client": ("testclient", 50000),
        "server": ("testserver", 80),
    }
    return Request(scope)


def test_audio_delivery_service_builds_descriptor_from_file_stats(tmp_path: Path):
    audio_path = tmp_path / "audio.wav"
    audio_path.write_bytes(b"abcdef")
    service = AudioDeliveryService()

    descriptor = service.build_descriptor(
        asset_id="asset-1",
        audio_url="/v1/edit-session/assets/compositions/asset-1/audio",
        asset_path=audio_path,
        sample_rate=32000,
    )

    assert descriptor.asset_id == "asset-1"
    assert descriptor.audio_url.endswith("/audio")
    assert descriptor.byte_length == 6
    assert descriptor.etag


def test_audio_delivery_service_returns_206_for_valid_range(tmp_path: Path):
    audio_path = tmp_path / "audio.wav"
    audio_path.write_bytes(b"0123456789")
    service = AudioDeliveryService()

    response = service.build_streaming_response(
        request=_build_request("bytes=2-5"),
        asset_path=audio_path,
        content_type="audio/wav",
        etag="etag-1",
    )

    assert response.status_code == 206
    assert response.headers["accept-ranges"] == "bytes"
    assert response.headers["content-range"] == "bytes 2-5/10"
    assert response.headers["content-length"] == "4"
    assert response.headers["etag"] == "etag-1"
    assert response.body == b"2345"


def test_audio_delivery_service_raises_416_for_invalid_range(tmp_path: Path):
    audio_path = tmp_path / "audio.wav"
    audio_path.write_bytes(b"0123456789")
    service = AudioDeliveryService()

    with pytest.raises(InvalidRangeError):
        service.build_streaming_response(
            request=_build_request("bytes=20-21"),
            asset_path=audio_path,
            content_type="audio/wav",
            etag="etag-1",
        )


def test_audio_delivery_service_adds_attachment_header_when_download_requested(tmp_path: Path):
    audio_path = tmp_path / "asset.wav"
    audio_path.write_bytes(b"0123456789")
    service = AudioDeliveryService()

    response = service.build_streaming_response(
        request=_build_request(),
        asset_path=audio_path,
        content_type="audio/wav",
        etag="etag-1",
        download=True,
    )

    assert response.status_code == 200
    assert response.headers["content-disposition"] == 'attachment; filename="asset.wav"'


def test_audio_delivery_service_rejects_expired_assets(tmp_path: Path):
    audio_path = tmp_path / "audio.wav"
    audio_path.write_bytes(b"0123456789")
    service = AudioDeliveryService()

    with pytest.raises(AssetExpiredError):
        service.build_streaming_response(
            request=_build_request(),
            asset_path=audio_path,
            content_type="audio/wav",
            etag="etag-1",
            expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
        )
