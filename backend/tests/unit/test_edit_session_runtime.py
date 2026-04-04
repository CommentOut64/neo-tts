import pytest

from backend.app.schemas.edit_session import RenderJobResponse
from backend.app.services.edit_session_runtime import EditSessionRuntime


def _build_job(*, job_id: str, status: str = "preparing") -> RenderJobResponse:
    return RenderJobResponse(
        job_id=job_id,
        document_id="doc-1",
        status=status,
        progress=0.0,
        message="starting",
        cancel_requested=False,
        pause_requested=False,
    )


def test_edit_session_runtime_rejects_second_active_job():
    runtime = EditSessionRuntime()
    runtime.start_job(_build_job(job_id="job-1"))

    with pytest.raises(RuntimeError, match="active render job"):
        runtime.start_job(_build_job(job_id="job-2"))


def test_edit_session_runtime_supports_pause_and_cancel_snapshot():
    runtime = EditSessionRuntime()
    runtime.start_job(_build_job(job_id="job-1"))

    pause_accepted = runtime.request_pause("job-1")
    paused_snapshot = runtime.get_job("job-1")
    accepted = runtime.request_cancel("job-1")
    snapshot = runtime.get_job("job-1")

    assert pause_accepted is True
    assert paused_snapshot is not None
    assert paused_snapshot.pause_requested is True
    assert paused_snapshot.status == "pause_requested"
    assert accepted is True
    assert snapshot is not None
    assert snapshot.cancel_requested is True
    assert snapshot.status == "cancel_requested"


def test_edit_session_runtime_broadcasts_typed_events():
    runtime = EditSessionRuntime()
    runtime.start_job(_build_job(job_id="job-1"))
    subscriber = runtime.subscribe("job-1")

    initial_payload = subscriber.get(timeout=1)
    runtime.update_job("job-1", status="rendering", progress=0.5, message="half")
    runtime.emit_event("job-1", "segment_completed", {"segment_id": "seg-1"})
    updated_payload = subscriber.get(timeout=1)
    domain_payload = subscriber.get(timeout=1)

    assert initial_payload["event"] == "job_state_changed"
    assert initial_payload["data"]["job_id"] == "job-1"
    assert updated_payload["event"] == "job_state_changed"
    assert updated_payload["data"]["status"] == "rendering"
    assert updated_payload["data"]["progress"] == 0.5
    assert domain_payload == {"event": "segment_completed", "data": {"segment_id": "seg-1"}}
