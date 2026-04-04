import time
from pathlib import Path

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


def test_b4_missing_read_and_mutation_routes_are_available(test_app_settings):
    app = create_app(settings=test_app_settings)
    app.state.editable_inference_gateway = EditableInferenceGateway(FakeEditableInferenceBackend())

    with TestClient(app) as client:
        initialize = client.post(
            "/v1/edit-session/initialize",
            json={"raw_text": "第一句。第二句。第三句。", "voice_id": "demo"},
        )
        assert initialize.status_code == 202
        _wait_until(lambda: client.get("/v1/edit-session/snapshot").json()["session_status"] == "ready")

        snapshot = client.get("/v1/edit-session/snapshot").json()
        assert client.get("/v1/edit-session/groups").status_code == 200
        assert client.get("/v1/edit-session/render-profiles").status_code == 200
        assert client.get("/v1/edit-session/voice-bindings").status_code == 200

        split_response = client.post(
            "/v1/edit-session/segments/split",
            json={
                "segment_id": snapshot["segments"][0]["segment_id"],
                "left_text": "第一句上半句。",
                "right_text": "第一句下半句。",
            },
        )
        assert split_response.status_code == 202
        _wait_until(lambda: client.get("/v1/edit-session/snapshot").json()["document_version"] == 2)

        snapshot = client.get("/v1/edit-session/snapshot").json()
        merge_response = client.post(
            "/v1/edit-session/segments/merge",
            json={
                "left_segment_id": snapshot["segments"][0]["segment_id"],
                "right_segment_id": snapshot["segments"][1]["segment_id"],
            },
        )
        assert merge_response.status_code == 202
        _wait_until(lambda: client.get("/v1/edit-session/snapshot").json()["document_version"] == 3)

        snapshot = client.get("/v1/edit-session/snapshot").json()
        move_response = client.post(
            "/v1/edit-session/segments/move-range",
            json={
                "segment_ids": [snapshot["segments"][0]["segment_id"]],
                "after_segment_id": snapshot["segments"][-1]["segment_id"],
            },
        )
        assert move_response.status_code == 202
        _wait_until(lambda: client.get("/v1/edit-session/snapshot").json()["document_version"] == 4)

        snapshot = client.get("/v1/edit-session/snapshot").json()
        profile_batch_response = client.patch(
            "/v1/edit-session/segments/render-profile-batch",
            json={
                "segment_ids": [snapshot["segments"][0]["segment_id"], snapshot["segments"][1]["segment_id"]],
                "patch": {"speed": 0.9},
            },
        )
        assert profile_batch_response.status_code == 202
        _wait_until(lambda: client.get("/v1/edit-session/snapshot").json()["document_version"] == 5)

        snapshot = client.get("/v1/edit-session/snapshot").json()
        binding_batch_response = client.patch(
            "/v1/edit-session/segments/voice-binding-batch",
            json={
                "segment_ids": [snapshot["segments"][0]["segment_id"]],
                "patch": {"voice_id": "voice-b", "model_key": "model-b"},
            },
        )
        assert binding_batch_response.status_code == 202
        _wait_until(lambda: client.get("/v1/edit-session/snapshot").json()["document_version"] == 6)

        latest_snapshot = client.get("/v1/edit-session/snapshot").json()
        assert latest_snapshot["timeline_manifest_id"] is not None


def test_composition_route_requires_completed_composition_export(test_app_settings):
    app = create_app(settings=test_app_settings)
    app.state.editable_inference_gateway = EditableInferenceGateway(FakeEditableInferenceBackend())

    with TestClient(app) as client:
        initialize = client.post(
            "/v1/edit-session/initialize",
            json={"raw_text": "第一句。第二句。", "voice_id": "demo"},
        )
        assert initialize.status_code == 202
        _wait_until(lambda: client.get("/v1/edit-session/snapshot").json()["session_status"] == "ready")

        composition_before_export = client.get("/v1/edit-session/composition")
        assert composition_before_export.status_code == 404

        snapshot = client.get("/v1/edit-session/snapshot").json()
        export_dir = test_app_settings.edit_session_exports_dir / "composition-ready"
        create_export = client.post(
            "/v1/edit-session/exports/composition",
            json={
                "document_version": snapshot["document_version"],
                "target_dir": "composition-ready",
                "overwrite_policy": "fail",
            },
        )
        assert create_export.status_code == 202
        export_job_id = create_export.json()["job"]["export_job_id"]
        _wait_until(lambda: client.get(f"/v1/edit-session/exports/{export_job_id}").json()["status"] == "completed")

        composition_after_export = client.get("/v1/edit-session/composition")
        assert composition_after_export.status_code == 200
        assert composition_after_export.json()["audio_delivery"]["audio_url"].endswith("/audio")
        assert (export_dir / "composition.wav").exists()


def test_export_target_dir_must_stay_inside_controlled_export_root(test_app_settings):
    app = create_app(settings=test_app_settings)
    app.state.editable_inference_gateway = EditableInferenceGateway(FakeEditableInferenceBackend())
    outside_dir = Path(test_app_settings.project_root).parent / "outside-export"

    with TestClient(app) as client:
        initialize = client.post(
            "/v1/edit-session/initialize",
            json={"raw_text": "第一句。第二句。", "voice_id": "demo"},
        )
        assert initialize.status_code == 202
        _wait_until(lambda: client.get("/v1/edit-session/snapshot").json()["session_status"] == "ready")

        snapshot = client.get("/v1/edit-session/snapshot").json()
        invalid_absolute = client.post(
            "/v1/edit-session/exports/segments",
            json={
                "document_version": snapshot["document_version"],
                "target_dir": str(outside_dir),
                "overwrite_policy": "fail",
            },
        )
        assert invalid_absolute.status_code == 400

        invalid_escape = client.post(
            "/v1/edit-session/exports/segments",
            json={
                "document_version": snapshot["document_version"],
                "target_dir": "..\\escape",
                "overwrite_policy": "fail",
            },
        )
        assert invalid_escape.status_code == 400
