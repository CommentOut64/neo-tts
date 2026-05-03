import threading
import time

import pytest

from backend.app.inference.external_http_rate_limiter import (
    ExternalHttpLimitConfig,
    ExternalHttpRateLimiter,
)


def test_external_http_rate_limiter_blocks_second_request_until_first_releases():
    limiter = ExternalHttpRateLimiter()
    config = ExternalHttpLimitConfig(
        max_concurrent_requests=1,
        requests_per_minute=None,
        tokens_per_minute=None,
        retry_on_429=True,
        max_retry_attempts=1,
        default_retry_backoff_ms=100,
        max_retry_backoff_ms=500,
        acquire_timeout_ms=1_000,
    )
    first = limiter.acquire(bucket_key="provider:acct-1:https://api.example.com/tts", config=config, requested_tokens=10)
    events: list[str] = []

    def _acquire_later() -> None:
        events.append("waiting")
        reservation = limiter.acquire(
            bucket_key="provider:acct-1:https://api.example.com/tts",
            config=config,
            requested_tokens=10,
        )
        events.append("acquired")
        reservation.release()

    worker = threading.Thread(target=_acquire_later, daemon=True)
    worker.start()
    time.sleep(0.1)

    assert events == ["waiting"]

    first.release()
    worker.join(timeout=1)

    assert events == ["waiting", "acquired"]


def test_external_http_rate_limiter_persists_retry_after_cooldown_in_shared_bucket():
    limiter = ExternalHttpRateLimiter()
    config = ExternalHttpLimitConfig(
        max_concurrent_requests=1,
        requests_per_minute=None,
        tokens_per_minute=None,
        retry_on_429=True,
        max_retry_attempts=2,
        default_retry_backoff_ms=100,
        max_retry_backoff_ms=1_000,
        acquire_timeout_ms=1_000,
    )
    bucket_key = "provider:acct-1:https://api.example.com/tts"
    reservation = limiter.acquire(bucket_key=bucket_key, config=config, requested_tokens=5)
    reservation.release()

    limiter.record_cooldown(
        bucket_key=bucket_key,
        retry_after_ms=750,
        provider_status=429,
        provider_request_id="req-429",
    )
    state = limiter.get_state(bucket_key)

    assert state.last_provider_status == 429
    assert state.last_provider_request_id == "req-429"
    assert state.cooldown_until is not None


def test_external_http_rate_limiter_times_out_when_rpm_window_is_exhausted():
    limiter = ExternalHttpRateLimiter()
    config = ExternalHttpLimitConfig(
        max_concurrent_requests=1,
        requests_per_minute=1,
        tokens_per_minute=None,
        retry_on_429=False,
        max_retry_attempts=0,
        default_retry_backoff_ms=100,
        max_retry_backoff_ms=500,
        acquire_timeout_ms=20,
    )
    bucket_key = "provider:acct-1:https://api.example.com/tts"

    limiter.acquire(bucket_key=bucket_key, config=config, requested_tokens=1).release()

    with pytest.raises(TimeoutError):
        limiter.acquire(bucket_key=bucket_key, config=config, requested_tokens=1)


def test_external_http_rate_limiter_times_out_when_tpm_window_is_exhausted():
    limiter = ExternalHttpRateLimiter()
    config = ExternalHttpLimitConfig(
        max_concurrent_requests=1,
        requests_per_minute=None,
        tokens_per_minute=5,
        retry_on_429=False,
        max_retry_attempts=0,
        default_retry_backoff_ms=100,
        max_retry_backoff_ms=500,
        acquire_timeout_ms=20,
    )
    bucket_key = "provider:acct-1:https://api.example.com/tts"

    limiter.acquire(bucket_key=bucket_key, config=config, requested_tokens=5).release()

    with pytest.raises(TimeoutError):
        limiter.acquire(bucket_key=bucket_key, config=config, requested_tokens=1)


def test_external_http_rate_limiter_shares_bucket_budget_state_across_callers():
    limiter = ExternalHttpRateLimiter()
    config = ExternalHttpLimitConfig(
        max_concurrent_requests=2,
        requests_per_minute=10,
        tokens_per_minute=100,
        retry_on_429=False,
        max_retry_attempts=0,
        default_retry_backoff_ms=100,
        max_retry_backoff_ms=500,
        acquire_timeout_ms=1_000,
    )
    bucket_key = "provider:acct-1:https://api.example.com/tts"

    first = limiter.acquire(bucket_key=bucket_key, config=config, requested_tokens=30)
    first.release()
    second = limiter.acquire(bucket_key=bucket_key, config=config, requested_tokens=20)
    second.release()
    state = limiter.get_state(bucket_key)

    assert state.rpm_used == 2
    assert state.tpm_used == 50
