import json
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


def test_edit_session_event_stream_replays_segment_progress_and_timeline_commit(test_app_settings):
    app = create_app(settings=test_app_settings)
    app.state.editable_inference_gateway = EditableInferenceGateway(FakeEditableInferenceBackend())
    with TestClient(app) as client:
        initialize = client.post(
            "/v1/edit-session/render-jobs",
            json={
                "raw_text": "第一句。第二句。",
                "voice_id": "demo",
            },
        )
        assert initialize.status_code == 202
        job_id = initialize.json()["job"]["job_id"]

        _wait_until(lambda: client.get(f"/v1/edit-session/render-jobs/{job_id}").json()["status"] == "completed")

        captured: list[tuple[str, dict]] = []
        with client.stream("GET", f"/v1/edit-session/render-jobs/{job_id}/events") as response:
            assert response.status_code == 200
            current_event = ""
            for line in response.iter_lines():
                if line.startswith("event: "):
                    current_event = line.removeprefix("event: ")
                    continue
                if not line.startswith("data: "):
                    continue
                payload = json.loads(line.removeprefix("data: "))
                captured.append((current_event, payload))
                if current_event == "job_state_changed" and payload.get("status") == "completed":
                    break

        interesting = [event for event, _ in captured if event in {"segments_initialized", "segment_completed", "timeline_committed"}]
        assert "segments_initialized" in interesting
        assert "segment_completed" in interesting
        assert "timeline_committed" in interesting
        assert interesting.index("segments_initialized") < interesting.index("segment_completed")
        assert interesting.index("segment_completed") < interesting.index("timeline_committed")


def test_edit_session_edit_job_event_stream_replays_segment_and_block_progress_before_pause(test_app_settings):
    app = create_app(settings=test_app_settings)
    fake_backend = FakeEditableInferenceBackend()
    app.state.editable_inference_gateway = EditableInferenceGateway(fake_backend)
    with TestClient(app) as client:
        initialize = client.post(
            "/v1/edit-session/render-jobs",
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

        pause_response = client.post(f"/v1/edit-session/render-jobs/{edit_job_id}/pause")
        assert pause_response.status_code == 200
        gate.set()
        _wait_until(lambda: client.get(f"/v1/edit-session/render-jobs/{edit_job_id}").json()["status"] == "paused")

        captured: list[tuple[str, dict]] = []
        with client.stream("GET", f"/v1/edit-session/render-jobs/{edit_job_id}/events") as response:
            assert response.status_code == 200
            current_event = ""
            for line in response.iter_lines():
                if line.startswith("event: "):
                    current_event = line.removeprefix("event: ")
                    continue
                if not line.startswith("data: "):
                    continue
                payload = json.loads(line.removeprefix("data: "))
                captured.append((current_event, payload))
                if current_event == "job_paused":
                    break

        interesting = [
            event
            for event, _ in captured
            if event in {"segment_completed", "block_completed", "timeline_committed", "job_paused"}
        ]
        assert "segment_completed" in interesting
        assert "block_completed" in interesting
        assert "timeline_committed" in interesting
        assert "job_paused" in interesting
        assert interesting.index("segment_completed") < interesting.index("block_completed")
        assert interesting.index("block_completed") < interesting.index("timeline_committed")
        assert interesting.index("timeline_committed") < interesting.index("job_paused")


def test_edit_session_event_stream_replays_prepare_progress_before_segments_initialized(test_app_settings):
    class _PrepareProgressBackend(FakeEditableInferenceBackend):
        def build_reference_context(self, resolved_context, *, progress_callback=None):
            if callable(progress_callback):
                progress_callback(
                    {
                        "status": "preparing",
                        "progress": 0.5,
                        "message": "参考上下文准备中",
                    }
                )
            return super().build_reference_context(resolved_context)

    app = create_app(settings=test_app_settings)
    app.state.editable_inference_gateway = EditableInferenceGateway(_PrepareProgressBackend())
    with TestClient(app) as client:
        initialize = client.post(
            "/v1/edit-session/render-jobs",
            json={
                "raw_text": "第一句。第二句。",
                "voice_id": "demo",
            },
        )
        assert initialize.status_code == 202
        job_id = initialize.json()["job"]["job_id"]

        _wait_until(lambda: client.get(f"/v1/edit-session/render-jobs/{job_id}").json()["status"] == "completed")

        captured: list[tuple[str, dict]] = []
        with client.stream("GET", f"/v1/edit-session/render-jobs/{job_id}/events") as response:
            assert response.status_code == 200
            current_event = ""
            for line in response.iter_lines():
                if line.startswith("event: "):
                    current_event = line.removeprefix("event: ")
                    continue
                if not line.startswith("data: "):
                    continue
                payload = json.loads(line.removeprefix("data: "))
                captured.append((current_event, payload))
                if current_event == "job_state_changed" and payload.get("status") == "completed":
                    break

        interesting: list[str] = []
        for event, payload in captured:
            if event == "job_state_changed" and payload.get("status") == "preparing" and payload.get("progress", 0) > 0.05:
                interesting.append("prepare_progress")
            elif event == "segments_initialized":
                interesting.append("segments_initialized")

        assert "prepare_progress" in interesting
        assert "segments_initialized" in interesting
        assert interesting.index("prepare_progress") < interesting.index("segments_initialized")
