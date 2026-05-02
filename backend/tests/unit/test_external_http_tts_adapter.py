from __future__ import annotations

import json

import pytest
import requests

from backend.app.inference.audio_processing import build_wav_bytes, float_audio_chunk_to_pcm16_bytes
from backend.app.inference.block_adapter_errors import BlockAdapterError
from backend.app.inference.block_adapter_types import (
    BlockRenderRequest,
    BlockRequestBlock,
    BlockRequestSegment,
    ResolvedModelBinding,
)
from backend.app.inference.external_http_rate_limiter import (
    ExternalHttpLimitConfig,
    ExternalHttpRateLimiter,
)
from backend.app.inference.adapters.external_http_tts_adapter import ExternalHttpTtsAdapter
from backend.app.tts_registry.secret_store import SecretStore


class _FakeResponse:
    def __init__(self, *, status_code: int, content: bytes = b"", headers: dict[str, str] | None = None, json_body=None) -> None:
        self.status_code = status_code
        self.content = content
        self.headers = headers or {}
        self._json_body = json_body
        self.text = content.decode("utf-8", errors="ignore") if content else (
            json.dumps(json_body, ensure_ascii=False) if json_body is not None else ""
        )

    def json(self):
        if self._json_body is not None:
            return self._json_body
        raise ValueError("response body is not json")


class _FakeSession:
    def __init__(self, *responses_or_errors: _FakeResponse | Exception) -> None:
        self._responses_or_errors = list(responses_or_errors)
        self.calls: list[dict[str, object]] = []

    def post(self, url: str, *, json=None, headers=None, timeout=None):
        self.calls.append(
            {
                "url": url,
                "json": json,
                "headers": headers,
                "timeout": timeout,
            }
        )
        next_item = self._responses_or_errors.pop(0)
        if isinstance(next_item, Exception):
            raise next_item
        return next_item


def _build_request(secret_handle: str) -> BlockRenderRequest:
    return BlockRenderRequest(
        request_id="req-http-1",
        document_id="doc-1",
        block=BlockRequestBlock(
            block_id="block-1",
            segment_ids=["seg-1"],
            start_order_key=1,
            end_order_key=1,
            estimated_sample_count=3,
            segments=[
                BlockRequestSegment(
                    segment_id="seg-1",
                    order_key=1,
                    text="你好，世界。",
                    language="zh",
                )
            ],
            block_text="你好，世界。",
        ),
        model_binding=ResolvedModelBinding(
            adapter_id="external_http_tts",
            model_instance_id="remote-demo",
            preset_id="voice-a",
            resolved_assets={},
            resolved_reference={
                "reference_id": "remote-demo:preset",
                "audio_uri": "",
                "text": "参考文本",
                "language": "zh",
                "source": "preset",
                "fingerprint": "",
            },
            resolved_parameters={"speed": 1.0},
            secret_handles={"api_key": secret_handle},
            binding_fingerprint="binding-http-1",
            endpoint={"url": "https://api.example.com/tts"},
            account_binding={"provider": "example", "account_id": "acct-1"},
            preset_fixed_fields={"remote_voice_id": "voice_a"},
            adapter_options={
                "max_concurrent_requests": 1,
                "requests_per_minute": 30,
                "tokens_per_minute": 1000,
            },
        ),
        adapter_options={
            "external_http_tts": {
                "text": "你好，世界。",
                "model_instance_id": "remote-demo",
                "preset_id": "voice-a",
                "remote_voice_id": "voice_a",
                "endpoint": {"url": "https://api.example.com/tts"},
                "reference": {
                    "reference_id": "remote-demo:preset",
                    "audio_uri": "",
                    "text": "参考文本",
                    "language": "zh",
                    "source": "preset",
                    "fingerprint": "",
                },
                "synthesis": {"speed": 1.0},
                "metadata": {
                    "provider": "example",
                    "account_id": "acct-1",
                },
            }
        },
    )


def test_external_http_tts_adapter_posts_json_payload_and_parses_wav(tmp_path):
    secret_store = SecretStore(tmp_path / "registry")
    secret_store.put_model_secrets("remote-demo", {"api_key": "top-secret"})
    fake_session = _FakeSession(
        _FakeResponse(
            status_code=200,
            content=build_wav_bytes(32000, float_audio_chunk_to_pcm16_bytes([0.1, 0.2, 0.3])),
        )
    )
    adapter = ExternalHttpTtsAdapter(
        secret_store=secret_store,
        rate_limiter=ExternalHttpRateLimiter(),
        http_session=fake_session,
    )

    result = adapter.render_block(_build_request("secret://remote-demo/api_key"))

    assert result.sample_rate == 32000
    assert result.audio_sample_count == 3
    assert fake_session.calls[0]["url"] == "https://api.example.com/tts"
    assert fake_session.calls[0]["json"]["remote_voice_id"] == "voice_a"
    assert fake_session.calls[0]["headers"]["Authorization"] == "Bearer top-secret"


def test_external_http_tts_adapter_exposes_block_only_http_capabilities():
    capabilities = ExternalHttpTtsAdapter.capabilities()

    assert capabilities.block_render is True
    assert capabilities.bounded_concurrency is True
    assert capabilities.external_http_api is True
    assert capabilities.remote_runtime is True
    assert capabilities.supports_block_only_alignment is True


def test_external_http_tts_adapter_maps_429_to_standard_block_adapter_error(tmp_path):
    secret_store = SecretStore(tmp_path / "registry")
    secret_store.put_model_secrets("remote-demo", {"api_key": "top-secret"})
    fake_session = _FakeSession(
        _FakeResponse(
            status_code=429,
            headers={"Retry-After": "2", "x-request-id": "req-429"},
            json_body={"message": "slow down"},
        )
    )
    adapter = ExternalHttpTtsAdapter(
        secret_store=secret_store,
        rate_limiter=ExternalHttpRateLimiter(),
        http_session=fake_session,
    )

    with pytest.raises(BlockAdapterError) as exc_info:
        adapter.render_block(_build_request("secret://remote-demo/api_key"))

    payload = exc_info.value.to_payload().model_dump(mode="json")
    assert payload["error_code"] == "rate_limited"
    assert payload["details"]["provider_http_status"] == 429
    assert payload["details"]["provider_request_id"] == "req-429"
    assert payload["details"]["retry_after_ms"] == 2000


def test_external_http_tts_adapter_uses_default_backoff_when_429_has_no_retry_after(tmp_path):
    secret_store = SecretStore(tmp_path / "registry")
    secret_store.put_model_secrets("remote-demo", {"api_key": "top-secret"})
    fake_session = _FakeSession(
        _FakeResponse(
            status_code=429,
            headers={"x-request-id": "req-429"},
            json_body={"message": "slow down"},
        )
    )
    adapter = ExternalHttpTtsAdapter(
        secret_store=secret_store,
        rate_limiter=ExternalHttpRateLimiter(),
        http_session=fake_session,
        default_limit_config=ExternalHttpLimitConfig(
            max_concurrent_requests=1,
            requests_per_minute=None,
            tokens_per_minute=None,
            retry_on_429=False,
            max_retry_attempts=0,
            default_retry_backoff_ms=750,
            max_retry_backoff_ms=2_000,
            acquire_timeout_ms=1_000,
        ),
    )

    with pytest.raises(BlockAdapterError) as exc_info:
        adapter.render_block(_build_request("secret://remote-demo/api_key"))

    payload = exc_info.value.to_payload().model_dump(mode="json")
    assert payload["error_code"] == "rate_limited"
    assert payload["details"]["retry_after_ms"] == 750


def test_external_http_tts_adapter_maps_timeout_to_standard_payload_with_bucket_context(tmp_path):
    secret_store = SecretStore(tmp_path / "registry")
    secret_store.put_model_secrets("remote-demo", {"api_key": "top-secret"})
    fake_session = _FakeSession(requests.Timeout("provider timed out"))
    adapter = ExternalHttpTtsAdapter(
        secret_store=secret_store,
        rate_limiter=ExternalHttpRateLimiter(),
        http_session=fake_session,
    )

    with pytest.raises(BlockAdapterError) as exc_info:
        adapter.render_block(_build_request("secret://remote-demo/api_key"))

    payload = exc_info.value.to_payload().model_dump(mode="json")
    assert payload["error_code"] == "timeout"
    assert payload["details"] == {
        "provider_http_status": 408,
        "provider_error_code": None,
        "provider_message": "provider timed out",
        "provider_request_id": None,
        "retryable": True,
        "retry_after_ms": 0,
        "limit_bucket_key": "example:acct-1:https://api.example.com/tts",
        "response_excerpt": "",
    }


@pytest.mark.parametrize("status_code", [401, 403])
def test_external_http_tts_adapter_maps_auth_error_to_adapter_unavailable(tmp_path, status_code: int):
    secret_store = SecretStore(tmp_path / "registry")
    secret_store.put_model_secrets("remote-demo", {"api_key": "top-secret"})
    fake_session = _FakeSession(
        _FakeResponse(
            status_code=status_code,
            headers={"request-id": "req-auth"},
            json_body={"message": "bad api key", "code": "unauthorized"},
        )
    )
    adapter = ExternalHttpTtsAdapter(
        secret_store=secret_store,
        rate_limiter=ExternalHttpRateLimiter(),
        http_session=fake_session,
    )

    with pytest.raises(BlockAdapterError) as exc_info:
        adapter.render_block(_build_request("secret://remote-demo/api_key"))

    payload = exc_info.value.to_payload().model_dump(mode="json")
    assert payload["error_code"] == "adapter_unavailable"
    assert payload["details"]["provider_http_status"] == status_code
    assert payload["details"]["provider_error_code"] == "unauthorized"
    assert payload["details"]["provider_request_id"] == "req-auth"
    assert payload["details"]["retryable"] is True


def test_external_http_tts_adapter_rejects_invalid_wav_payload(tmp_path):
    secret_store = SecretStore(tmp_path / "registry")
    secret_store.put_model_secrets("remote-demo", {"api_key": "top-secret"})
    fake_session = _FakeSession(
        _FakeResponse(
            status_code=200,
            content=b"not-a-wav",
            headers={"Content-Type": "audio/wav"},
        )
    )
    adapter = ExternalHttpTtsAdapter(
        secret_store=secret_store,
        rate_limiter=ExternalHttpRateLimiter(),
        http_session=fake_session,
    )

    with pytest.raises(BlockAdapterError) as exc_info:
        adapter.render_block(_build_request("secret://remote-demo/api_key"))

    payload = exc_info.value.to_payload().model_dump(mode="json")
    assert payload["error_code"] == "render_failed"
    assert payload["details"]["retryable"] is False
    assert "provider_message" in payload["details"]


def test_external_http_tts_adapter_maps_limiter_acquire_timeout_to_standard_rate_limited_error(tmp_path):
    secret_store = SecretStore(tmp_path / "registry")
    secret_store.put_model_secrets("remote-demo", {"api_key": "top-secret"})
    fake_session = _FakeSession(
        _FakeResponse(
            status_code=200,
            content=build_wav_bytes(32000, float_audio_chunk_to_pcm16_bytes([0.1, 0.2, 0.3])),
        )
    )
    limiter = ExternalHttpRateLimiter()
    adapter = ExternalHttpTtsAdapter(
        secret_store=secret_store,
        rate_limiter=limiter,
        http_session=fake_session,
    )
    request = _build_request("secret://remote-demo/api_key")
    request.model_binding.adapter_options = {
        "max_concurrent_requests": 1,
        "requests_per_minute": 1,
        "tokens_per_minute": 1_000,
        "acquire_timeout_ms": 10,
    }

    adapter.render_block(request)

    with pytest.raises(BlockAdapterError) as exc_info:
        adapter.render_block(request)

    payload = exc_info.value.to_payload().model_dump(mode="json")
    assert payload["error_code"] == "rate_limited"
    assert payload["details"]["provider_http_status"] is None
    assert payload["details"]["retryable"] is True
    assert payload["details"]["limit_bucket_key"] == "example:acct-1:https://api.example.com/tts"
