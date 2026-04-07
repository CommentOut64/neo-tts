import threading
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


def _initialize_ready_document(client: TestClient) -> dict:
    initialize = client.post(
        "/v1/edit-session/initialize",
        json={
            "raw_text": "第一句。第二句。",
            "voice_id": "demo",
        },
    )
    assert initialize.status_code == 202
    _wait_until(lambda: client.get("/v1/edit-session/snapshot").json()["session_status"] == "ready")
    return client.get("/v1/edit-session/snapshot").json()


def test_segment_export_route_creates_numbered_wavs_without_composition_file(test_app_settings):
    gate = threading.Event()
    app = create_app(settings=test_app_settings)
    app.state.editable_inference_gateway = EditableInferenceGateway(FakeEditableInferenceBackend(gate=gate))
    export_root = test_app_settings.edit_session_exports_dir / "segment_exports"

    with TestClient(app) as client:
        gate.set()
        snapshot = _initialize_ready_document(client)

        create_export = client.post(
            "/v1/edit-session/exports/segments",
            json={
                "document_version": snapshot["document_version"],
                "target_dir": str(export_root),
                "overwrite_policy": "fail",
            },
        )
        assert create_export.status_code == 202
        export_job_id = create_export.json()["job"]["export_job_id"]

        _wait_until(lambda: client.get(f"/v1/edit-session/exports/{export_job_id}").json()["status"] == "completed")

        export_job = client.get(f"/v1/edit-session/exports/{export_job_id}")
        assert export_job.status_code == 200
        payload = export_job.json()
        assert payload["export_kind"] == "segments"
        assert payload["status"] == "completed"
        final_dir = Path(payload["output_manifest"]["target_dir"])
        assert final_dir.parent == export_root
        assert final_dir.name.startswith("neo-tts-export-")
        manifest_file = Path(payload["output_manifest"]["manifest_file"])
        assert manifest_file.name == "manifest.json"
        assert "formal" in manifest_file.parts
        assert [Path(path).name for path in payload["output_manifest"]["segment_files"]] == [
            "segments-1.wav",
            "segments-2.wav",
        ]

        with client.stream("GET", f"/v1/edit-session/exports/{export_job_id}/events") as response:
            assert response.status_code == 200
            raw_stream = "\n".join(response.iter_lines())
        assert "event: export_progress" in raw_stream
        assert "event: export_completed" in raw_stream

    export_dirs = list(export_root.glob("neo-tts-export-*"))
    assert len(export_dirs) == 1
    assert (export_dirs[0] / "segments-1.wav").exists()
    assert (export_dirs[0] / "segments-2.wav").exists()
    assert not (export_dirs[0] / "manifest.json").exists()
    assert not (export_dirs[0] / "composition.wav").exists()


def test_composition_export_route_creates_only_composition_artifact(test_app_settings):
    gate = threading.Event()
    app = create_app(settings=test_app_settings)
    app.state.editable_inference_gateway = EditableInferenceGateway(FakeEditableInferenceBackend(gate=gate))
    export_root = test_app_settings.edit_session_exports_dir / "composition_exports"

    with TestClient(app) as client:
        gate.set()
        snapshot = _initialize_ready_document(client)

        create_export = client.post(
            "/v1/edit-session/exports/composition",
            json={
                "document_version": snapshot["document_version"],
                "target_dir": str(export_root),
                "overwrite_policy": "fail",
            },
        )
        assert create_export.status_code == 202
        export_job_id = create_export.json()["job"]["export_job_id"]

        _wait_until(lambda: client.get(f"/v1/edit-session/exports/{export_job_id}").json()["status"] == "completed")

        export_job = client.get(f"/v1/edit-session/exports/{export_job_id}")
        assert export_job.status_code == 200
        payload = export_job.json()
        assert payload["export_kind"] == "composition"
        assert payload["status"] == "completed"
        assert payload["output_manifest"]["target_dir"] == str(export_root)
        composition_file = Path(payload["output_manifest"]["composition_file"])
        manifest_file = Path(payload["output_manifest"]["manifest_file"])
        assert composition_file.parent == export_root
        assert composition_file.name.startswith("neo-tts-export-")
        assert composition_file.suffix == ".wav"
        assert manifest_file.name == "manifest.json"
        assert "formal" in manifest_file.parts

    wav_files = list(export_root.glob("neo-tts-export-*.wav"))
    assert len(wav_files) == 1
    assert list(export_root.glob("*.manifest.json")) == []
    assert not (export_root / "0001.wav").exists()
