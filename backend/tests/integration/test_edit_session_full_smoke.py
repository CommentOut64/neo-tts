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


def test_edit_session_full_smoke_covers_timeline_mutation_and_dual_exports(test_app_settings):
    gate = threading.Event()
    app = create_app(settings=test_app_settings)
    app.state.editable_inference_gateway = EditableInferenceGateway(FakeEditableInferenceBackend(gate=gate))
    segment_export_dir = test_app_settings.edit_session_exports_dir / "full-smoke-segments"
    composition_export_dir = test_app_settings.edit_session_exports_dir / "full-smoke-composition"

    with TestClient(app) as client:
        gate.set()
        initialize = client.post(
            "/v1/edit-session/initialize",
            json={
                "raw_text": "第一句。第二句。",
                "voice_id": "demo",
            },
        )
        assert initialize.status_code == 202
        _wait_until(lambda: client.get("/v1/edit-session/snapshot").json()["session_status"] == "ready")

        initial_snapshot = client.get("/v1/edit-session/snapshot").json()
        edge_id = initial_snapshot["edges"][0]["edge_id"]

        patch_edge = client.patch(
            f"/v1/edit-session/edges/{edge_id}",
            json={"pause_duration_seconds": 0.8},
        )
        assert patch_edge.status_code == 202
        _wait_until(lambda: client.get("/v1/edit-session/snapshot").json()["document_version"] == 2)

        append = client.post(
            "/v1/edit-session/append",
            json={
                "raw_text": "第三句。",
                "text_language": "auto",
            },
        )
        assert append.status_code == 202
        _wait_until(lambda: client.get("/v1/edit-session/snapshot").json()["document_version"] == 3)

        snapshot = client.get("/v1/edit-session/snapshot").json()
        assert snapshot["timeline_manifest_id"] is not None
        assert snapshot["composition_manifest_id"] is None
        assert client.get("/v1/edit-session/composition").status_code == 404

        timeline = client.get("/v1/edit-session/timeline")
        assert timeline.status_code == 200
        assert timeline.json()["timeline_version"] == 3

        segment_export = client.post(
            "/v1/edit-session/exports/segments",
            json={
                "document_version": snapshot["document_version"],
                "target_dir": "full-smoke-segments",
                "overwrite_policy": "fail",
            },
        )
        assert segment_export.status_code == 202
        segment_export_job_id = segment_export.json()["job"]["export_job_id"]
        _wait_until(
            lambda: client.get(f"/v1/edit-session/exports/{segment_export_job_id}").json()["status"] == "completed"
        )

        composition_export = client.post(
            "/v1/edit-session/exports/composition",
            json={
                "document_version": snapshot["document_version"],
                "target_dir": "full-smoke-composition",
                "overwrite_policy": "fail",
            },
        )
        assert composition_export.status_code == 202
        composition_export_job_id = composition_export.json()["job"]["export_job_id"]
        _wait_until(
            lambda: client.get(f"/v1/edit-session/exports/{composition_export_job_id}").json()["status"] == "completed"
        )

        playback_map = client.get("/v1/edit-session/playback-map")
        assert playback_map.status_code == 200
        assert playback_map.json()["document_version"] == 3
        assert playback_map.json()["composition_manifest_id"] is not None

        composition = client.get("/v1/edit-session/composition")
        assert composition.status_code == 200

        refreshed_snapshot = client.get("/v1/edit-session/snapshot").json()
        assert refreshed_snapshot["composition_manifest_id"] is not None

    assert (segment_export_dir / "0001.wav").exists()
    assert (segment_export_dir / "0002.wav").exists()
    assert (segment_export_dir / "0003.wav").exists()
    assert (composition_export_dir / "composition.wav").exists()
