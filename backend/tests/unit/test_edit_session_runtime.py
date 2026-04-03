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
    )


def test_edit_session_runtime_rejects_second_active_job():
    runtime = EditSessionRuntime()
    runtime.start_job(_build_job(job_id="job-1"))

    with pytest.raises(RuntimeError, match="active render job"):
        runtime.start_job(_build_job(job_id="job-2"))


def test_edit_session_runtime_supports_cancel_and_snapshot():
    runtime = EditSessionRuntime()
    runtime.start_job(_build_job(job_id="job-1"))

    accepted = runtime.request_cancel("job-1")
    snapshot = runtime.get_job("job-1")

    assert accepted is True
    assert snapshot is not None
    assert snapshot.cancel_requested is True
    assert snapshot.status == "cancelling"


def test_edit_session_runtime_broadcasts_per_job_updates():
    runtime = EditSessionRuntime()
    runtime.start_job(_build_job(job_id="job-1"))
    subscriber = runtime.subscribe("job-1")

    initial_payload = subscriber.get(timeout=1)
    runtime.update_job("job-1", status="rendering", progress=0.5, message="half")
    updated_payload = subscriber.get(timeout=1)

    assert initial_payload["job_id"] == "job-1"
    assert updated_payload["status"] == "rendering"
    assert updated_payload["progress"] == 0.5
