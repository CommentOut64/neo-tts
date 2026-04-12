from __future__ import annotations

import threading
import time

import pytest

from backend.app.services.inference_runtime import InferenceRuntimeController


def _cancel_task_when_requested(runtime: InferenceRuntimeController, task_id: str) -> threading.Thread:
    def _worker() -> None:
        deadline = time.time() + 2
        while time.time() < deadline:
            if runtime.should_cancel(task_id):
                runtime.mark_cancelled(task_id=task_id, message="cancelled for exit")
                return
            time.sleep(0.01)
        raise AssertionError("force pause request was not observed before timeout")

    thread = threading.Thread(target=_worker)
    thread.start()
    return thread


def test_wait_for_terminal_returns_idle_snapshot_when_runtime_is_already_idle():
    runtime = InferenceRuntimeController()

    snapshot = runtime.wait_for_terminal()

    assert snapshot.status == "idle"


def test_wait_for_terminal_returns_cancelled_snapshot_after_force_pause():
    runtime = InferenceRuntimeController()
    task_id = runtime.start_task(message="running")
    runtime.update_progress(task_id=task_id, status="inferencing", progress=0.5, message="half")
    worker = _cancel_task_when_requested(runtime, task_id)

    accepted = runtime.request_force_pause(message="pause for exit")
    snapshot = runtime.wait_for_terminal(timeout_seconds=1.0, poll_interval_seconds=0.01)
    worker.join(timeout=2)

    assert accepted is True
    assert snapshot.task_id == task_id
    assert snapshot.status == "cancelled"


def test_wait_for_terminal_times_out_when_task_never_leaves_active_state():
    runtime = InferenceRuntimeController()
    task_id = runtime.start_task(message="running")
    runtime.update_progress(task_id=task_id, status="inferencing", progress=0.2, message="still running")

    with pytest.raises(TimeoutError, match="terminal state"):
        runtime.wait_for_terminal(timeout_seconds=0.05, poll_interval_seconds=0.01)
