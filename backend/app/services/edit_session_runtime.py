from __future__ import annotations

from contextlib import suppress
from datetime import datetime, timezone
import queue
import threading
import time
from typing import Any

from backend.app.schemas.edit_session import RenderJobResponse


class EditSessionRuntime:
    ACTIVE_STATUSES = {
        "preparing",
        "rendering",
        "composing",
        "committing",
        "pause_requested",
        "cancel_requested",
    }
    TERMINAL_STATUSES = {"paused", "cancelled_partial", "completed", "failed"}

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._jobs: dict[str, RenderJobResponse] = {}
        self._active_job_id: str | None = None
        self._subscribers: dict[str, set[queue.Queue[dict[str, Any]]]] = {}
        self._events: dict[str, list[dict[str, Any]]] = {}

    def start_job(self, job: RenderJobResponse) -> None:
        with self._lock:
            self.assert_can_start()
            started_job = job.model_copy(deep=True)
            if started_job.status == "queued":
                started_job.status = "preparing"
            started_job.updated_at = datetime.now(timezone.utc)
            self._jobs[started_job.job_id] = started_job
            self._active_job_id = started_job.job_id
            self._events[started_job.job_id] = []
            self._append_job_state_event_locked(started_job.job_id)

    def update_job(self, job_id: str, **changes: Any) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return
            for field_name, value in changes.items():
                if not hasattr(job, field_name):
                    continue
                if field_name == "progress" and value is not None:
                    value = max(0.0, min(1.0, float(value)))
                setattr(job, field_name, value)
            job.updated_at = datetime.now(timezone.utc)
            if job.status not in self.ACTIVE_STATUSES and self._active_job_id == job_id:
                self._active_job_id = None
            self._append_job_state_event_locked(job_id)

    def request_pause(self, job_id: str) -> bool:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None or job.status not in self.ACTIVE_STATUSES:
                return False
            job.pause_requested = True
            job.status = "pause_requested"
            job.updated_at = datetime.now(timezone.utc)
            self._append_job_state_event_locked(job_id)
            return True

    def request_cancel(self, job_id: str) -> bool:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None or job.status not in self.ACTIVE_STATUSES:
                return False
            job.cancel_requested = True
            job.status = "cancel_requested"
            job.updated_at = datetime.now(timezone.utc)
            self._append_job_state_event_locked(job_id)
            return True

    def emit_event(self, job_id: str, event_type: str, payload: dict[str, Any]) -> None:
        with self._lock:
            if job_id not in self._jobs:
                return
            self._append_event_locked(job_id, event_type, payload)

    def assert_can_start(self) -> None:
        if self._active_job_id is None:
            return
        active_job = self._jobs.get(self._active_job_id)
        if active_job is None or active_job.status not in self.ACTIVE_STATUSES:
            return
        raise RuntimeError("An active render job is already running.")

    def subscribe(self, job_id: str) -> queue.Queue[dict[str, Any]]:
        subscriber: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=64)
        with self._lock:
            subscribers = self._subscribers.setdefault(job_id, set())
            subscribers.add(subscriber)
            for event in self._events.get(job_id, []):
                self._put_nowait(subscriber, event)
        return subscriber

    def unsubscribe(self, job_id: str, subscriber: queue.Queue[dict[str, Any]]) -> None:
        with self._lock:
            subscribers = self._subscribers.get(job_id)
            if subscribers is None:
                return
            subscribers.discard(subscriber)
            if not subscribers:
                self._subscribers.pop(job_id, None)

    def get_job(self, job_id: str) -> RenderJobResponse | None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return None
            return job.model_copy(deep=True)

    def wait_for_job_terminal(
        self,
        job_id: str,
        *,
        timeout_seconds: float = 10.0,
        poll_interval_seconds: float = 0.05,
    ) -> RenderJobResponse | None:
        deadline = time.monotonic() + timeout_seconds
        while True:
            snapshot = self.get_job(job_id)
            if snapshot is None or snapshot.status in self.TERMINAL_STATUSES:
                return snapshot
            if time.monotonic() >= deadline:
                raise TimeoutError(f"Timed out waiting for render job '{job_id}' to reach a terminal state.")
            time.sleep(poll_interval_seconds)

    def reset(self) -> None:
        with self._lock:
            self._jobs.clear()
            self._events.clear()
            self._subscribers.clear()
            self._active_job_id = None

    def _append_job_state_event_locked(self, job_id: str) -> None:
        job = self._jobs.get(job_id)
        if job is None:
            return
        self._append_event_locked(job_id, "job_state_changed", job.model_dump(mode="json"))

    def _append_event_locked(self, job_id: str, event_type: str, payload: dict[str, Any]) -> None:
        event = {
            "event": event_type,
            "data": payload,
        }
        history = self._events.setdefault(job_id, [])
        history.append(event)
        if len(history) > 256:
            del history[:-256]
        stale: list[queue.Queue[dict[str, Any]]] = []
        for subscriber in self._subscribers.get(job_id, set()):
            try:
                self._put_nowait(subscriber, event)
            except Exception:
                stale.append(subscriber)
        for subscriber in stale:
            subscribers = self._subscribers.get(job_id)
            if subscribers is not None:
                subscribers.discard(subscriber)

    @staticmethod
    def _put_nowait(subscriber: queue.Queue[dict[str, Any]], payload: dict[str, Any]) -> None:
        if subscriber.full():
            with suppress(queue.Empty):
                subscriber.get_nowait()
        subscriber.put_nowait(payload)
