import threading
import time
from pathlib import Path

from fastapi.testclient import TestClient

from backend.app.inference.block_adapter_types import BlockRenderResult, JoinReport
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


def test_unified_export_route_can_emit_composition_and_srt(test_app_settings):
    gate = threading.Event()
    app = create_app(settings=test_app_settings)
    app.state.editable_inference_gateway = EditableInferenceGateway(FakeEditableInferenceBackend(gate=gate))
    export_root = test_app_settings.edit_session_exports_dir / "unified_composition_exports"

    with TestClient(app) as client:
        gate.set()
        snapshot = _initialize_ready_document(client)

        create_export = client.post(
            "/v1/edit-session/exports",
            json={
                "document_version": snapshot["document_version"],
                "target_dir": str(export_root),
                "audio": {"kind": "composition", "overwrite_policy": "fail"},
                "subtitle": {
                    "enabled": True,
                    "format": "srt",
                    "offset_seconds": 0.2,
                    "strip_trailing_punctuation": True,
                },
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
        subtitle_files = [Path(path) for path in payload["output_manifest"]["subtitle_files"]]
        assert composition_file.parent == export_root
        assert composition_file.name.startswith("neo-tts-export-")
        assert composition_file.suffix == ".wav"
        assert subtitle_files == [export_root / f"{composition_file.stem}.srt"]
        assert payload["output_manifest"]["audio_files"] == [str(composition_file)]
        assert payload["output_manifest"]["subtitle_manifest"] == {
            "format": "srt",
            "offset_seconds": 0.2,
            "strip_trailing_punctuation": True,
        }

    wav_files = list(export_root.glob("neo-tts-export-*.wav"))
    srt_files = list(export_root.glob("neo-tts-export-*.srt"))
    assert len(wav_files) == 1
    assert len(srt_files) == 1
    assert srt_files[0].stem == wav_files[0].stem


def test_unified_export_route_can_emit_segments_and_shared_srt(test_app_settings):
    gate = threading.Event()
    app = create_app(settings=test_app_settings)
    app.state.editable_inference_gateway = EditableInferenceGateway(FakeEditableInferenceBackend(gate=gate))
    export_root = test_app_settings.edit_session_exports_dir / "unified_segment_exports"

    with TestClient(app) as client:
        gate.set()
        snapshot = _initialize_ready_document(client)

        create_export = client.post(
            "/v1/edit-session/exports",
            json={
                "document_version": snapshot["document_version"],
                "target_dir": str(export_root),
                "audio": {"kind": "segments", "overwrite_policy": "fail"},
                "subtitle": {
                    "enabled": True,
                    "format": "srt",
                    "offset_seconds": -0.1,
                    "strip_trailing_punctuation": True,
                },
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
        assert payload["timeline_manifest_id"] == snapshot["timeline_manifest_id"]
        final_dir = Path(payload["output_manifest"]["target_dir"])
        segment_files = [Path(path) for path in payload["output_manifest"]["segment_files"]]
        subtitle_files = [Path(path) for path in payload["output_manifest"]["subtitle_files"]]
        assert final_dir.parent == export_root
        assert final_dir.name.startswith("neo-tts-export-")
        assert [path.name for path in segment_files] == ["segments-1.wav", "segments-2.wav"]
        assert subtitle_files == [final_dir / f"{final_dir.name}.srt"]
        assert payload["output_manifest"]["subtitle_manifest"] == {
            "format": "srt",
            "offset_seconds": -0.1,
            "strip_trailing_punctuation": True,
        }

    export_dirs = list(export_root.glob("neo-tts-export-*"))
    assert len(export_dirs) == 1
    assert (export_dirs[0] / "segments-1.wav").exists()
    assert (export_dirs[0] / "segments-2.wav").exists()
    assert (export_dirs[0] / f"{export_dirs[0].name}.srt").exists()


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
        assert payload["timeline_manifest_id"] == snapshot["timeline_manifest_id"]
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


def test_unified_export_route_can_emit_blocks_and_shared_srt(test_app_settings):
    gate = threading.Event()
    app = create_app(settings=test_app_settings)
    app.state.editable_inference_gateway = EditableInferenceGateway(FakeEditableInferenceBackend(gate=gate))
    export_root = test_app_settings.edit_session_exports_dir / "blocks_exports"

    with TestClient(app) as client:
        gate.set()
        snapshot = _initialize_ready_document(client)

        create_export = client.post(
            "/v1/edit-session/exports",
            json={
                "document_version": snapshot["document_version"],
                "target_dir": str(export_root),
                "audio": {"kind": "blocks", "overwrite_policy": "fail"},
                "subtitle": {
                    "enabled": True,
                    "format": "srt",
                    "offset_seconds": 0.0,
                    "strip_trailing_punctuation": False,
                },
            },
        )
        assert create_export.status_code == 202
        export_job_id = create_export.json()["job"]["export_job_id"]

        _wait_until(lambda: client.get(f"/v1/edit-session/exports/{export_job_id}").json()["status"] == "completed")

        export_job = client.get(f"/v1/edit-session/exports/{export_job_id}")
        assert export_job.status_code == 200
        payload = export_job.json()
        assert payload["export_kind"] == "blocks"
        assert payload["status"] == "completed"
        final_dir = Path(payload["output_manifest"]["target_dir"])
        block_files = [Path(path) for path in payload["output_manifest"]["block_files"]]
        subtitle_files = [Path(path) for path in payload["output_manifest"]["subtitle_files"]]
        assert final_dir.parent == export_root
        assert final_dir.name.startswith("neo-tts-export-")
        assert [path.name for path in block_files] == ["blocks-1.wav"]
        assert subtitle_files == [final_dir / f"{final_dir.name}.srt"]
        assert payload["output_manifest"]["block_manifest_entries"] == [
            {
                "block_id": payload["output_manifest"]["block_manifest_entries"][0]["block_id"],
                "block_asset_id": payload["output_manifest"]["block_manifest_entries"][0]["block_asset_id"],
                "order_index": 1,
                "sample_span": payload["output_manifest"]["block_manifest_entries"][0]["sample_span"],
                "segment_ids": [segment["segment_id"] for segment in snapshot["segments"]],
                "segment_alignment_mode": "exact",
            }
        ]

    export_dirs = list(export_root.glob("neo-tts-export-*"))
    assert len(export_dirs) == 1
    assert (export_dirs[0] / "blocks-1.wav").exists()
    assert (export_dirs[0] / f"{export_dirs[0].name}.srt").exists()


def test_segment_export_fails_when_timeline_only_has_block_level_alignment(test_app_settings):
    class _BlockOnlyAdapter:
        def render_block(self, request):
            return BlockRenderResult(
                block_id=request.block.block_id,
                segment_ids=[segment.segment_id for segment in request.block.segments],
                sample_rate=32000,
                audio=[0.1, 0.2, 0.3, 0.4],
                audio_sample_count=4,
                segment_alignment_mode="block_only",
                segment_outputs=[],
                segment_spans=[],
                join_report=JoinReport(
                    requested_policy=request.join_policy,
                    applied_mode=request.join_policy,
                    enhancement_applied=False,
                    implementation="block-only-test",
                ),
            )

    gate = threading.Event()
    app = create_app(settings=test_app_settings)
    app.state.editable_inference_gateway = EditableInferenceGateway(FakeEditableInferenceBackend(gate=gate))
    app.state.block_adapter_selector = lambda adapter_id, **kwargs: _BlockOnlyAdapter()
    export_root = test_app_settings.edit_session_exports_dir / "block_only_segment_exports"

    with TestClient(app) as client:
        gate.set()
        snapshot = _initialize_ready_document(client)

        create_export = client.post(
            "/v1/edit-session/exports",
            json={
                "document_version": snapshot["document_version"],
                "target_dir": str(export_root),
                "audio": {"kind": "segments", "overwrite_policy": "fail"},
            },
        )
        assert create_export.status_code == 202
        export_job_id = create_export.json()["job"]["export_job_id"]

        _wait_until(lambda: client.get(f"/v1/edit-session/exports/{export_job_id}").json()["status"] == "failed")

        export_job = client.get(f"/v1/edit-session/exports/{export_job_id}")
        assert export_job.status_code == 200
        payload = export_job.json()
        assert payload["export_kind"] == "segments"
        assert payload["status"] == "failed"
        assert "exact segment alignment" in payload["message"]
