from __future__ import annotations

import io
import time
import wave
from typing import Any

import numpy as np
import requests

from backend.app.inference.block_adapter_errors import BlockAdapterError
from backend.app.inference.block_adapter_types import AdapterCapabilities, BlockRenderRequest, BlockRenderResult
from backend.app.inference.external_http_rate_limiter import ExternalHttpLimitConfig, ExternalHttpRateLimiter
from backend.app.tts_registry.secret_store import SecretStore


class ExternalHttpTtsAdapter:
    def __init__(
        self,
        *,
        secret_store: SecretStore,
        rate_limiter: ExternalHttpRateLimiter,
        http_session: requests.Session | Any | None = None,
        timeout_seconds: float = 30.0,
        default_limit_config: ExternalHttpLimitConfig | None = None,
    ) -> None:
        self._secret_store = secret_store
        self._rate_limiter = rate_limiter
        self._http_session = http_session or requests.Session()
        self._timeout_seconds = timeout_seconds
        self._default_limit_config = default_limit_config or ExternalHttpLimitConfig(
            max_concurrent_requests=1,
            requests_per_minute=None,
            tokens_per_minute=None,
            retry_on_429=False,
            max_retry_attempts=0,
            default_retry_backoff_ms=500,
            max_retry_backoff_ms=5_000,
            acquire_timeout_ms=30_000,
        )

    @staticmethod
    def capabilities() -> AdapterCapabilities:
        return AdapterCapabilities(
            block_render=True,
            bounded_concurrency=True,
            external_http_api=True,
            remote_runtime=True,
        )

    def render_block(self, request: BlockRenderRequest) -> BlockRenderResult:
        payload = self._resolve_payload(request)
        endpoint = payload.get("endpoint") or {}
        endpoint_url = str(endpoint.get("url") or "").strip()
        if not endpoint_url:
            raise BlockAdapterError(error_code="invalid_request", message="External HTTP endpoint url is required.")
        limit_config = self._resolve_limit_config(request)
        bucket_key = self._build_bucket_key(request=request, endpoint_url=endpoint_url)
        requested_tokens = self._estimate_tokens(str(payload.get("text") or ""))
        attempt = 0
        while True:
            try:
                reservation = self._rate_limiter.acquire(
                    bucket_key=bucket_key,
                    config=limit_config,
                    requested_tokens=requested_tokens,
                )
            except TimeoutError as exc:
                limiter_state = self._rate_limiter.get_state(bucket_key)
                raise BlockAdapterError(
                    error_code="rate_limited",
                    message="Timed out while waiting for external HTTP provider capacity.",
                    details={
                        "provider_http_status": limiter_state.last_provider_status,
                        "provider_error_code": None,
                        "provider_message": str(exc),
                        "provider_request_id": limiter_state.last_provider_request_id,
                        "retryable": True,
                        "retry_after_ms": 0,
                        "limit_bucket_key": bucket_key,
                        "response_excerpt": "",
                    },
                ) from exc
            try:
                response = self._post_request(
                    endpoint_url=endpoint_url,
                    payload=payload,
                    secret_handles=request.model_binding.secret_handles,
                    bucket_key=bucket_key,
                )
            finally:
                reservation.release()
            if 200 <= response.status_code < 300:
                return self._build_success_result(request=request, response=response)
            adapter_error = self._build_error(
                request=request,
                response=response,
                bucket_key=bucket_key,
                limit_config=limit_config,
            )
            if adapter_error.error_code == "rate_limited":
                retry_after_ms = int(adapter_error.details.get("retry_after_ms") or 0)
                self._rate_limiter.record_cooldown(
                    bucket_key=bucket_key,
                    retry_after_ms=retry_after_ms,
                    provider_status=response.status_code,
                    provider_request_id=adapter_error.details.get("provider_request_id"),
                )
                if limit_config.retry_on_429 and attempt < limit_config.max_retry_attempts:
                    time.sleep(max(retry_after_ms, limit_config.default_retry_backoff_ms) / 1000.0)
                    attempt += 1
                    continue
            raise adapter_error

    def _post_request(
        self,
        *,
        endpoint_url: str,
        payload: dict[str, Any],
        secret_handles: dict[str, str],
        bucket_key: str,
    ):
        headers: dict[str, str] = {}
        api_key_handle = secret_handles.get("api_key")
        if api_key_handle:
            headers["Authorization"] = f"Bearer {self._secret_store.resolve_handle(api_key_handle)}"
        try:
            return self._http_session.post(
                endpoint_url,
                json=payload,
                headers=headers,
                timeout=self._timeout_seconds,
            )
        except requests.Timeout as exc:
            raise BlockAdapterError(
                error_code="timeout",
                message="External HTTP TTS request timed out.",
                details={
                    "provider_http_status": 408,
                    "provider_error_code": None,
                    "provider_message": str(exc),
                    "provider_request_id": None,
                    "retryable": True,
                    "retry_after_ms": 0,
                    "limit_bucket_key": bucket_key,
                    "response_excerpt": "",
                },
            ) from exc
        except requests.RequestException as exc:
            raise BlockAdapterError(
                error_code="adapter_unavailable",
                message="External HTTP TTS request failed.",
                details={
                    "provider_http_status": None,
                    "provider_error_code": None,
                    "provider_message": str(exc),
                    "provider_request_id": None,
                    "retryable": True,
                    "retry_after_ms": 0,
                    "limit_bucket_key": bucket_key,
                    "response_excerpt": "",
                },
            ) from exc

    @staticmethod
    def _resolve_payload(request: BlockRenderRequest) -> dict[str, Any]:
        payload = request.adapter_options.get("external_http_tts")
        if isinstance(payload, dict):
            return payload
        return {
            "text": request.block.block_text,
            "model_instance_id": request.model_binding.model_instance_id,
            "preset_id": request.model_binding.preset_id,
            "remote_voice_id": request.model_binding.preset_fixed_fields.get("remote_voice_id"),
            "endpoint": dict(request.model_binding.endpoint or {}),
            "reference": dict(request.model_binding.resolved_reference or {}),
            "synthesis": dict(request.model_binding.resolved_parameters),
            "metadata": {
                "provider": request.model_binding.account_binding.get("provider"),
                "account_id": request.model_binding.account_binding.get("account_id"),
            },
        }

    def _resolve_limit_config(self, request: BlockRenderRequest) -> ExternalHttpLimitConfig:
        options = dict(self._default_limit_config.__dict__)
        options.update(request.model_binding.adapter_options or {})
        return ExternalHttpLimitConfig(
            max_concurrent_requests=max(int(options.get("max_concurrent_requests", 1)), 1),
            requests_per_minute=self._optional_int(options.get("requests_per_minute")),
            tokens_per_minute=self._optional_int(options.get("tokens_per_minute")),
            retry_on_429=bool(options.get("retry_on_429", self._default_limit_config.retry_on_429)),
            max_retry_attempts=max(int(options.get("max_retry_attempts", self._default_limit_config.max_retry_attempts)), 0),
            default_retry_backoff_ms=max(int(options.get("default_retry_backoff_ms", self._default_limit_config.default_retry_backoff_ms)), 0),
            max_retry_backoff_ms=max(int(options.get("max_retry_backoff_ms", self._default_limit_config.max_retry_backoff_ms)), 0),
            acquire_timeout_ms=max(int(options.get("acquire_timeout_ms", self._default_limit_config.acquire_timeout_ms)), 1),
        )

    @staticmethod
    def _optional_int(value: Any) -> int | None:
        if value in {None, "", 0}:
            return None if value in {None, ""} else int(value)
        return int(value)

    @staticmethod
    def _estimate_tokens(text: str) -> int:
        return max(1, len(text.strip()) or 1)

    @staticmethod
    def _build_bucket_key(*, request: BlockRenderRequest, endpoint_url: str) -> str:
        account_binding = request.model_binding.account_binding or {}
        provider = account_binding.get("provider")
        account_id = account_binding.get("account_id")
        if provider and account_id:
            return f"{provider}:{account_id}:{endpoint_url}"
        return f"{request.model_binding.adapter_id}:{endpoint_url}:{request.model_binding.model_instance_id}"

    def _build_success_result(self, *, request: BlockRenderRequest, response) -> BlockRenderResult:
        sample_rate, audio = self._parse_wav_bytes(response.content)
        return BlockRenderResult(
            block_id=request.block.block_id,
            segment_ids=[segment.segment_id for segment in request.block.segments],
            sample_rate=sample_rate,
            audio=audio,
            audio_sample_count=len(audio),
            segment_alignment_mode="block_only",
        )

    @staticmethod
    def _parse_wav_bytes(payload: bytes) -> tuple[int, list[float]]:
        try:
            with wave.open(io.BytesIO(payload), "rb") as wav_file:
                sample_rate = wav_file.getframerate()
                frames = wav_file.readframes(wav_file.getnframes())
        except wave.Error as exc:
            raise BlockAdapterError(
                error_code="render_failed",
                message="External HTTP TTS returned an invalid WAV payload.",
                details={"provider_message": str(exc), "retryable": False},
            ) from exc
        pcm = np.frombuffer(frames, dtype=np.int16)
        audio = (pcm.astype(np.float32) / 32768.0).tolist()
        return sample_rate, audio

    def _build_error(
        self,
        *,
        request: BlockRenderRequest,
        response,
        bucket_key: str,
        limit_config: ExternalHttpLimitConfig,
    ) -> BlockAdapterError:
        response_json = self._try_parse_json(response)
        provider_message = self._extract_provider_message(response_json) or response.text or "provider request failed"
        provider_error_code = self._extract_provider_error_code(response_json)
        provider_request_id = response.headers.get("x-request-id") or response.headers.get("request-id")
        retry_after_ms = self._resolve_retry_after_ms(
            raw_value=response.headers.get("Retry-After"),
            limit_config=limit_config,
        )
        error_code = self._map_status_to_error_code(response.status_code)
        retryable = error_code in {"rate_limited", "timeout", "adapter_unavailable"}
        return BlockAdapterError(
            error_code=error_code,
            message=provider_message if error_code != "rate_limited" else "External HTTP provider rate limited the request.",
            details={
                "provider_http_status": response.status_code,
                "provider_error_code": provider_error_code,
                "provider_message": provider_message,
                "provider_request_id": provider_request_id,
                "retryable": retryable,
                "retry_after_ms": retry_after_ms,
                "limit_bucket_key": bucket_key,
                "response_excerpt": response.text[:200],
            },
        )

    @staticmethod
    def _try_parse_json(response) -> dict[str, Any] | None:
        try:
            payload = response.json()
        except Exception:
            return None
        return payload if isinstance(payload, dict) else None

    @staticmethod
    def _extract_provider_message(payload: dict[str, Any] | None) -> str | None:
        if payload is None:
            return None
        if isinstance(payload.get("message"), str):
            return payload["message"]
        error_payload = payload.get("error")
        if isinstance(error_payload, dict) and isinstance(error_payload.get("message"), str):
            return error_payload["message"]
        return None

    @staticmethod
    def _extract_provider_error_code(payload: dict[str, Any] | None) -> str | None:
        if payload is None:
            return None
        if isinstance(payload.get("code"), str):
            return payload["code"]
        error_payload = payload.get("error")
        if isinstance(error_payload, dict) and isinstance(error_payload.get("code"), str):
            return error_payload["code"]
        return None

    @staticmethod
    def _parse_retry_after_ms(raw_value: str | None) -> int:
        if raw_value is None:
            return 0
        try:
            return max(int(float(raw_value) * 1000), 0)
        except ValueError:
            return 0

    def _resolve_retry_after_ms(self, *, raw_value: str | None, limit_config: ExternalHttpLimitConfig) -> int:
        parsed = self._parse_retry_after_ms(raw_value)
        if parsed > 0:
            return min(parsed, max(limit_config.max_retry_backoff_ms, 0))
        if limit_config.default_retry_backoff_ms <= 0:
            return 0
        if limit_config.max_retry_backoff_ms <= 0:
            return limit_config.default_retry_backoff_ms
        return min(limit_config.default_retry_backoff_ms, limit_config.max_retry_backoff_ms)

    @staticmethod
    def _map_status_to_error_code(status_code: int):
        if status_code in {400, 404, 422}:
            return "invalid_request"
        if status_code in {401, 403}:
            return "adapter_unavailable"
        if status_code == 408:
            return "timeout"
        if status_code == 429:
            return "rate_limited"
        if status_code == 402:
            return "quota_exceeded"
        if 500 <= status_code <= 599:
            return "adapter_unavailable"
        return "render_failed"
