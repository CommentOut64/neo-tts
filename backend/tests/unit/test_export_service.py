from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from backend.app.inference.audio_processing import build_wav_bytes, float_audio_chunk_to_pcm16_bytes
from backend.app.repositories.edit_session_repository import EditSessionRepository
from backend.app.schemas.edit_session import (
    ActiveDocumentState,
    CompositionExportRequest,
    DocumentSnapshot,
    EditableSegment,
    SegmentExportRequest,
    TimelineManifest,
)
from backend.app.services.edit_asset_store import EditAssetStore
from backend.app.services.export_service import ExportService


def _build_repository(tmp_path: Path) -> EditSessionRepository:
    repository = EditSessionRepository(project_root=tmp_path, db_file=tmp_path / "session.db")
    repository.initialize_schema()
    return repository


def _build_store(tmp_path: Path) -> EditAssetStore:
    return EditAssetStore(
        project_root=tmp_path,
        assets_dir=tmp_path / "assets",
        export_root=tmp_path / "exports",
        staging_ttl_seconds=60,
    )


def _segment(*, segment_id: str, order_key: int, render_asset_id: str | None) -> EditableSegment:
    return EditableSegment(
        segment_id=segment_id,
        document_id="doc-1",
        order_key=order_key,
        stem=f"第{order_key}句",
        text_language="zh",
        terminal_raw="。",
        terminal_source="original",
        detected_language="zh",
        inference_exclusion_reason="none",
        render_asset_id=render_asset_id,
    )


def _persist_segment_asset(store: EditAssetStore, *, render_asset_id: str, audio: list[float]) -> None:
    wav_bytes = build_wav_bytes(4, float_audio_chunk_to_pcm16_bytes(audio))
    store.write_formal_bytes_atomic(f"segments/{render_asset_id}/audio.wav", wav_bytes)
    store.write_formal_json_atomic(
        f"segments/{render_asset_id}/metadata.json",
        {
            "segment_asset_id": render_asset_id,
            "render_asset_id": render_asset_id,
            "segment_id": render_asset_id.replace("render-", "seg-"),
            "render_version": 0,
            "parent_block_asset_id": "block-1",
            "sample_span_in_block": [0, len(audio)],
            "source": "adapter_exact",
            "alignment_mode": "exact",
            "audio_sample_count": len(audio),
            "left_margin_sample_count": 0,
            "core_sample_count": len(audio),
            "right_margin_sample_count": 0,
            "semantic_tokens": [],
            "phone_ids": [],
            "decoder_frame_count": 0,
            "trace": {"derived_from_block": True},
        },
    )


def _persist_block_asset(store: EditAssetStore, *, block_asset_id: str, render_asset_id: str) -> None:
    wav_bytes = build_wav_bytes(4, float_audio_chunk_to_pcm16_bytes([0.1, 0.2, 0.3]))
    store.write_formal_bytes_atomic(f"blocks/{block_asset_id}/audio.wav", wav_bytes)
    store.write_formal_json_atomic(
        f"blocks/{block_asset_id}/metadata.json",
        {
            "block_id": "block-1",
            "block_asset_id": block_asset_id,
            "segment_ids": ["seg-1"],
            "sample_rate": 4,
            "audio_sample_count": 3,
            "segment_alignment_mode": "exact",
            "segment_spans": [
                {
                    "segment_id": "seg-1",
                    "sample_start": 0,
                    "sample_end": 3,
                    "precision": "exact",
                    "confidence": None,
                    "source": None,
                }
            ],
            "segment_entries": [
                {
                    "segment_id": "seg-1",
                    "audio_sample_span": [0, 3],
                    "order_key": 1,
                    "render_asset_id": render_asset_id,
                    "precision": "exact",
                    "source": "adapter_exact",
                }
            ],
            "segment_output_sources": {"seg-1": "adapter_exact"},
            "join_report": {
                "requested_policy": "natural",
                "applied_mode": "natural",
                "enhancement_applied": False,
                "implementation": "adapter-demo",
            },
            "join_report_summary": {
                "requested_policy": "natural",
                "applied_mode": "natural",
                "enhancement_applied": False,
            },
            "adapter_trace": None,
            "diagnostics": {},
            "block_render_cache_key": "cache-1",
            "block_policy_version": "policy-v1",
            "adapter_id": "gpt_sovits_local",
            "model_instance_id": "model-1",
            "preset_id": "preset-1",
            "model_binding_fingerprint": "binding-fp",
            "edge_entries": [],
            "marker_entries": [],
        },
    )


def test_segment_export_keeps_working_for_exact_formal_segment_assets(tmp_path: Path):
    repository = _build_repository(tmp_path)
    store = _build_store(tmp_path)
    export_root = tmp_path / "target-segments"
    render_asset_id = "render-seg-1"
    _persist_segment_asset(store, render_asset_id=render_asset_id, audio=[0.1, 0.2, 0.3])
    timeline = TimelineManifest(
        timeline_manifest_id="timeline-1",
        document_id="doc-1",
        document_version=1,
        timeline_version=1,
        sample_rate=4,
        playable_sample_span=(0, 3),
        block_entries=[],
        segment_entries=[],
        edge_entries=[],
        markers=[],
    )
    store.write_formal_json_atomic(f"timelines/{timeline.timeline_manifest_id}/manifest.json", timeline.model_dump(mode="json"))
    snapshot = DocumentSnapshot(
        snapshot_id="head-1",
        document_id="doc-1",
        snapshot_kind="head",
        document_version=1,
        timeline_manifest_id="timeline-1",
        segments=[_segment(segment_id="seg-1", order_key=1, render_asset_id=render_asset_id)],
        edges=[],
    )
    repository.save_snapshot(snapshot)
    repository.upsert_active_session(
        ActiveDocumentState(
            document_id="doc-1",
            session_status="ready",
            baseline_snapshot_id="head-1",
            head_snapshot_id="head-1",
        )
    )
    service = ExportService(repository=repository, asset_store=store, run_jobs_in_background=False)

    accepted = service.create_segment_export_job(
        SegmentExportRequest(document_version=1, target_dir=str(export_root), overwrite_policy="fail")
    )
    service.run_export_job(accepted.job.export_job_id)
    completed = service.get_job(accepted.job.export_job_id)

    assert completed is not None
    assert completed.status == "completed"
    assert completed.output_manifest is not None
    assert completed.output_manifest.export_kind == "segments"
    assert len(completed.output_manifest.segment_files) == 1
    assert Path(completed.output_manifest.segment_files[0]).exists()


def test_composition_export_keeps_working_for_formal_timeline_block_assets(tmp_path: Path):
    repository = _build_repository(tmp_path)
    store = _build_store(tmp_path)
    export_root = tmp_path / "target-composition"
    render_asset_id = "render-seg-1"
    block_asset_id = "block-asset-1"
    _persist_segment_asset(store, render_asset_id=render_asset_id, audio=[0.1, 0.2, 0.3])
    _persist_block_asset(store, block_asset_id=block_asset_id, render_asset_id=render_asset_id)
    timeline_payload = {
        "timeline_manifest_id": "timeline-1",
        "document_id": "doc-1",
        "document_version": 1,
        "timeline_version": 1,
        "sample_rate": 4,
        "playable_sample_span": [0, 3],
        "block_entries": [
            {
                "block_asset_id": block_asset_id,
                "segment_ids": ["seg-1"],
                "start_sample": 0,
                "end_sample": 3,
                "audio_sample_count": 3,
                "audio_url": f"/v1/edit-session/assets/blocks/{block_asset_id}/audio",
                "segment_alignment_mode": "exact",
                "join_report_summary": {
                    "requested_policy": "natural",
                    "applied_mode": "natural",
                    "enhancement_applied": False,
                },
            }
        ],
        "segment_entries": [
            {
                "segment_id": "seg-1",
                "order_key": 1,
                "start_sample": 0,
                "end_sample": 3,
                "render_status": "ready",
                "group_id": None,
                "render_profile_id": None,
                "voice_binding_id": None,
                "alignment_precision": "exact",
                "source": "adapter_exact",
            }
        ],
        "edge_entries": [],
        "markers": [],
        "created_at": datetime(2026, 1, 1, tzinfo=timezone.utc).isoformat(),
    }
    store.write_formal_json_atomic("timelines/timeline-1/manifest.json", timeline_payload)
    snapshot = DocumentSnapshot(
        snapshot_id="head-1",
        document_id="doc-1",
        snapshot_kind="head",
        document_version=1,
        block_ids=[block_asset_id],
        timeline_manifest_id="timeline-1",
        segments=[_segment(segment_id="seg-1", order_key=1, render_asset_id=render_asset_id)],
        edges=[],
    )
    repository.save_snapshot(snapshot)
    repository.upsert_active_session(
        ActiveDocumentState(
            document_id="doc-1",
            session_status="ready",
            baseline_snapshot_id="head-1",
            head_snapshot_id="head-1",
        )
    )
    service = ExportService(repository=repository, asset_store=store, run_jobs_in_background=False)

    accepted = service.create_composition_export_job(
        CompositionExportRequest(document_version=1, target_dir=str(export_root), overwrite_policy="fail")
    )
    service.run_export_job(accepted.job.export_job_id)
    completed = service.get_job(accepted.job.export_job_id)

    assert completed is not None
    assert completed.status == "completed"
    assert completed.output_manifest is not None
    assert completed.output_manifest.export_kind == "composition"
    assert completed.output_manifest.composition_file is not None
    assert Path(completed.output_manifest.composition_file).exists()
    assert completed.output_manifest.composition_manifest_id is not None
    assert (store.composition_asset_path(completed.output_manifest.composition_manifest_id) / "audio.wav").exists()
