from __future__ import annotations

from dataclasses import dataclass, replace
import json
from pathlib import Path
import time

import numpy as np
import torch
from fastapi.testclient import TestClient

from backend.app.inference.audio_processing import build_wav_bytes, float_audio_chunk_to_pcm16_bytes
from backend.app.inference.editable_gateway import EditableInferenceGateway
from backend.app.inference.editable_types import (
    BoundaryAssetPayload,
    ReferenceContext,
    ResolvedRenderContext,
    SegmentRenderAssetPayload,
    build_boundary_asset_id,
)
from backend.app.main import create_app


class _FakeEditableInferenceBackend:
    def build_reference_context(
        self,
        resolved_context: ResolvedRenderContext,
        *,
        progress_callback=None,
    ) -> ReferenceContext:
        del progress_callback
        return ReferenceContext(
            reference_context_id="ctx-local-1",
            voice_id=resolved_context.voice_id,
            model_id=resolved_context.model_key,
            reference_audio_path=resolved_context.reference_audio_path or "fake.wav",
            reference_text=resolved_context.reference_text or "参考文本。",
            reference_language=resolved_context.reference_language or "zh",
            reference_semantic_tokens=np.asarray([1, 2, 3], dtype=np.int64),
            reference_spectrogram=torch.ones((1, 3, 3), dtype=torch.float32),
            reference_speaker_embedding=torch.ones((1, 4), dtype=torch.float32),
            inference_config_fingerprint="fingerprint-local",
            inference_config={"margin_frame_count": 0, "speed": resolved_context.speed},
        )

    def render_segment_base(self, segment, context, *, progress_callback=None) -> SegmentRenderAssetPayload:
        del progress_callback
        sample_count = 2 if context.inference_config.get("speed", 1.0) < 1.0 else 1
        audio = np.asarray([segment.order_key / 10] * sample_count, dtype=np.float32)
        return SegmentRenderAssetPayload(
            render_asset_id=f"render-{segment.segment_id}",
            segment_id=segment.segment_id,
            render_version=1,
            semantic_tokens=[1, 2],
            phone_ids=[11, 12],
            decoder_frame_count=1,
            audio_sample_count=sample_count,
            left_margin_sample_count=0,
            core_sample_count=sample_count,
            right_margin_sample_count=0,
            left_margin_audio=np.zeros(0, dtype=np.float32),
            core_audio=audio,
            right_margin_audio=np.zeros(0, dtype=np.float32),
            trace=None,
        )

    def render_boundary_asset(self, left_asset, right_asset, edge, context) -> BoundaryAssetPayload:
        del context
        return BoundaryAssetPayload(
            boundary_asset_id=build_boundary_asset_id(
                left_segment_id=edge.left_segment_id,
                left_render_version=left_asset.render_version,
                right_segment_id=edge.right_segment_id,
                right_render_version=right_asset.render_version,
                edge_version=edge.edge_version,
                boundary_strategy=edge.boundary_strategy,
            ),
            left_segment_id=left_asset.segment_id,
            left_render_version=1,
            right_segment_id=right_asset.segment_id,
            right_render_version=1,
            edge_version=1,
            boundary_strategy="latent_overlap_then_equal_power_crossfade",
            boundary_sample_count=1,
            boundary_audio=np.asarray([0.9], dtype=np.float32),
            trace=None,
        )


@dataclass(frozen=True)
class _ProviderResponse:
    status_code: int
    body: bytes
    headers: dict[str, str]
    delay_seconds: float = 0.0


class _FakeResponse:
    def __init__(self, *, status_code: int, body: bytes, headers: dict[str, str]) -> None:
        self.status_code = status_code
        self.content = body
        self.headers = headers
        content_type = headers.get("Content-Type", "")
        self.text = body.decode("utf-8", errors="ignore") if "json" in content_type else ""

    def json(self):
        return json.loads(self.text)


class _QueuedHttpSession:
    def __init__(self, responses: list[_ProviderResponse | Exception]) -> None:
        self._responses = list(responses)
        self.requests: list[dict[str, object]] = []

    def post(self, url: str, *, json=None, headers=None, timeout=None):
        self.requests.append(
            {
                "url": url,
                "json": json,
                "headers": headers or {},
                "timeout": timeout,
            }
        )
        if not self._responses:
            return _FakeResponse(
                status_code=500,
                body=b'{"message":"no queued response"}',
                headers={"Content-Type": "application/json"},
            )
        response = self._responses.pop(0)
        if isinstance(response, Exception):
            raise response
        if response.delay_seconds > 0:
            time.sleep(response.delay_seconds)
        return _FakeResponse(
            status_code=response.status_code,
            body=response.body,
            headers=response.headers,
        )


def _wait_until(predicate, *, timeout: float = 5.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return
        time.sleep(0.05)
    raise AssertionError("Condition not met before timeout.")


def _create_external_model(
    client: TestClient,
    *,
    endpoint_url: str = "https://api.example.com/tts",
    adapter_options: dict[str, object] | None = None,
) -> None:
    created = client.post(
        "/v1/tts-registry/models",
        json={
            "model_instance_id": "remote-direct",
            "display_name": "Remote Direct",
            "adapter_id": "external_http_tts",
            "endpoint": {"url": endpoint_url},
            "account_binding": {
                "provider": "example",
                "account_id": "acct-direct",
                "required_secrets": ["api_key"],
            },
            "presets": [
                {
                    "preset_id": "voice-a",
                    "display_name": "Voice A",
                    "kind": "remote",
                    "fixed_fields": {"remote_voice_id": "voice_a"},
                    "defaults": {
                        "reference_text": "远端参考文本",
                        "reference_language": "zh",
                    },
                }
            ],
            "adapter_options": adapter_options or {},
        },
    )
    assert created.status_code == 201
    secret_response = client.put(
        "/v1/tts-registry/models/remote-direct/secrets",
        json={"secrets": {"api_key": "top-secret"}},
    )
    assert secret_response.status_code == 200
    assert secret_response.json()["status"] == "ready"


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _create_local_package(package_root: Path) -> Path:
    _write_json(
        package_root / "neo-tts-model.json",
        {
            "schema_version": 1,
            "package_id": "demo-gpt-sovits",
            "display_name": "Demo Voice",
            "adapter_id": "gpt_sovits_local",
            "source_type": "local_package",
            "instance": {
                "assets": {
                    "pretrained_base": "base",
                    "bert": "pretrained/bert.bin",
                }
            },
            "presets": [
                {
                    "preset_id": "default",
                    "display_name": "Default",
                    "assets": {
                        "gpt_weight": "weights/demo.ckpt",
                        "sovits_weight": "weights/demo.pth",
                        "reference_audio": "refs/demo.wav",
                    },
                    "defaults": {
                        "reference_text": "测试参考文本",
                        "reference_language": "zh",
                        "speed": 1.0,
                    },
                }
            ],
        },
    )
    _write_text(package_root / "base" / "README.txt", "base data")
    _write_text(package_root / "pretrained" / "bert.bin", "bert")
    _write_text(package_root / "weights" / "demo.ckpt", "ckpt")
    _write_text(package_root / "weights" / "demo.pth", "pth")
    _write_text(package_root / "refs" / "demo.wav", "wav")
    return package_root


def _initialize_local_session(client: TestClient, *, tmp_path: Path) -> str:
    package_root = _create_local_package(tmp_path / "local-package")
    imported = client.post(
        "/v1/tts-registry/models/import",
        json={"package_path": str(package_root), "storage_mode": "managed"},
    )
    assert imported.status_code == 201
    initialize = client.post(
        "/v1/edit-session/initialize",
        json={
            "raw_text": "第一句。第二句。",
            "voice_id": "demo-gpt-sovits",
        },
    )
    assert initialize.status_code == 202
    _wait_until(lambda: client.get("/v1/edit-session/snapshot").json()["session_status"] == "ready")
    snapshot = client.get("/v1/edit-session/snapshot").json()
    return snapshot["segments"][0]["segment_id"]


def _read_terminal_job_payload(client: TestClient, *, job_id: str) -> dict[str, object]:
    with client.stream("GET", f"/v1/edit-session/render-jobs/{job_id}/events") as response:
        assert response.status_code == 200
        event_name = None
        for line in response.iter_lines():
            if not line:
                continue
            if line.startswith("event: "):
                event_name = line.removeprefix("event: ")
                continue
            if line.startswith("data: "):
                assert event_name == "job_state_changed"
                payload = json.loads(line.removeprefix("data: "))
                if payload.get("status") in {"completed", "failed", "cancelled_partial", "paused"}:
                    return payload
    raise AssertionError("Expected terminal SSE payload.")


def test_block_first_external_http_adapter_retries_429_using_settings_defaults_and_keeps_export_flow(
    test_app_settings,
    monkeypatch,
):
    settings = replace(
        test_app_settings,
        external_http_default_retry_on_429=True,
        external_http_default_max_retry_attempts=1,
        external_http_default_retry_backoff_ms=1,
        external_http_default_max_retry_backoff_ms=10,
        external_http_default_acquire_timeout_ms=1_000,
    )
    wav_payload = build_wav_bytes(32000, float_audio_chunk_to_pcm16_bytes([0.1, 0.2, 0.3, 0.4]))
    session = _QueuedHttpSession(
        responses=[
            _ProviderResponse(
                status_code=429,
                body=b'{"message":"slow down"}',
                headers={
                    "Content-Type": "application/json",
                    "Retry-After": "0.001",
                    "x-request-id": "req-429",
                },
            ),
            _ProviderResponse(
                status_code=200,
                body=wav_payload,
                headers={"Content-Type": "audio/wav"},
            ),
        ]
    )
    monkeypatch.setattr(
        "backend.app.inference.adapters.external_http_tts_adapter.requests.Session",
        lambda: session,
    )
    app = create_app(settings=settings)
    app.state.editable_inference_gateway = EditableInferenceGateway(_FakeEditableInferenceBackend())
    with TestClient(app) as client:
        _create_external_model(client)
        segment_id = _initialize_local_session(client, tmp_path=settings.project_root)
        patch_response = client.patch(
            f"/v1/edit-session/segments/{segment_id}/voice-binding",
            json={
                "model_key": "external-http",
                "model_instance_id": "remote-direct",
                "preset_id": "voice-a",
            },
        )
        assert patch_response.status_code == 202
        job_id = patch_response.json()["job"]["job_id"]
        _wait_until(lambda: client.get(f"/v1/edit-session/render-jobs/{job_id}").json()["status"] == "completed")

        job_payload = client.get(f"/v1/edit-session/render-jobs/{job_id}").json()
        timeline_payload = client.get("/v1/edit-session/timeline").json()
        block_audio_url = timeline_payload["block_entries"][0]["audio_url"]
        block_audio = client.get(block_audio_url)
        export_response = client.post(
            "/v1/edit-session/exports/composition",
            json={
                "document_version": timeline_payload["document_version"],
                "target_dir": str(settings.edit_session_exports_dir / "http-adapter-success"),
                "overwrite_policy": "fail",
            },
        )

        assert job_payload["status"] == "completed"
        assert job_payload["adapter_error"] is None
        assert block_audio.status_code == 200
        assert export_response.status_code == 202

    assert len(session.requests) == 2
    assert session.requests[0]["url"] == "https://api.example.com/tts"
    assert session.requests[0]["json"]["remote_voice_id"] == "voice_a"
    assert session.requests[0]["headers"]["Authorization"] == "Bearer top-secret"
    limiter_state = app.state.external_http_rate_limiter.get_state(
        "example:acct-direct:https://api.example.com/tts"
    )
    assert limiter_state.last_provider_status == 429
    assert limiter_state.last_provider_request_id == "req-429"


def test_block_first_external_http_adapter_surfaces_provider_error_to_job_and_sse(test_app_settings, monkeypatch):
    session = _QueuedHttpSession(
        responses=[
            _ProviderResponse(
                status_code=401,
                body=b'{"message":"bad api key","code":"unauthorized"}',
                headers={
                    "Content-Type": "application/json",
                    "x-request-id": "req-401",
                },
            )
        ]
    )
    monkeypatch.setattr(
        "backend.app.inference.adapters.external_http_tts_adapter.requests.Session",
        lambda: session,
    )
    app = create_app(settings=test_app_settings)
    app.state.editable_inference_gateway = EditableInferenceGateway(_FakeEditableInferenceBackend())
    with TestClient(app) as client:
        _create_external_model(client)
        segment_id = _initialize_local_session(client, tmp_path=test_app_settings.project_root)
        patch_response = client.patch(
            f"/v1/edit-session/segments/{segment_id}/voice-binding",
            json={
                "model_key": "external-http",
                "model_instance_id": "remote-direct",
                "preset_id": "voice-a",
            },
        )
        assert patch_response.status_code == 202
        job_id = patch_response.json()["job"]["job_id"]
        _wait_until(lambda: client.get(f"/v1/edit-session/render-jobs/{job_id}").json()["status"] == "failed")

        job_payload = client.get(f"/v1/edit-session/render-jobs/{job_id}").json()
        sse_payload = _read_terminal_job_payload(client, job_id=job_id)

    assert job_payload["adapter_error"]["error_code"] == "adapter_unavailable"
    assert job_payload["adapter_error"]["details"]["provider_http_status"] == 401
    assert job_payload["adapter_error"]["details"]["provider_message"] == "bad api key"
    assert job_payload["adapter_error"]["details"]["provider_request_id"] == "req-401"
    assert sse_payload["adapter_error"]["details"]["provider_http_status"] == 401
    assert sse_payload["adapter_error"]["details"]["provider_request_id"] == "req-401"


def test_block_first_external_http_adapter_surfaces_provider_timeout_to_job_and_sse(test_app_settings, monkeypatch):
    import requests

    session = _QueuedHttpSession(
        responses=[
            requests.Timeout("provider timed out"),
        ]
    )
    monkeypatch.setattr(
        "backend.app.inference.adapters.external_http_tts_adapter.requests.Session",
        lambda: session,
    )
    app = create_app(settings=test_app_settings)
    app.state.editable_inference_gateway = EditableInferenceGateway(_FakeEditableInferenceBackend())
    with TestClient(app) as client:
        _create_external_model(client)
        segment_id = _initialize_local_session(client, tmp_path=test_app_settings.project_root)
        patch_response = client.patch(
            f"/v1/edit-session/segments/{segment_id}/voice-binding",
            json={
                "model_key": "external-http",
                "model_instance_id": "remote-direct",
                "preset_id": "voice-a",
            },
        )
        assert patch_response.status_code == 202
        job_id = patch_response.json()["job"]["job_id"]
        _wait_until(lambda: client.get(f"/v1/edit-session/render-jobs/{job_id}").json()["status"] == "failed")

        job_payload = client.get(f"/v1/edit-session/render-jobs/{job_id}").json()
        sse_payload = _read_terminal_job_payload(client, job_id=job_id)

    assert job_payload["adapter_error"]["error_code"] == "timeout"
    assert job_payload["adapter_error"]["details"]["provider_http_status"] == 408
    assert job_payload["adapter_error"]["details"]["provider_message"] == "provider timed out"
    assert job_payload["adapter_error"]["details"]["limit_bucket_key"] == "example:acct-direct:https://api.example.com/tts"
    assert sse_payload["adapter_error"]["error_code"] == "timeout"
    assert sse_payload["adapter_error"]["details"]["provider_http_status"] == 408


def test_block_first_external_http_adapter_surfaces_invalid_wav_to_job_and_sse(test_app_settings, monkeypatch):
    session = _QueuedHttpSession(
        responses=[
            _ProviderResponse(
                status_code=200,
                body=b"not-a-wav",
                headers={"Content-Type": "audio/wav"},
            )
        ]
    )
    monkeypatch.setattr(
        "backend.app.inference.adapters.external_http_tts_adapter.requests.Session",
        lambda: session,
    )
    app = create_app(settings=test_app_settings)
    app.state.editable_inference_gateway = EditableInferenceGateway(_FakeEditableInferenceBackend())
    with TestClient(app) as client:
        _create_external_model(client)
        segment_id = _initialize_local_session(client, tmp_path=test_app_settings.project_root)
        patch_response = client.patch(
            f"/v1/edit-session/segments/{segment_id}/voice-binding",
            json={
                "model_key": "external-http",
                "model_instance_id": "remote-direct",
                "preset_id": "voice-a",
            },
        )
        assert patch_response.status_code == 202
        job_id = patch_response.json()["job"]["job_id"]
        _wait_until(lambda: client.get(f"/v1/edit-session/render-jobs/{job_id}").json()["status"] == "failed")

        job_payload = client.get(f"/v1/edit-session/render-jobs/{job_id}").json()
        sse_payload = _read_terminal_job_payload(client, job_id=job_id)

    assert job_payload["adapter_error"]["error_code"] == "render_failed"
    assert job_payload["adapter_error"]["details"]["retryable"] is False
    assert sse_payload["adapter_error"]["error_code"] == "render_failed"


def test_block_first_external_http_adapter_surfaces_shared_rpm_limit_timeout_to_job_and_sse(
    test_app_settings,
    monkeypatch,
):
    wav_payload = build_wav_bytes(32000, float_audio_chunk_to_pcm16_bytes([0.1, 0.2, 0.3, 0.4]))
    session = _QueuedHttpSession(
        responses=[
            _ProviderResponse(
                status_code=200,
                body=wav_payload,
                headers={"Content-Type": "audio/wav"},
            )
        ]
    )
    monkeypatch.setattr(
        "backend.app.inference.adapters.external_http_tts_adapter.requests.Session",
        lambda: session,
    )
    app = create_app(settings=test_app_settings)
    app.state.editable_inference_gateway = EditableInferenceGateway(_FakeEditableInferenceBackend())
    with TestClient(app) as client:
        _create_external_model(
            client,
            adapter_options={
                "max_concurrent_requests": 1,
                "requests_per_minute": 1,
                "tokens_per_minute": 1_000,
                "acquire_timeout_ms": 10,
            },
        )
        first_segment_id = _initialize_local_session(client, tmp_path=test_app_settings.project_root)
        snapshot = client.get("/v1/edit-session/snapshot").json()
        second_segment_id = snapshot["segments"][1]["segment_id"]
        first_patch = client.patch(
            f"/v1/edit-session/segments/{first_segment_id}/voice-binding",
            json={
                "model_key": "external-http",
                "model_instance_id": "remote-direct",
                "preset_id": "voice-a",
            },
        )
        assert first_patch.status_code == 202
        first_job_id = first_patch.json()["job"]["job_id"]
        _wait_until(lambda: client.get(f"/v1/edit-session/render-jobs/{first_job_id}").json()["status"] == "completed")

        second_patch = client.patch(
            f"/v1/edit-session/segments/{second_segment_id}/voice-binding",
            json={
                "model_key": "external-http",
                "model_instance_id": "remote-direct",
                "preset_id": "voice-a",
            },
        )
        assert second_patch.status_code == 202
        second_job_id = second_patch.json()["job"]["job_id"]
        _wait_until(lambda: client.get(f"/v1/edit-session/render-jobs/{second_job_id}").json()["status"] == "failed")

        job_payload = client.get(f"/v1/edit-session/render-jobs/{second_job_id}").json()
        sse_payload = _read_terminal_job_payload(client, job_id=second_job_id)

    assert len(session.requests) == 1
    assert job_payload["adapter_error"]["error_code"] == "rate_limited"
    assert job_payload["adapter_error"]["details"]["provider_http_status"] is None
    assert job_payload["adapter_error"]["details"]["limit_bucket_key"] == "example:acct-direct:https://api.example.com/tts"
    assert sse_payload["adapter_error"]["error_code"] == "rate_limited"

