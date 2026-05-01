from dataclasses import replace
from datetime import datetime, timedelta, timezone
import importlib
import json
import os
from pathlib import Path
import queue
import time
import threading
from types import SimpleNamespace
from uuid import uuid4

import numpy as np
import torch
from fastapi.testclient import TestClient

from backend.app.inference.editable_gateway import EditableInferenceGateway
from backend.app.inference.block_adapter_types import BlockRenderResult, JoinReport, SegmentOutput, SegmentSpan
from backend.app.inference.editable_types import (
    BoundaryAssetPayload,
    ReferenceContext,
    ResolvedRenderContext,
    SegmentRenderAssetPayload,
    build_boundary_asset_id,
)
from backend.app.main import create_app
from backend.app.repositories.edit_session_repository import EditSessionRepository
from backend.app.schemas.edit_session import (
    ActiveDocumentState,
    DocumentSnapshot,
    EditableEdge,
    EditableSegment,
    InitializeEditSessionRequest,
    RenderJobRecord,
)
from backend.app.services.edit_asset_store import EditAssetStore
from backend.app.services import render_job_service as render_job_service_module
from backend.app.text.segment_standardizer import build_segment_display_text


class FakeEditableInferenceBackend:
    def __init__(self, gate: threading.Event | None = None, *, wait_timeout: float | None = 2.0) -> None:
        self.gate = gate
        self.wait_timeout = wait_timeout
        self.segment_calls: list[tuple[str, str]] = []
        self.boundary_calls: list[tuple[str, str, str]] = []

    def build_reference_context(
        self,
        resolved_context: ResolvedRenderContext,
        *,
        progress_callback=None,
    ) -> ReferenceContext:
        del progress_callback
        return ReferenceContext(
            reference_context_id="ctx-1",
            voice_id=resolved_context.voice_id,
            model_id=resolved_context.model_key,
            reference_audio_path=resolved_context.reference_audio_path or "fake.wav",
            reference_text=resolved_context.reference_text or "参考文本。",
            reference_language=resolved_context.reference_language or "zh",
            reference_semantic_tokens=np.asarray([1, 2, 3], dtype=np.int64),
            reference_spectrogram=torch.ones((1, 3, 3), dtype=torch.float32),
            reference_speaker_embedding=torch.ones((1, 4), dtype=torch.float32),
            inference_config_fingerprint="fingerprint",
            inference_config={"margin_frame_count": 0, "speed": resolved_context.speed},
        )

    def render_segment_base(self, segment, context, *, progress_callback=None) -> SegmentRenderAssetPayload:
        del progress_callback
        if self.gate is not None:
            if self.wait_timeout is None:
                self.gate.wait()
            else:
                self.gate.wait(timeout=self.wait_timeout)
        self.segment_calls.append((segment.segment_id, segment.display_text))
        sample_count = 2 if context.inference_config.get("speed", 1.0) < 1.0 else 1
        audio = np.asarray([segment.order_key / 10] * sample_count, dtype=np.float32)
        return SegmentRenderAssetPayload(
            render_asset_id=f"render-{segment.segment_id}",
            segment_id=segment.segment_id,
            render_version=1,
            semantic_tokens=[1, 2],
            phone_ids=[11, 12],
            decoder_frame_count=1,
            audio_sample_count=sample_count,
            left_margin_sample_count=0,
            core_sample_count=sample_count,
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


class FakeBlockAdapter:
    def __init__(self) -> None:
        self.requests = []

    def render_block(self, request):
        self.requests.append(request)
        audio: list[float] = []
        spans: list[SegmentSpan] = []
        outputs: list[SegmentOutput] = []
        cursor = 0
        for index, segment in enumerate(request.block.segments, start=1):
            audio.extend([index / 10.0, index / 10.0])
            span = SegmentSpan(
                segment_id=segment.segment_id,
                sample_start=cursor,
                sample_end=cursor + 2,
                precision="exact",
            )
            spans.append(span)
            outputs.append(
                SegmentOutput(
                    segment_id=segment.segment_id,
                    sample_span=span,
                    source="adapter_exact",
                )
            )
            cursor += 2
        return BlockRenderResult(
            block_id=request.block.block_id,
            segment_ids=[segment.segment_id for segment in request.block.segments],
            sample_rate=32000,
            audio=audio,
            audio_sample_count=len(audio),
            segment_alignment_mode="exact",
            segment_outputs=outputs,
            segment_spans=spans,
            join_report=JoinReport(
                requested_policy=request.join_policy,
                applied_mode=request.join_policy,
                enhancement_applied=False,
                implementation="fake-block-adapter",
            ),
            adapter_trace={"request_id": request.request_id},
        )


def _wait_until(predicate, *, timeout: float = 3.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return
        time.sleep(0.05)
    raise AssertionError("Condition not met before timeout.")


def _export_composition_for_current_snapshot(client: TestClient, *, target_dir: str | Path) -> dict:
    snapshot = client.get("/v1/edit-session/snapshot").json()
    response = client.post(
        "/v1/edit-session/exports/composition",
        json={
            "document_version": snapshot["document_version"],
            "target_dir": str(target_dir),
            "overwrite_policy": "fail",
        },
    )
    assert response.status_code == 202
    export_job_id = response.json()["job"]["export_job_id"]
    _wait_until(lambda: client.get(f"/v1/edit-session/exports/{export_job_id}").json()["status"] == "completed")
    composition = client.get("/v1/edit-session/composition")
    assert composition.status_code == 200
    return composition.json()


def _segment_display_text(segment_payload: dict) -> str:
    return build_segment_display_text(
        stem=segment_payload["stem"],
        text_language=segment_payload["text_language"],
        terminal_raw=segment_payload.get("terminal_raw", ""),
        terminal_closer_suffix=segment_payload.get("terminal_closer_suffix", ""),
        terminal_source=segment_payload.get("terminal_source", "synthetic"),
    )


def _seed_ready_session(app, *, segment_count: int) -> tuple[str, str]:
    repository = app.state.edit_session_repository
    document_id = "doc-seeded"
    segments: list[EditableSegment] = []
    for index in range(segment_count):
        segment_id = f"segment-{index + 1}"
        previous_segment_id = segments[-1].segment_id if segments else None
        segment = EditableSegment(
            segment_id=segment_id,
            document_id=document_id,
            order_key=index + 1,
            previous_segment_id=previous_segment_id,
            next_segment_id=f"segment-{index + 2}" if index + 1 < segment_count else None,
            stem=f"第{index + 1}句",
            text_language="zh",
            render_version=1,
            render_asset_id=f"render-{segment_id}",
        )
        segments.append(segment)

    edges = [
        EditableEdge(
            edge_id=f"edge-{left.segment_id}-{right.segment_id}",
            document_id=document_id,
            left_segment_id=left.segment_id,
            right_segment_id=right.segment_id,
        )
        for left, right in zip(segments, segments[1:])
    ]
    snapshot = DocumentSnapshot(
        snapshot_id=f"head-{uuid4().hex}",
        document_id=document_id,
        snapshot_kind="head",
        document_version=1,
        segment_ids=[segment.segment_id for segment in segments],
        edge_ids=[edge.edge_id for edge in edges],
        composition_manifest_id="composition-seeded",
        playback_map_version=1,
        segments=segments,
        edges=edges,
    )
    repository.save_snapshot(snapshot)
    repository.upsert_active_session(
        ActiveDocumentState(
            document_id=document_id,
            session_status="ready",
            baseline_snapshot_id=snapshot.snapshot_id,
            head_snapshot_id=snapshot.snapshot_id,
            active_job_id=None,
            editable_mode="segment",
            initialize_request=InitializeEditSessionRequest(
                raw_text="".join(segment.display_text for segment in segments),
                voice_id="demo",
            ),
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
    )
    return document_id, snapshot.snapshot_id


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
                "raw_text": "第一句。\n第二句。",
                "voice_id": "demo",
            },
        )
        assert initialize.status_code == 202
        job_id = initialize.json()["job"]["job_id"]

        initializing_snapshot = client.get("/v1/edit-session/snapshot")
        assert initializing_snapshot.status_code == 200
        assert initializing_snapshot.json()["session_status"] == "initializing"
        assert initializing_snapshot.json()["source_text"] == "第一句。\n第二句。"

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

        ready_snapshot = client.get("/v1/edit-session/snapshot")
        assert ready_snapshot.status_code == 200
        assert ready_snapshot.json()["source_text"] == "第一句。\n第二句。"

        delete_response = client.delete("/v1/edit-session")
        assert delete_response.status_code == 204
        after_delete = client.get("/v1/edit-session/snapshot")
        assert after_delete.status_code == 200
        assert after_delete.json()["session_status"] == "empty"
        assert after_delete.json()["source_text"] is None

        assert job_id


def test_initialize_route_single_segment_commits_render_asset_and_changed_block_metadata(test_app_settings):
    gate = threading.Event()
    app = create_app(settings=test_app_settings)
    app.state.editable_inference_gateway = EditableInferenceGateway(FakeEditableInferenceBackend(gate=gate))
    with TestClient(app) as client:
        initialize = client.post(
            "/v1/edit-session/initialize",
            json={
                "raw_text": "第一句。",
                "voice_id": "demo",
            },
        )
        assert initialize.status_code == 202
        job_id = initialize.json()["job"]["job_id"]

        gate.set()
        _wait_until(lambda: client.get("/v1/edit-session/snapshot").json()["session_status"] == "ready")

        snapshot = client.get("/v1/edit-session/snapshot")
        assert snapshot.status_code == 200
        snapshot_payload = snapshot.json()
        assert len(snapshot_payload["segments"]) == 1
        assert snapshot_payload["segments"][0]["render_asset_id"] is not None

        timeline = client.get("/v1/edit-session/timeline")
        assert timeline.status_code == 200
        timeline_payload = timeline.json()
        assert len(timeline_payload["segment_entries"]) == 1
        assert len(timeline_payload["block_entries"]) == 1

        job = client.get(f"/v1/edit-session/render-jobs/{job_id}")
        assert job.status_code == 200
        job_payload = job.json()
        assert job_payload["changed_block_asset_ids"] == [timeline_payload["block_entries"][0]["block_asset_id"]]


def test_initialize_route_defaults_to_block_first_and_exposes_exact_block_alignment(test_app_settings):
    gate = threading.Event()
    settings = replace(test_app_settings, edit_session_block_first_enabled=True)
    app = create_app(settings=settings)
    fake_backend = FakeEditableInferenceBackend(gate=gate)
    fake_adapter = FakeBlockAdapter()
    app.state.editable_inference_gateway = EditableInferenceGateway(fake_backend)
    app.state.block_adapter_selector = lambda adapter_id, **kwargs: fake_adapter

    with TestClient(app) as client:
        initialize = client.post(
            "/v1/edit-session/initialize",
            json={
                "raw_text": "第一句。第二句。",
                "voice_id": "demo",
            },
        )
        assert initialize.status_code == 202

        gate.set()
        _wait_until(lambda: client.get("/v1/edit-session/snapshot").json()["session_status"] == "ready")

        timeline_payload = client.get("/v1/edit-session/timeline").json()

        assert fake_backend.segment_calls == []
        assert len(fake_adapter.requests) == 1
        assert [entry["segment_alignment_mode"] for entry in timeline_payload["block_entries"]] == ["exact"]


def test_initialize_route_rollback_switch_can_force_segment_first_for_new_job(test_app_settings):
    gate = threading.Event()
    settings = replace(test_app_settings, edit_session_block_first_enabled=False)
    app = create_app(settings=settings)
    fake_backend = FakeEditableInferenceBackend(gate=gate)
    fake_adapter = FakeBlockAdapter()
    app.state.editable_inference_gateway = EditableInferenceGateway(fake_backend)
    app.state.block_adapter_selector = lambda adapter_id, **kwargs: fake_adapter

    with TestClient(app) as client:
        initialize = client.post(
            "/v1/edit-session/initialize",
            json={
                "raw_text": "第一句。第二句。",
                "voice_id": "demo",
            },
        )
        assert initialize.status_code == 202

        gate.set()
        _wait_until(lambda: client.get("/v1/edit-session/snapshot").json()["session_status"] == "ready")

        assert len(fake_backend.segment_calls) == 2
        assert fake_adapter.requests == []


def test_preview_route_returns_expiring_segment_edge_and_block_assets_after_initialize(test_app_settings):
    gate = threading.Event()
    settings = replace(test_app_settings, edit_session_block_first_enabled=False)
    app = create_app(settings=settings)
    app.state.editable_inference_gateway = EditableInferenceGateway(FakeEditableInferenceBackend(gate=gate))
    with TestClient(app) as client:
        initialize = client.post(
            "/v1/edit-session/initialize",
            json={
                "raw_text": "第一句。第二句。",
                "voice_id": "demo",
            },
        )
        assert initialize.status_code == 202

        gate.set()
        _wait_until(lambda: client.get("/v1/edit-session/snapshot").json()["session_status"] == "ready")

        snapshot = client.get("/v1/edit-session/snapshot").json()
        timeline = client.get("/v1/edit-session/timeline").json()
        segment_id = snapshot["segments"][0]["segment_id"]
        edge_id = snapshot["edges"][0]["edge_id"]
        block_id = timeline["block_entries"][0]["block_asset_id"]

        segment_preview = client.get("/v1/edit-session/preview", params={"segment_id": segment_id})
        edge_preview = client.get("/v1/edit-session/preview", params={"edge_id": edge_id})
        block_preview = client.get("/v1/edit-session/preview", params={"block_id": block_id})

        assert segment_preview.status_code == 200
        assert edge_preview.status_code == 200
        assert block_preview.status_code == 200
        assert segment_preview.json()["preview_kind"] == "segment"
        assert edge_preview.json()["preview_kind"] == "edge"
        assert block_preview.json()["preview_kind"] == "block"
        assert segment_preview.json()["audio_delivery"]["expires_at"] is not None
        assert edge_preview.json()["audio_delivery"]["expires_at"] is not None
        assert block_preview.json()["audio_delivery"]["expires_at"] is not None


def test_delete_session_waits_for_active_job_to_cancel_before_clearing(test_app_settings):
    gate = threading.Event()
    app = create_app(settings=test_app_settings)
    app.state.editable_inference_gateway = EditableInferenceGateway(
        FakeEditableInferenceBackend(gate=gate, wait_timeout=None)
    )
    with TestClient(app) as client:
        initialize = client.post(
            "/v1/edit-session/initialize",
            json={
                "raw_text": "第一句。第二句。",
                "voice_id": "demo",
            },
        )
        assert initialize.status_code == 202
        job_id = initialize.json()["job"]["job_id"]
        subscriber = app.state.edit_session_runtime.subscribe(job_id)

        delete_result: dict[str, object] = {}

        def _delete_session() -> None:
            delete_result["response"] = client.delete("/v1/edit-session")

        delete_thread = threading.Thread(target=_delete_session, daemon=True)
        delete_thread.start()

        cancel_requested_seen = False
        deadline = time.time() + 8.0
        try:
            while time.time() < deadline:
                try:
                    event = subscriber.get(timeout=0.2)
                except queue.Empty:
                    continue
                if event.get("event") != "job_state_changed":
                    continue
                payload = event.get("data") or {}
                if payload.get("status") == "cancel_requested":
                    cancel_requested_seen = True
                    break
        finally:
            app.state.edit_session_runtime.unsubscribe(job_id, subscriber)

        assert cancel_requested_seen
        assert delete_thread.is_alive()

        gate.set()
        delete_thread.join(timeout=3.0)
        assert not delete_thread.is_alive()

        delete_response = delete_result["response"]
        assert delete_response.status_code == 204

        after_delete = client.get("/v1/edit-session/snapshot")
        assert after_delete.status_code == 200
        assert after_delete.json()["session_status"] == "empty"


def test_upload_reference_audio_returns_temporary_path(test_app_settings):
    app = create_app(settings=test_app_settings)
    with TestClient(app) as client:
        _seed_ready_session(app, segment_count=1)

        response = client.post(
            "/v1/edit-session/reference-audio",
            files={
                "ref_audio_file": ("custom.wav", b"RIFFcustom", "audio/wav"),
            },
        )

    assert response.status_code == 200
    data = response.json()
    assert data["filename"] == "custom.wav"
    assert data["reference_asset_id"]
    assert data["reference_scope"] == "session_override"
    assert data["reference_identity"].endswith(data["reference_asset_id"])
    assert data["reference_audio_fingerprint"]
    assert data["reference_text_fingerprint"] == "da39a3ee5e6b4b0d3255bfef95601890afd80709"
    uploaded_path = Path(data["reference_audio_path"])
    assert uploaded_path.exists()
    assert uploaded_path.name == "audio.wav"
    assert uploaded_path.parent.name == data["reference_asset_id"]
    assert "references" in uploaded_path.parts
    metadata_path = uploaded_path.with_name("metadata.json")
    assert metadata_path.exists()


def test_upload_reference_audio_rejects_unsupported_extension(test_app_settings):
    app = create_app(settings=test_app_settings)
    with TestClient(app) as client:
        response = client.post(
            "/v1/edit-session/reference-audio",
            files={
                "ref_audio_file": ("custom.txt", b"plain-text", "text/plain"),
            },
        )

    assert response.status_code == 400
    assert response.json() == {
        "detail": "ref_audio_file must use one of: .flac, .mp3, .wav."
    }


def test_initialize_route_does_not_construct_real_backend_before_accepted_response(test_app_settings, monkeypatch):
    constructed: list[tuple[str, str, str, str]] = []
    runtime_module = importlib.import_module("backend.app.inference.pytorch_optimized")

    def fake_runtime(gpt_path: str, sovits_path: str, cnhubert_path: str, bert_path: str):
        constructed.append((gpt_path, sovits_path, cnhubert_path, bert_path))
        return FakeEditableInferenceBackend()

    class _FakeWorkerThread:
        def __init__(self, *args, **kwargs) -> None:
            del args, kwargs

        def start(self) -> None:
            return None

    monkeypatch.setattr(runtime_module, "GPTSoVITSOptimizedInference", fake_runtime)
    monkeypatch.setattr(
        render_job_service_module,
        "threading",
        SimpleNamespace(Thread=_FakeWorkerThread),
    )

    app = create_app(settings=test_app_settings)
    with TestClient(app) as client:
        initialize = client.post(
            "/v1/edit-session/initialize",
            json={
                "raw_text": "第一句。第二句。",
                "voice_id": "demo",
            },
        )

    assert initialize.status_code == 202
    assert constructed == []


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
            assert first_event_line == "event: job_state_changed"
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
                if '"status": "cancel_requested"' in payload:
                    statuses.append("cancel_requested")
                if '"status": "cancelled_partial"' in payload:
                    statuses.append("cancelled_partial")
                    break

        assert statuses[-1:] == ["cancelled_partial"]
        assert set(statuses).issubset({"cancel_requested", "cancelled_partial"})


def test_edit_session_segment_crud_and_read_models(test_app_settings):
    backend = FakeEditableInferenceBackend()
    settings = replace(test_app_settings, edit_session_block_first_enabled=False)
    app = create_app(settings=settings)
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
        assert [_segment_display_text(item) for item in list_segments.json()["items"]] == ["第一句。", "第三句。"]

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
        assert [_segment_display_text(item) for item in inserted_snapshot["segments"]] == [
            "第一句。",
            "第二句。",
            "第三句。",
        ]
        inserted_segment_id = inserted_snapshot["segments"][1]["segment_id"]
        assert len(backend.segment_calls) == 3
        assert len(backend.boundary_calls) == 3

        delete_response = client.delete(f"/v1/edit-session/segments/{inserted_segment_id}")
        assert delete_response.status_code == 202
        _wait_until(lambda: client.get("/v1/edit-session/snapshot").json()["document_version"] == 3)

        deleted_snapshot = client.get("/v1/edit-session/snapshot").json()
        assert [_segment_display_text(item) for item in deleted_snapshot["segments"]] == ["第一句。", "第三句。"]
        assert len(backend.segment_calls) == 3
        assert len(backend.boundary_calls) == 4

        composition = client.get("/v1/edit-session/composition")
        assert composition.status_code == 404

        playback_map = client.get("/v1/edit-session/playback-map")
        assert playback_map.status_code == 200
        assert playback_map.json()["document_version"] == 3
        assert len(playback_map.json()["entries"]) == 2


def test_edit_session_swap_segments_reorders_without_rerendering_segments(test_app_settings):
    backend = FakeEditableInferenceBackend()
    settings = replace(test_app_settings, edit_session_block_first_enabled=False)
    app = create_app(settings=settings)
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

        initial_snapshot = client.get("/v1/edit-session/snapshot").json()
        second_segment_id = initial_snapshot["segments"][1]["segment_id"]
        third_segment_id = initial_snapshot["segments"][2]["segment_id"]
        baseline_segment_calls = len(backend.segment_calls)
        baseline_boundary_calls = len(backend.boundary_calls)

        swap_response = client.post(
            "/v1/edit-session/segments/swap",
            json={
                "first_segment_id": second_segment_id,
                "second_segment_id": third_segment_id,
            },
        )

        assert swap_response.status_code == 202
        _wait_until(lambda: client.get("/v1/edit-session/snapshot").json()["document_version"] == 2)

        swapped_snapshot = client.get("/v1/edit-session/snapshot").json()
        assert [_segment_display_text(item) for item in swapped_snapshot["segments"]] == [
            "第一句。",
            "第三句。",
            "第二句。",
        ]
        assert [(edge["left_segment_id"], edge["right_segment_id"]) for edge in swapped_snapshot["edges"]] == [
            (swapped_snapshot["segments"][0]["segment_id"], swapped_snapshot["segments"][1]["segment_id"]),
            (swapped_snapshot["segments"][1]["segment_id"], swapped_snapshot["segments"][2]["segment_id"]),
        ]
        assert len(backend.segment_calls) == baseline_segment_calls
        assert len(backend.boundary_calls) == baseline_boundary_calls

        playback_map = client.get("/v1/edit-session/playback-map")
        assert playback_map.status_code == 200
        assert [entry["segment_id"] for entry in playback_map.json()["entries"]] == [
            swapped_snapshot["segments"][0]["segment_id"],
            swapped_snapshot["segments"][1]["segment_id"],
            swapped_snapshot["segments"][2]["segment_id"],
        ]

        composition = client.get("/v1/edit-session/composition")
        assert composition.status_code == 404


def test_edit_session_reorder_segments_reorders_without_rerendering_segments(test_app_settings):
    backend = FakeEditableInferenceBackend()
    settings = replace(test_app_settings, edit_session_block_first_enabled=False)
    app = create_app(settings=settings)
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

        initial_snapshot = client.get("/v1/edit-session/snapshot").json()
        baseline_segment_calls = len(backend.segment_calls)
        baseline_boundary_calls = len(backend.boundary_calls)

        reorder_response = client.post(
            "/v1/edit-session/segments/reorder",
            json={
                "base_document_version": initial_snapshot["document_version"],
                "ordered_segment_ids": [
                    initial_snapshot["segments"][2]["segment_id"],
                    initial_snapshot["segments"][0]["segment_id"],
                    initial_snapshot["segments"][1]["segment_id"],
                ],
            },
        )

        assert reorder_response.status_code == 202
        _wait_until(lambda: client.get("/v1/edit-session/snapshot").json()["document_version"] == 2)

        reordered_snapshot = client.get("/v1/edit-session/snapshot").json()
        assert [_segment_display_text(item) for item in reordered_snapshot["segments"]] == [
            "第三句。",
            "第一句。",
            "第二句。",
        ]
        assert [(edge["left_segment_id"], edge["right_segment_id"]) for edge in reordered_snapshot["edges"]] == [
            (reordered_snapshot["segments"][0]["segment_id"], reordered_snapshot["segments"][1]["segment_id"]),
            (reordered_snapshot["segments"][1]["segment_id"], reordered_snapshot["segments"][2]["segment_id"]),
        ]
        assert reordered_snapshot["edges"][0]["boundary_strategy"] == "crossfade_only"
        assert reordered_snapshot["edges"][0]["boundary_strategy_locked"] is True
        assert reordered_snapshot["edges"][1]["boundary_strategy"] == "latent_overlap_then_equal_power_crossfade"
        assert reordered_snapshot["edges"][1]["boundary_strategy_locked"] is False
        assert len(backend.segment_calls) == baseline_segment_calls
        assert len(backend.boundary_calls) == baseline_boundary_calls

        playback_map = client.get("/v1/edit-session/playback-map")
        assert playback_map.status_code == 200
        assert [entry["segment_id"] for entry in playback_map.json()["entries"]] == [
            reordered_snapshot["segments"][0]["segment_id"],
            reordered_snapshot["segments"][1]["segment_id"],
            reordered_snapshot["segments"][2]["segment_id"],
        ]

        locked_strategy_response = client.patch(
            f"/v1/edit-session/edges/{reordered_snapshot['edges'][0]['edge_id']}",
            json={"boundary_strategy": "hard_cut"},
        )
        assert locked_strategy_response.status_code == 400
        assert "已锁定" in locked_strategy_response.json()["detail"]


def test_edit_session_reorder_segments_rejects_stale_document_version(test_app_settings):
    app = create_app(settings=test_app_settings)
    app.state.editable_inference_gateway = EditableInferenceGateway(FakeEditableInferenceBackend())
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

        snapshot = client.get("/v1/edit-session/snapshot").json()
        stale_response = client.post(
            "/v1/edit-session/segments/reorder",
            json={
                "base_document_version": snapshot["document_version"] + 1,
                "ordered_segment_ids": [
                    snapshot["segments"][1]["segment_id"],
                    snapshot["segments"][0]["segment_id"],
                    snapshot["segments"][2]["segment_id"],
                ],
            },
        )

        assert stale_response.status_code == 409
        assert "document version" in stale_response.json()["detail"]


def test_edit_session_segment_edge_preview_and_restore_baseline(test_app_settings):
    backend = FakeEditableInferenceBackend()
    settings = replace(test_app_settings, edit_session_block_first_enabled=False)
    app = create_app(settings=settings)
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
            json={
                "text_patch": {
                    "stem": "第一句已修改",
                    "terminal_raw": "。",
                    "terminal_closer_suffix": "",
                    "terminal_source": "original",
                }
            },
        )
        assert patch_segment.status_code == 202
        _wait_until(lambda: client.get("/v1/edit-session/snapshot").json()["document_version"] == 2)

        updated_snapshot = client.get("/v1/edit-session/snapshot").json()
        assert _segment_display_text(updated_snapshot["segments"][0]) == "第一句已修改。"
        assert len(backend.segment_calls) == 3
        assert len(backend.boundary_calls) == 2
        timeline_before_pause = client.get("/v1/edit-session/timeline").json()

        patch_edge = client.patch(
            f"/v1/edit-session/edges/{edge_id}",
            json={"pause_duration_seconds": 0.8},
        )
        assert patch_edge.status_code == 202
        _wait_until(lambda: client.get("/v1/edit-session/snapshot").json()["document_version"] == 3)

        paused_snapshot = client.get("/v1/edit-session/snapshot").json()
        paused_timeline = client.get("/v1/edit-session/timeline").json()
        assert paused_snapshot["edges"][0]["pause_duration_seconds"] == 0.8
        assert paused_timeline["edge_entries"][0]["pause_duration_seconds"] == 0.8
        assert paused_timeline["playable_sample_span"][1] > timeline_before_pause["playable_sample_span"][1]
        assert paused_timeline["block_entries"][0]["audio_url"] != timeline_before_pause["block_entries"][0]["audio_url"]
        assert len(backend.segment_calls) == 3
        assert len(backend.boundary_calls) == 2

        segment_preview = client.get("/v1/edit-session/preview", params={"segment_id": segment_id})
        assert segment_preview.status_code == 200
        assert segment_preview.json()["preview_kind"] == "segment"
        assert segment_preview.json()["audio_delivery"]["audio_url"].endswith("/audio")
        assert segment_preview.json()["audio_delivery"]["expires_at"] is not None

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

        restore = client.post("/v1/edit-session/restore-baseline")
        assert restore.status_code == 202
        _wait_until(lambda: client.get("/v1/edit-session/snapshot").json()["document_version"] == 5)

        restored_snapshot = client.get("/v1/edit-session/snapshot").json()
        assert _segment_display_text(restored_snapshot["segments"][0]) == "第一句。"
        assert restored_snapshot["edges"][0]["pause_duration_seconds"] == 0.3


def test_standardization_preview_route_returns_capsules_and_language_summary(test_app_settings):
    app = create_app(settings=test_app_settings)

    with TestClient(app) as client:
        response = client.post(
            "/v1/edit-session/standardization-preview",
            json={
                "raw_text": '第一句？！\nSecond sentence!\n第三句”',
                "text_language": "auto",
                "segment_limit": 2,
            },
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["analysis_stage"] == "complete"
        assert payload["total_segments"] == 3
        assert payload["next_cursor"] == 2
        assert payload["resolved_document_language"] == "zh"
        assert payload["language_detection_source"] == "auto"
        assert payload["segments"][0]["stem"] == "第一句"
        assert payload["segments"][0]["display_text"] == "第一句？！"
        assert payload["segments"][0]["terminal_raw"] == "？！"
        assert payload["segments"][0]["detected_language"] == "zh"
        assert payload["segments"][1]["stem"] == "Second sentence"
        assert payload["segments"][1]["display_text"] == "Second sentence!"
        assert payload["segments"][1]["detected_language"] == "en"
        assert payload["segments"][1]["inference_exclusion_reason"] == "other_language_segment"
        assert "canonical_text" not in payload["segments"][0]


def test_edit_session_audio_asset_routes_and_debug_asset_metadata(test_app_settings):
    backend = FakeEditableInferenceBackend()
    settings = replace(test_app_settings, edit_session_block_first_enabled=False)
    app = create_app(settings=settings)
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

        snapshot = client.get("/v1/edit-session/snapshot").json()
        assert snapshot["composition_manifest_id"] is None
        first_segment = snapshot["segments"][0]
        first_edge = snapshot["edges"][0]
        boundary_asset_id = build_boundary_asset_id(
            left_segment_id=first_edge["left_segment_id"],
            left_render_version=1,
            right_segment_id=first_edge["right_segment_id"],
            right_render_version=1,
            edge_version=first_edge["edge_version"],
            boundary_strategy=first_edge["boundary_strategy"],
        )

        composition_payload = _export_composition_for_current_snapshot(
            client,
            target_dir=test_app_settings.edit_session_exports_dir / "asset-route-composition",
        )
        composition_id = composition_payload["composition_manifest_id"]
        refreshed_snapshot = client.get("/v1/edit-session/snapshot").json()
        assert refreshed_snapshot["composition_manifest_id"] == composition_id
        assert composition_payload["audio_delivery"]["audio_url"].endswith(f"/assets/compositions/{composition_id}/audio")

        composition_audio = client.get(
            f"/v1/edit-session/assets/compositions/{composition_id}/audio",
            headers={"Range": "bytes=0-7"},
        )
        assert composition_audio.status_code == 206
        assert composition_audio.headers["content-type"] == "audio/wav"
        assert composition_audio.headers["accept-ranges"] == "bytes"
        assert composition_audio.headers["etag"]

        segment_asset = client.get(f"/v1/edit-session/assets/segments/{first_segment['render_asset_id']}")
        assert segment_asset.status_code == 200
        assert segment_asset.json()["render_asset_id"] == first_segment["render_asset_id"]
        assert segment_asset.json()["audio_delivery"]["audio_url"].endswith(
            f"/assets/segments/{first_segment['render_asset_id']}/audio"
        )

        segment_audio = client.get(f"/v1/edit-session/assets/segments/{first_segment['render_asset_id']}/audio")
        assert segment_audio.status_code == 200
        assert segment_audio.headers["content-type"] == "audio/wav"

        boundary_asset = client.get(f"/v1/edit-session/assets/boundaries/{boundary_asset_id}")
        assert boundary_asset.status_code == 200
        assert boundary_asset.json()["boundary_asset_id"] == boundary_asset_id
        assert boundary_asset.json()["audio_delivery"]["audio_url"].endswith(
            f"/assets/boundaries/{boundary_asset_id}/audio"
        )

        boundary_audio = client.get(
            f"/v1/edit-session/assets/boundaries/{boundary_asset_id}/audio",
            params={"download": 1},
        )
        assert boundary_audio.status_code == 200
        assert boundary_audio.headers["content-disposition"] == f'attachment; filename="{boundary_asset_id}.wav"'


def test_preview_audio_returns_410_after_expiration(test_app_settings):
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

        snapshot = client.get("/v1/edit-session/snapshot").json()
        segment_id = snapshot["segments"][0]["segment_id"]
        preview = client.get("/v1/edit-session/preview", params={"segment_id": segment_id})
        assert preview.status_code == 200
        preview_asset_id = preview.json()["preview_asset_id"]

        metadata_path = app.state.edit_asset_store.preview_asset_path(preview_asset_id) / "metadata.json"
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        metadata["expires_at"] = "2000-01-01T00:00:00+00:00"
        metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")

        expired_audio = client.get(f"/v1/edit-session/assets/previews/{preview_asset_id}/audio")
        assert expired_audio.status_code == 410


def test_snapshot_paginates_when_segment_count_reaches_1000(test_app_settings):
    app = create_app(settings=test_app_settings)

    with TestClient(app) as client:
        _seed_ready_session(app, segment_count=1000)
        snapshot = client.get("/v1/edit-session/snapshot")
        assert snapshot.status_code == 200
        payload = snapshot.json()
        assert payload["total_segment_count"] == 1000
        assert payload["total_edge_count"] == 999
        assert payload["segments"] == []
        assert payload["edges"] == []

        segments_page = client.get("/v1/edit-session/segments", params={"limit": 2})
        assert segments_page.status_code == 200
        assert len(segments_page.json()["items"]) == 2


def test_service_recovers_session_after_app_restart(test_app_settings):
    first_app = create_app(settings=test_app_settings)
    first_app.state.editable_inference_gateway = EditableInferenceGateway(FakeEditableInferenceBackend())
    with TestClient(first_app) as client:
        initialize = client.post(
            "/v1/edit-session/initialize",
            json={
                "raw_text": "第一句。第二句。",
                "voice_id": "demo",
            },
        )
        assert initialize.status_code == 202
        _wait_until(lambda: client.get("/v1/edit-session/snapshot").json()["session_status"] == "ready")
        first_snapshot = client.get("/v1/edit-session/snapshot").json()

    restarted_app = create_app(settings=test_app_settings)
    with TestClient(restarted_app) as client:
        restarted_snapshot = client.get("/v1/edit-session/snapshot")
        assert restarted_snapshot.status_code == 200
        payload = restarted_snapshot.json()
        assert payload["session_status"] == "ready"
        assert payload["document_id"] == first_snapshot["document_id"]
        assert payload["document_version"] == first_snapshot["document_version"]


def test_startup_reconcile_marks_zombie_job_failed_and_clears_active_job(test_app_settings):
    repository = EditSessionRepository(
        project_root=test_app_settings.project_root,
        db_file=test_app_settings.edit_session_db_file,
    )
    repository.initialize_schema()
    repository.save_render_job(
        RenderJobRecord(
            job_id="job-zombie",
            document_id="doc-zombie",
            job_kind="initialize",
            status="rendering",
            progress=0.4,
            message="still running",
            cancel_requested=False,
            updated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
    )
    repository.upsert_active_session(
        ActiveDocumentState(
            document_id="doc-zombie",
            session_status="initializing",
            active_job_id="job-zombie",
            initialize_request=InitializeEditSessionRequest(raw_text="第一句。", voice_id="demo"),
            created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            updated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
    )

    application = create_app(settings=test_app_settings)

    with TestClient(application) as client:
        snapshot = client.get("/v1/edit-session/snapshot")
        assert snapshot.status_code == 200
        payload = snapshot.json()
        assert payload["session_status"] == "failed"
        assert payload["document_id"] == "doc-zombie"
        assert payload["active_job"] is None

        job_response = client.get("/v1/edit-session/render-jobs/job-zombie")
        assert job_response.status_code == 200
        job_payload = job_response.json()
        assert job_payload["status"] == "failed"
        assert "Recovered on startup" in job_payload["message"]


def test_startup_reconcile_cleans_orphan_preview_and_expired_staging(test_app_settings):
    store = EditAssetStore(
        project_root=test_app_settings.project_root,
        assets_dir=test_app_settings.edit_session_assets_dir,
        export_root=test_app_settings.edit_session_exports_dir,
        staging_ttl_seconds=test_app_settings.edit_session_staging_ttl_seconds,
    )
    store.create_preview_asset(
        job_id="job-preview",
        preview_asset_id="preview-orphan",
        preview_kind="segment",
        payload=b"preview",
        ttl_seconds=3600,
        now=datetime.now(timezone.utc),
    )
    expired_file = store.write_staging_bytes("job-old", "segments/render-old/audio.wav", b"old")
    old_timestamp = (
        datetime.now(timezone.utc) - timedelta(seconds=test_app_settings.edit_session_staging_ttl_seconds + 10)
    ).timestamp()
    os.utime(expired_file.parents[2], (old_timestamp, old_timestamp))

    application = create_app(settings=test_app_settings)

    with TestClient(application) as client:
        snapshot = client.get("/v1/edit-session/snapshot")
        assert snapshot.status_code == 200
        assert snapshot.json()["session_status"] == "empty"

    assert not store.preview_asset_path("preview-orphan").exists()
    assert not (test_app_settings.edit_session_assets_dir / "staging" / "job-old").exists()


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
