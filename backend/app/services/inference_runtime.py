from __future__ import annotations

from contextlib import suppress
from datetime import UTC, datetime
import queue
import threading
import time
from uuid import uuid4

from backend.app.schemas.inference import InferenceProgressState


class InferenceRuntimeController:
    _ACTIVE_STATUSES = {"preparing", "inferencing", "cancelling"}
    TERMINAL_STATUSES = {"idle", "completed", "cancelled", "error"}

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._subscribers: set[queue.Queue[dict]] = set()
        self._state = InferenceProgressState()

    def snapshot(self) -> InferenceProgressState:
        with self._lock:
            return self._state.model_copy(deep=True)

    def subscribe(self) -> queue.Queue[dict]:
        subscriber: queue.Queue[dict] = queue.Queue(maxsize=64)
        with self._lock:
            self._subscribers.add(subscriber)
            self._put_nowait(subscriber, self._state.model_dump(mode="json"))
        return subscriber

    def unsubscribe(self, subscriber: queue.Queue[dict]) -> None:
        with self._lock:
            self._subscribers.discard(subscriber)

    def start_task(self, *, message: str) -> str:
        with self._lock:
            if self._state.status in self._ACTIVE_STATUSES:
                raise RuntimeError("An inference task is already running.")
            task_id = uuid4().hex
            self._state = InferenceProgressState(
                task_id=task_id,
                status="preparing",
                progress=0.0,
                message=message,
                cancel_requested=False,
                current_segment=None,
                total_segments=None,
                result_id=None,
                updated_at=datetime.now(UTC),
            )
            self._broadcast_locked()
            return task_id

    def should_cancel(self, task_id: str) -> bool:
        with self._lock:
            return self._state.task_id == task_id and self._state.cancel_requested

    def request_force_pause(self, *, message: str) -> bool:
        with self._lock:
            if self._state.status not in self._ACTIVE_STATUSES:
                return False
            self._state.status = "cancelling"
            self._state.cancel_requested = True
            self._state.message = message
            self._state.updated_at = datetime.now(UTC)
            self._broadcast_locked()
            return True

    def update_progress(
        self,
        *,
        task_id: str,
        status: str | None = None,
        progress: float | None = None,
        message: str | None = None,
        current_segment: int | None = None,
        total_segments: int | None = None,
    ) -> None:
        with self._lock:
            if self._state.task_id != task_id:
                return
            if status is not None:
                self._state.status = status
            if progress is not None:
                self._state.progress = max(0.0, min(1.0, float(progress)))
            if message is not None:
                self._state.message = message
            if current_segment is not None:
                self._state.current_segment = current_segment
            if total_segments is not None:
                self._state.total_segments = total_segments
            self._state.updated_at = datetime.now(UTC)
            self._broadcast_locked()

    def mark_completed(self, *, task_id: str, result_id: str | None = None, message: str = "推理完成。") -> None:
        with self._lock:
            if self._state.task_id != task_id:
                return
            self._state.status = "completed"
            self._state.progress = 1.0
            self._state.message = message
            self._state.cancel_requested = False
            self._state.result_id = result_id
            self._state.updated_at = datetime.now(UTC)
            self._broadcast_locked()

    def mark_cancelled(self, *, task_id: str, message: str) -> None:
        with self._lock:
            if self._state.task_id != task_id:
                return
            self._state.status = "cancelled"
            self._state.message = message
            self._state.cancel_requested = False
            self._state.updated_at = datetime.now(UTC)
            self._broadcast_locked()

    def mark_failed(self, *, task_id: str, message: str) -> None:
        with self._lock:
            if self._state.task_id != task_id:
                return
            self._state.status = "error"
            self._state.message = message
            self._state.cancel_requested = False
            self._state.updated_at = datetime.now(UTC)
            self._broadcast_locked()

    def reset_if_idle(self, *, message: str) -> bool:
        with self._lock:
            if self._state.status in self._ACTIVE_STATUSES:
                return False
            self._state = InferenceProgressState(message=message)
            self._broadcast_locked()
            return True

    def wait_for_terminal(
        self,
        *,
        timeout_seconds: float = 10.0,
        poll_interval_seconds: float = 0.05,
    ) -> InferenceProgressState:
        deadline = time.monotonic() + timeout_seconds
        while True:
            snapshot = self.snapshot()
            if snapshot.status in self.TERMINAL_STATUSES:
                return snapshot
            if time.monotonic() >= deadline:
                raise TimeoutError("Timed out waiting for inference runtime to reach a terminal state.")
            time.sleep(poll_interval_seconds)

    def _broadcast_locked(self) -> None:
        payload = self._state.model_dump(mode="json")
        stale: list[queue.Queue[dict]] = []
        for subscriber in self._subscribers:
            try:
                self._put_nowait(subscriber, payload)
            except Exception:
                stale.append(subscriber)
        for subscriber in stale:
            self._subscribers.discard(subscriber)

    @staticmethod
    def _put_nowait(subscriber: queue.Queue[dict], payload: dict) -> None:
        if subscriber.full():
            with suppress(queue.Empty):
                subscriber.get_nowait()
        subscriber.put_nowait(payload)
