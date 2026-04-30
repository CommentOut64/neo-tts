import threading
import time

from fastapi.testclient import TestClient

from backend.app.inference.editable_gateway import EditableInferenceGateway
from backend.app.main import create_app
from backend.tests.integration.test_edit_session_router import FakeEditableInferenceBackend


def _wait_until(predicate, *, timeout: float = 5.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return
        time.sleep(0.05)
    raise AssertionError("Condition not met before timeout.")


def test_edit_session_cancel_returns_partial_head_and_keeps_timeline_playable(test_app_settings):
    gate = threading.Event()
    app = create_app(settings=test_app_settings)
    app.state.editable_inference_gateway = EditableInferenceGateway(
        FakeEditableInferenceBackend(gate=gate, wait_timeout=None)
    )
    with TestClient(app) as client:
        initialize = client.post(
            "/v1/edit-session/initialize",
            json={
                "raw_text": "第一句。第二句。第三句。",
                "voice_id": "demo",
            },
        )
        assert initialize.status_code == 202
        job_id = initialize.json()["job"]["job_id"]

        cancel_response = client.post(f"/v1/edit-session/render-jobs/{job_id}/cancel")
        assert cancel_response.status_code == 200
        assert cancel_response.json()["cancel_requested"] is True

        gate.set()
        _wait_until(
            lambda: client.get(f"/v1/edit-session/render-jobs/{job_id}").json()["status"] == "cancelled_partial"
        )

        snapshot = client.get("/v1/edit-session/snapshot").json()
        assert snapshot["document_version"] == 1
        assert snapshot["total_segment_count"] == 1
        assert len(snapshot["segments"]) == 1

        checkpoint = client.get("/v1/edit-session/checkpoints/current")
        assert checkpoint.status_code == 200
        checkpoint_payload = checkpoint.json()["checkpoint"]
        assert checkpoint_payload["status"] == "cancelled_partial"
        assert checkpoint_payload["resume_token"] is None
        assert not (app.state.edit_asset_store._staging_root / job_id).exists()  # noqa: SLF001

        timeline = client.get("/v1/edit-session/timeline")
        assert timeline.status_code == 200
        timeline_payload = timeline.json()
        assert len(timeline_payload["segment_entries"]) == 1
        assert timeline_payload["playable_sample_span"][1] > 0


def test_edit_session_edit_job_cancel_returns_partial_head_and_keeps_timeline_playable(test_app_settings):
    app = create_app(settings=test_app_settings)
    fake_backend = FakeEditableInferenceBackend()
    app.state.editable_inference_gateway = EditableInferenceGateway(fake_backend)
    with TestClient(app) as client:
        initialize = client.post(
            "/v1/edit-session/initialize",
            json={
                "raw_text": "第一句。第二句。",
                "voice_id": "demo",
            },
        )
        assert initialize.status_code == 202
        initialize_job_id = initialize.json()["job"]["job_id"]
        _wait_until(lambda: client.get(f"/v1/edit-session/render-jobs/{initialize_job_id}").json()["status"] == "completed")

        gate = threading.Event()
        fake_backend.gate = gate
        fake_backend.wait_timeout = None

        append_response = client.post(
            "/v1/edit-session/append",
            json={
                "raw_text": "第三句。第四句。",
                "voice_id": "demo",
            },
        )
        assert append_response.status_code == 202
        edit_job_id = append_response.json()["job"]["job_id"]

        cancel_response = client.post(f"/v1/edit-session/render-jobs/{edit_job_id}/cancel")
        assert cancel_response.status_code == 200
        assert cancel_response.json()["cancel_requested"] is True

        gate.set()
        _wait_until(
            lambda: client.get(f"/v1/edit-session/render-jobs/{edit_job_id}").json()["status"] == "cancelled_partial"
        )

        snapshot = client.get("/v1/edit-session/snapshot").json()
        assert snapshot["document_version"] == 2
        assert snapshot["total_segment_count"] == 3
        assert len(snapshot["segments"]) == 3

        checkpoint = client.get("/v1/edit-session/checkpoints/current")
        assert checkpoint.status_code == 200
        checkpoint_payload = checkpoint.json()["checkpoint"]
        assert checkpoint_payload["job_id"] == edit_job_id
        assert checkpoint_payload["status"] == "cancelled_partial"
        assert checkpoint_payload["resume_token"] is None
        assert len(checkpoint_payload["remaining_segment_ids"]) == 1
        assert not (app.state.edit_asset_store._staging_root / edit_job_id).exists()  # noqa: SLF001

        timeline = client.get("/v1/edit-session/timeline")
        assert timeline.status_code == 200
        timeline_payload = timeline.json()
        assert len(timeline_payload["segment_entries"]) == 3
        assert timeline_payload["playable_sample_span"][1] > 0
