from __future__ import annotations

from contextlib import suppress
from datetime import datetime, timezone
from typing import Any
import queue
import threading

from backend.app.schemas.edit_session import RenderJobResponse


class EditSessionRuntime:
    ACTIVE_STATUSES = {"preparing", "rendering", "composing", "committing", "cancelling"}

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._jobs: dict[str, RenderJobResponse] = {}
        self._active_job_id: str | None = None
        self._subscribers: dict[str, set[queue.Queue[dict[str, Any]]]] = {}

    def start_job(self, job: RenderJobResponse) -> None:
        with self._lock:
            self.assert_can_start()
            started_job = job.model_copy(deep=True)
            if started_job.status == "queued":
                started_job.status = "preparing"
            started_job.updated_at = datetime.now(timezone.utc)
            self._jobs[started_job.job_id] = started_job
            self._active_job_id = started_job.job_id
            self._broadcast_locked(started_job.job_id)

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
            self._broadcast_locked(job_id)

    def request_cancel(self, job_id: str) -> bool:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None or job.status not in self.ACTIVE_STATUSES:
                return False
            job.cancel_requested = True
            job.status = "cancelling"
            job.updated_at = datetime.now(timezone.utc)
            self._broadcast_locked(job_id)
            return True

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
            job = self._jobs.get(job_id)
            if job is not None:
                self._put_nowait(subscriber, job.model_dump(mode="json"))
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

    def reset(self) -> None:
        with self._lock:
            self._jobs.clear()
            self._subscribers.clear()
            self._active_job_id = None

    def _broadcast_locked(self, job_id: str) -> None:
        job = self._jobs.get(job_id)
        if job is None:
            return
        payload = job.model_dump(mode="json")
        stale: list[queue.Queue[dict[str, Any]]] = []
        for subscriber in self._subscribers.get(job_id, set()):
            try:
                self._put_nowait(subscriber, payload)
            except Exception:
                stale.append(subscriber)
        for subscriber in stale:
            self._subscribers[job_id].discard(subscriber)

    @staticmethod
    def _put_nowait(subscriber: queue.Queue[dict[str, Any]], payload: dict[str, Any]) -> None:
        if subscriber.full():
            with suppress(queue.Empty):
                subscriber.get_nowait()
        subscriber.put_nowait(payload)
