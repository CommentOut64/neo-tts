from __future__ import annotations

from dataclasses import dataclass, field
import threading
import time


@dataclass(frozen=True)
class ExternalHttpLimitConfig:
    max_concurrent_requests: int
    requests_per_minute: int | None
    tokens_per_minute: int | None
    retry_on_429: bool
    max_retry_attempts: int
    default_retry_backoff_ms: int
    max_retry_backoff_ms: int
    acquire_timeout_ms: int


@dataclass
class ExternalHttpLimitBucketState:
    bucket_key: str
    active_requests: int = 0
    rpm_window_started_at: float = 0.0
    rpm_used: int = 0
    tpm_window_started_at: float = 0.0
    tpm_used: int = 0
    cooldown_until: float | None = None
    last_provider_status: int | None = None
    last_provider_request_id: str | None = None
    waiter_count: int = 0


@dataclass
class _BucketControl:
    state: ExternalHttpLimitBucketState
    condition: threading.Condition = field(default_factory=lambda: threading.Condition(threading.Lock()))


class ExternalHttpReservation:
    def __init__(self, *, limiter: "ExternalHttpRateLimiter", bucket_key: str) -> None:
        self._limiter = limiter
        self.bucket_key = bucket_key
        self._released = False

    def release(self) -> None:
        if self._released:
            return
        self._released = True
        self._limiter.release(self.bucket_key)


class ExternalHttpRateLimiter:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._buckets: dict[str, _BucketControl] = {}

    def acquire(
        self,
        *,
        bucket_key: str,
        config: ExternalHttpLimitConfig,
        requested_tokens: int,
    ) -> ExternalHttpReservation:
        bucket = self._get_bucket(bucket_key)
        deadline = time.monotonic() + max(config.acquire_timeout_ms, 1) / 1000.0
        with bucket.condition:
            while True:
                now = time.monotonic()
                self._reset_windows_if_needed(bucket.state, now)
                wait_seconds = self._compute_wait_seconds(
                    state=bucket.state,
                    config=config,
                    requested_tokens=requested_tokens,
                    now=now,
                )
                if wait_seconds <= 0:
                    bucket.state.active_requests += 1
                    if config.requests_per_minute is not None:
                        bucket.state.rpm_used += 1
                    if config.tokens_per_minute is not None:
                        bucket.state.tpm_used += requested_tokens
                    return ExternalHttpReservation(limiter=self, bucket_key=bucket_key)
                remaining = deadline - now
                if remaining <= 0:
                    raise TimeoutError(f"Timed out waiting for external HTTP bucket '{bucket_key}'.")
                bucket.state.waiter_count += 1
                try:
                    bucket.condition.wait(timeout=min(wait_seconds, remaining))
                finally:
                    bucket.state.waiter_count = max(0, bucket.state.waiter_count - 1)

    def release(self, bucket_key: str) -> None:
        bucket = self._get_bucket(bucket_key)
        with bucket.condition:
            bucket.state.active_requests = max(0, bucket.state.active_requests - 1)
            bucket.condition.notify_all()

    def record_cooldown(
        self,
        *,
        bucket_key: str,
        retry_after_ms: int,
        provider_status: int,
        provider_request_id: str | None,
    ) -> None:
        bucket = self._get_bucket(bucket_key)
        with bucket.condition:
            now = time.monotonic()
            cooldown_until = now + max(retry_after_ms, 0) / 1000.0
            bucket.state.cooldown_until = max(bucket.state.cooldown_until or 0.0, cooldown_until)
            bucket.state.last_provider_status = provider_status
            bucket.state.last_provider_request_id = provider_request_id
            bucket.condition.notify_all()

    def get_state(self, bucket_key: str) -> ExternalHttpLimitBucketState:
        bucket = self._get_bucket(bucket_key)
        with bucket.condition:
            return ExternalHttpLimitBucketState(
                bucket_key=bucket.state.bucket_key,
                active_requests=bucket.state.active_requests,
                rpm_window_started_at=bucket.state.rpm_window_started_at,
                rpm_used=bucket.state.rpm_used,
                tpm_window_started_at=bucket.state.tpm_window_started_at,
                tpm_used=bucket.state.tpm_used,
                cooldown_until=bucket.state.cooldown_until,
                last_provider_status=bucket.state.last_provider_status,
                last_provider_request_id=bucket.state.last_provider_request_id,
                waiter_count=bucket.state.waiter_count,
            )

    def _get_bucket(self, bucket_key: str) -> _BucketControl:
        with self._lock:
            bucket = self._buckets.get(bucket_key)
            if bucket is not None:
                return bucket
            control = _BucketControl(state=ExternalHttpLimitBucketState(bucket_key=bucket_key))
            self._buckets[bucket_key] = control
            return control

    @staticmethod
    def _reset_windows_if_needed(state: ExternalHttpLimitBucketState, now: float) -> None:
        if state.rpm_window_started_at == 0.0:
            state.rpm_window_started_at = now
        elif now - state.rpm_window_started_at >= 60.0:
            state.rpm_window_started_at = now
            state.rpm_used = 0
        if state.tpm_window_started_at == 0.0:
            state.tpm_window_started_at = now
        elif now - state.tpm_window_started_at >= 60.0:
            state.tpm_window_started_at = now
            state.tpm_used = 0
        if state.cooldown_until is not None and state.cooldown_until <= now:
            state.cooldown_until = None

    @staticmethod
    def _compute_wait_seconds(
        *,
        state: ExternalHttpLimitBucketState,
        config: ExternalHttpLimitConfig,
        requested_tokens: int,
        now: float,
    ) -> float:
        waits: list[float] = []
        if state.cooldown_until is not None and state.cooldown_until > now:
            waits.append(state.cooldown_until - now)
        if state.active_requests >= max(config.max_concurrent_requests, 1):
            waits.append(0.05)
        if config.requests_per_minute is not None and state.rpm_used >= config.requests_per_minute:
            waits.append(max(0.0, 60.0 - (now - state.rpm_window_started_at)))
        if (
            config.tokens_per_minute is not None
            and state.tpm_used + requested_tokens > config.tokens_per_minute
        ):
            waits.append(max(0.0, 60.0 - (now - state.tpm_window_started_at)))
        return max(waits, default=0.0)
