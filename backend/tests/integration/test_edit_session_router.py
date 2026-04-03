import time
from pathlib import Path
import threading

import numpy as np
import torch
from fastapi.testclient import TestClient

from backend.app.inference.editable_gateway import EditableInferenceGateway
from backend.app.inference.editable_types import (
    BoundaryAssetPayload,
    ReferenceContext,
    SegmentRenderAssetPayload,
    build_boundary_asset_id,
)
from backend.app.main import create_app
from backend.app.schemas.edit_session import InitializeEditSessionRequest


class FakeEditableInferenceBackend:
    def __init__(self, gate: threading.Event | None = None, *, wait_timeout: float | None = 2.0) -> None:
        self.gate = gate
        self.wait_timeout = wait_timeout
        self.segment_calls: list[tuple[str, str]] = []
        self.boundary_calls: list[tuple[str, str, str]] = []

    def build_reference_context(self, request: InitializeEditSessionRequest) -> ReferenceContext:
        return ReferenceContext(
            reference_context_id="ctx-1",
            voice_id=request.voice_id,
            model_id=request.model_id,
            reference_audio_path=request.reference_audio_path or "fake.wav",
            reference_text=request.reference_text or "参考文本。",
            reference_language=request.reference_language or "zh",
            reference_semantic_tokens=np.asarray([1, 2, 3], dtype=np.int64),
            reference_spectrogram=torch.ones((1, 3, 3), dtype=torch.float32),
            reference_speaker_embedding=torch.ones((1, 4), dtype=torch.float32),
            inference_config_fingerprint="fingerprint",
            inference_config={"margin_frame_count": 0},
        )

    def render_segment_base(self, segment, context) -> SegmentRenderAssetPayload:
        del context
        if self.gate is not None:
            if self.wait_timeout is None:
                self.gate.wait()
            else:
                self.gate.wait(timeout=self.wait_timeout)
        self.segment_calls.append((segment.segment_id, segment.raw_text))
        audio = np.asarray([segment.order_key / 10], dtype=np.float32)
        return SegmentRenderAssetPayload(
            render_asset_id=f"render-{segment.segment_id}",
            segment_id=segment.segment_id,
            render_version=1,
            semantic_tokens=[1, 2],
            phone_ids=[11, 12],
            decoder_frame_count=1,
            audio_sample_count=1,
            left_margin_sample_count=0,
            core_sample_count=1,
            right_margin_sample_count=0,
            left_margin_audio=np.zeros(0, dtype=np.float32),
            core_audio=audio,
            right_margin_audio=np.zeros(0, dtype=np.float32),
            trace=None,
        )

    def render_boundary_asset(self, left_asset, right_asset, edge, context) -> BoundaryAssetPayload:
        del context
        self.boundary_calls.append((edge.left_segment_id, edge.right_segment_id, edge.boundary_strategy))
        return BoundaryAssetPayload(
            boundary_asset_id=build_boundary_asset_id(
                left_segment_id=edge.left_segment_id,
                left_render_version=left_asset.render_version,
                right_segment_id=edge.right_segment_id,
                right_render_version=right_asset.render_version,
                edge_version=edge.edge_version,
                boundary_strategy=edge.boundary_strategy,
            ),
            left_segment_id=left_asset.segment_id,
            left_render_version=1,
            right_segment_id=right_asset.segment_id,
            right_render_version=1,
            edge_version=1,
            boundary_strategy="latent_overlap_then_equal_power_crossfade",
            boundary_sample_count=1,
            boundary_audio=np.asarray([0.9], dtype=np.float32),
            trace=None,
        )


def _wait_until(predicate, *, timeout: float = 3.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return
        time.sleep(0.05)
    raise AssertionError("Condition not met before timeout.")


def test_edit_session_initialize_snapshot_delete_and_conflict(test_app_settings):
    gate = threading.Event()
    app = create_app(settings=test_app_settings)
    app.state.editable_inference_gateway = EditableInferenceGateway(FakeEditableInferenceBackend(gate=gate))
    with TestClient(app) as client:
        empty_snapshot = client.get("/v1/edit-session/snapshot")
        assert empty_snapshot.status_code == 200
        assert empty_snapshot.json()["session_status"] == "empty"

        initialize = client.post(
            "/v1/edit-session/initialize",
            json={
                "raw_text": "第一句。第二句。",
                "voice_id": "demo",
            },
        )
        assert initialize.status_code == 202
        job_id = initialize.json()["job"]["job_id"]

        initializing_snapshot = client.get("/v1/edit-session/snapshot")
        assert initializing_snapshot.status_code == 200
        assert initializing_snapshot.json()["session_status"] == "initializing"

        conflict = client.post(
            "/v1/edit-session/initialize",
            json={
                "raw_text": "第三句。",
                "voice_id": "demo",
            },
        )
        assert conflict.status_code == 409

        gate.set()
        _wait_until(lambda: client.get("/v1/edit-session/snapshot").json()["session_status"] == "ready")

        baseline = client.get("/v1/edit-session/baseline")
        assert baseline.status_code == 200
        assert baseline.json()["baseline_snapshot"]["document_id"] is not None

        delete_response = client.delete("/v1/edit-session")
        assert delete_response.status_code == 204
        after_delete = client.get("/v1/edit-session/snapshot")
        assert after_delete.status_code == 200
        assert after_delete.json()["session_status"] == "empty"

        assert job_id


def test_edit_session_render_job_events_and_cancel(test_app_settings):
    gate = threading.Event()
    app = create_app(settings=test_app_settings)
    app.state.editable_inference_gateway = EditableInferenceGateway(FakeEditableInferenceBackend(gate=gate))
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

        job_response = client.get(f"/v1/edit-session/render-jobs/{job_id}")
        assert job_response.status_code == 200
        assert job_response.json()["job_id"] == job_id

        cancel_response = client.post(f"/v1/edit-session/render-jobs/{job_id}/cancel")
        assert cancel_response.status_code == 200
        assert cancel_response.json()["cancel_requested"] is True

        with client.stream("GET", f"/v1/edit-session/render-jobs/{job_id}/events") as response:
            assert response.status_code == 200
            lines = response.iter_lines()
            first_event_line = next(lines)
            first_data_line = next(lines)
            assert first_event_line == "event: progress"
            assert f'"job_id": "{job_id}"' in first_data_line

        gate.set()


def test_edit_session_event_stream_waits_for_cancelled_terminal_state(test_app_settings):
    gate = threading.Event()
    app = create_app(settings=test_app_settings)
    app.state.editable_inference_gateway = EditableInferenceGateway(
        FakeEditableInferenceBackend(gate=gate, wait_timeout=None)
    )
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

        cancel_response = client.post(f"/v1/edit-session/render-jobs/{job_id}/cancel")
        assert cancel_response.status_code == 200
        assert cancel_response.json()["cancel_requested"] is True

        release_thread = threading.Thread(target=lambda: (time.sleep(0.1), gate.set()), daemon=True)
        release_thread.start()

        statuses: list[str] = []
        with client.stream("GET", f"/v1/edit-session/render-jobs/{job_id}/events") as response:
            assert response.status_code == 200
            for line in response.iter_lines():
                if not line.startswith("data: "):
                    continue
                payload = line.removeprefix("data: ")
                if '"status": "cancelling"' in payload:
                    statuses.append("cancelling")
                if '"status": "cancelled"' in payload:
                    statuses.append("cancelled")
                    break

        assert statuses in (["cancelled"], ["cancelling", "cancelled"])


def test_edit_session_segment_crud_and_read_models(test_app_settings):
    backend = FakeEditableInferenceBackend()
    app = create_app(settings=test_app_settings)
    app.state.editable_inference_gateway = EditableInferenceGateway(backend)
    with TestClient(app) as client:
        initialize = client.post(
            "/v1/edit-session/initialize",
            json={
                "raw_text": "第一句。第三句。",
                "voice_id": "demo",
            },
        )
        assert initialize.status_code == 202
        _wait_until(lambda: client.get("/v1/edit-session/snapshot").json()["session_status"] == "ready")

        initial_snapshot = client.get("/v1/edit-session/snapshot").json()
        first_segment_id = initial_snapshot["segments"][0]["segment_id"]
        assert len(backend.segment_calls) == 2
        assert len(backend.boundary_calls) == 1

        list_segments = client.get("/v1/edit-session/segments")
        assert list_segments.status_code == 200
        assert [item["raw_text"] for item in list_segments.json()["items"]] == ["第一句。", "第三句。"]

        insert_response = client.post(
            "/v1/edit-session/segments",
            json={
                "after_segment_id": first_segment_id,
                "raw_text": "第二句。",
                "text_language": "auto",
                "inference_override": {},
            },
        )
        assert insert_response.status_code == 202
        _wait_until(lambda: client.get("/v1/edit-session/snapshot").json()["document_version"] == 2)

        inserted_snapshot = client.get("/v1/edit-session/snapshot").json()
        assert [item["raw_text"] for item in inserted_snapshot["segments"]] == ["第一句。", "第二句。", "第三句。"]
        inserted_segment_id = inserted_snapshot["segments"][1]["segment_id"]
        assert len(backend.segment_calls) == 3
        assert len(backend.boundary_calls) == 3

        delete_response = client.delete(f"/v1/edit-session/segments/{inserted_segment_id}")
        assert delete_response.status_code == 202
        _wait_until(lambda: client.get("/v1/edit-session/snapshot").json()["document_version"] == 3)

        deleted_snapshot = client.get("/v1/edit-session/snapshot").json()
        assert [item["raw_text"] for item in deleted_snapshot["segments"]] == ["第一句。", "第三句。"]
        assert len(backend.segment_calls) == 3
        assert len(backend.boundary_calls) == 4

        composition = client.get("/v1/edit-session/composition")
        assert composition.status_code == 200
        assert composition.json()["document_version"] == 3
        assert composition.json()["audio_delivery"]["audio_url"].endswith("/audio")

        playback_map = client.get("/v1/edit-session/playback-map")
        assert playback_map.status_code == 200
        assert playback_map.json()["document_version"] == 3
        assert len(playback_map.json()["entries"]) == 2


def test_edit_session_segment_edge_preview_and_restore_baseline(test_app_settings):
    backend = FakeEditableInferenceBackend()
    app = create_app(settings=test_app_settings)
    app.state.editable_inference_gateway = EditableInferenceGateway(backend)
    with TestClient(app) as client:
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
        segment_id = initial_snapshot["segments"][0]["segment_id"]
        edge_id = initial_snapshot["edges"][0]["edge_id"]
        assert len(backend.segment_calls) == 2
        assert len(backend.boundary_calls) == 1

        patch_segment = client.patch(
            f"/v1/edit-session/segments/{segment_id}",
            json={"raw_text": "第一句已修改。"},
        )
        assert patch_segment.status_code == 202
        _wait_until(lambda: client.get("/v1/edit-session/snapshot").json()["document_version"] == 2)

        updated_snapshot = client.get("/v1/edit-session/snapshot").json()
        assert updated_snapshot["segments"][0]["raw_text"] == "第一句已修改。"
        assert len(backend.segment_calls) == 3
        assert len(backend.boundary_calls) == 2

        patch_edge = client.patch(
            f"/v1/edit-session/edges/{edge_id}",
            json={"pause_duration_seconds": 0.8},
        )
        assert patch_edge.status_code == 202
        _wait_until(lambda: client.get("/v1/edit-session/snapshot").json()["document_version"] == 3)

        paused_snapshot = client.get("/v1/edit-session/snapshot").json()
        assert paused_snapshot["edges"][0]["pause_duration_seconds"] == 0.8
        assert len(backend.segment_calls) == 3
        assert len(backend.boundary_calls) == 2

        patch_strategy = client.patch(
            f"/v1/edit-session/edges/{edge_id}",
            json={"boundary_strategy": "crossfade_only"},
        )
        assert patch_strategy.status_code == 202
        _wait_until(lambda: client.get("/v1/edit-session/snapshot").json()["document_version"] == 4)

        strategy_snapshot = client.get("/v1/edit-session/snapshot").json()
        assert strategy_snapshot["edges"][0]["boundary_strategy"] == "crossfade_only"
        assert len(backend.segment_calls) == 3
        assert len(backend.boundary_calls) == 3

        list_edges = client.get("/v1/edit-session/edges")
        assert list_edges.status_code == 200
        assert list_edges.json()["items"][0]["pause_duration_seconds"] == 0.8

        preview = client.get("/v1/edit-session/preview", params={"segment_id": segment_id})
        assert preview.status_code == 200
        assert preview.json()["preview_kind"] == "segment"
        assert preview.json()["audio_delivery"]["audio_url"].endswith("/audio")

        restore = client.post("/v1/edit-session/restore-baseline")
        assert restore.status_code == 202
        _wait_until(lambda: client.get("/v1/edit-session/snapshot").json()["document_version"] == 5)

        restored_snapshot = client.get("/v1/edit-session/snapshot").json()
        assert restored_snapshot["segments"][0]["raw_text"] == "第一句。"
        assert restored_snapshot["edges"][0]["pause_duration_seconds"] == 0.3


def test_edit_session_edges_support_cursor_pagination(test_app_settings):
    backend = FakeEditableInferenceBackend()
    app = create_app(settings=test_app_settings)
    app.state.editable_inference_gateway = EditableInferenceGateway(backend)
    with TestClient(app) as client:
        initialize = client.post(
            "/v1/edit-session/initialize",
            json={
                "raw_text": "第一句。第二句。第三句。",
                "voice_id": "demo",
            },
        )
        assert initialize.status_code == 202
        _wait_until(lambda: client.get("/v1/edit-session/snapshot").json()["session_status"] == "ready")

        first_page = client.get("/v1/edit-session/edges", params={"limit": 1})
        assert first_page.status_code == 200
        assert len(first_page.json()["items"]) == 1
        assert first_page.json()["next_cursor"] is not None

        second_page = client.get("/v1/edit-session/edges", params={"limit": 1, "cursor": first_page.json()["next_cursor"]})
        assert second_page.status_code == 200
        assert len(second_page.json()["items"]) == 1
        assert second_page.json()["items"][0]["edge_id"] != first_page.json()["items"][0]["edge_id"]
