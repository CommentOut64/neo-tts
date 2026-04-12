import pytest

from datetime import datetime, timezone

from pydantic import ValidationError

from backend.app.schemas.edit_session import (
    AudioDeliveryDescriptor,
    BoundaryAssetResponse,
    CheckpointState,
    CompositionResponse,
    EditableEdgeResponse,
    EditableSegmentResponse,
    InitializeEditSessionRequest,
    PreviewRequest,
    PreviewResponse,
    RenderJobResponse,
    SegmentAssetResponse,
    StandardizationPreviewRequest,
    StandardizationPreviewResponse,
)


def test_initialize_edit_session_request_exposes_frozen_defaults():
    request = InitializeEditSessionRequest(
        raw_text="第一句。第二句。",
        voice_id="demo",
    )

    assert request.text_language == "auto"
    assert request.model_id == "gpt-sovits-v2"
    assert request.reference_audio_path is None
    assert request.reference_text is None
    assert request.reference_language is None
    assert request.speed == 1.0
    assert request.top_k == 15
    assert request.top_p == 1.0
    assert request.temperature == 1.0
    assert request.pause_duration_seconds == 0.3
    assert request.noise_scale == 0.35
    assert request.segment_boundary_mode == "raw_strong_punctuation"


def test_render_job_response_exposes_frozen_progress_fields():
    job = RenderJobResponse(
        job_id="job-1",
        document_id="doc-1",
        status="queued",
        progress=0.25,
        message="queued",
        cancel_requested=False,
        current_segment_index=1,
        total_segment_count=4,
        current_block_index=0,
        total_block_count=1,
        result_document_version=None,
        committed_document_version=2,
        committed_timeline_manifest_id="timeline-2",
        committed_playable_sample_span=(0, 128),
        changed_block_asset_ids=["block-1"],
        updated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )

    assert job.model_dump()["current_segment_index"] == 1
    assert job.model_dump()["total_segment_count"] == 4
    assert job.model_dump()["current_block_index"] == 0
    assert job.model_dump()["total_block_count"] == 1
    assert job.model_dump()["committed_document_version"] == 2
    assert job.model_dump()["committed_timeline_manifest_id"] == "timeline-2"
    assert job.model_dump()["committed_playable_sample_span"] == (0, 128)
    assert job.model_dump()["changed_block_asset_ids"] == ["block-1"]


def test_audio_delivery_contract_is_metadata_only():
    preview_descriptor = AudioDeliveryDescriptor(
        asset_id="asset-1",
        audio_url="/v1/edit-session/assets/previews/asset-1/audio",
        sample_rate=32000,
        byte_length=1024,
        etag="etag-1",
        expires_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    composition_descriptor = AudioDeliveryDescriptor(
        asset_id="comp-1",
        audio_url="/v1/edit-session/assets/compositions/comp-1/audio",
        sample_rate=32000,
        byte_length=2048,
        etag="etag-2",
    )

    composition = CompositionResponse(
        composition_manifest_id="comp-1",
        document_id="doc-1",
        document_version=2,
        materialized_audio_available=True,
        audio_delivery=composition_descriptor,
    )
    preview = PreviewResponse(
        preview_asset_id="preview-1",
        preview_kind="segment",
        audio_delivery=preview_descriptor,
    )

    assert composition.audio_delivery.audio_url.endswith("/audio")
    assert composition.audio_delivery.content_type == "audio/wav"
    assert composition.audio_delivery.supports_range is True
    assert preview.audio_delivery.expires_at is not None


def test_preview_response_requires_expires_at():
    descriptor = AudioDeliveryDescriptor(
        asset_id="preview-1",
        audio_url="/v1/edit-session/assets/previews/preview-1/audio",
        sample_rate=32000,
        etag="etag-1",
    )

    with pytest.raises(ValueError, match="expires_at"):
        PreviewResponse(
            preview_asset_id="preview-1",
            preview_kind="segment",
            audio_delivery=descriptor,
        )


def test_formal_asset_responses_reject_short_ttl():
    expiring_descriptor = AudioDeliveryDescriptor(
        asset_id="asset-1",
        audio_url="/v1/edit-session/assets/segments/asset-1/audio",
        sample_rate=32000,
        etag="etag-1",
        expires_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )

    with pytest.raises(ValueError, match="expires_at"):
        CompositionResponse(
            composition_manifest_id="comp-1",
            document_id="doc-1",
            document_version=2,
            materialized_audio_available=True,
            audio_delivery=expiring_descriptor,
        )

    with pytest.raises(ValueError, match="expires_at"):
        SegmentAssetResponse(
            render_asset_id="render-1",
            segment_id="seg-1",
            render_version=1,
            audio_delivery=expiring_descriptor,
        )

    with pytest.raises(ValueError, match="expires_at"):
        BoundaryAssetResponse(
            boundary_asset_id="boundary-1",
            left_segment_id="seg-1",
            right_segment_id="seg-2",
            edge_version=1,
            audio_delivery=expiring_descriptor,
        )


def test_preview_request_requires_exactly_one_target():
    request = PreviewRequest(segment_id="seg-1")

    assert request.segment_id == "seg-1"


def test_standardization_preview_request_exposes_defaults():
    request = StandardizationPreviewRequest(raw_text="第一句。")

    assert request.text_language == "auto"
    assert request.segment_limit == 80
    assert request.cursor is None
    assert request.include_language_analysis is True


def test_standardization_preview_response_requires_known_stage():
    with pytest.raises(ValidationError):
        StandardizationPreviewResponse(
            analysis_stage="invalid",
            document_char_count=4,
            total_segments=1,
            next_cursor=None,
            resolved_document_language=None,
            language_detection_source=None,
            warnings=[],
            segments=[],
        )


def test_segment_and_edge_response_types_reuse_domain_fields():
    segment = EditableSegmentResponse(
        segment_id="seg-1",
        document_id="doc-1",
        order_key=1,
        raw_text="你好。",
        normalized_text="你好。",
        text_language="zh",
    )
    edge = EditableEdgeResponse(
        edge_id="edge-1",
        document_id="doc-1",
        left_segment_id="seg-1",
        right_segment_id="seg-2",
    )

    assert segment.segment_kind == "speech"
    assert segment.terminal_raw == ""
    assert segment.terminal_closer_suffix == ""
    assert segment.terminal_source == "synthetic"
    assert segment.detected_language == "unknown"
    assert segment.inference_exclusion_reason == "language_unresolved"
    assert edge.pause_duration_seconds == 0.3
    assert edge.boundary_strategy == "latent_overlap_then_equal_power_crossfade"
    assert edge.boundary_strategy_locked is False


def test_checkpoint_state_rejects_running_partial_status():
    with pytest.raises(ValidationError, match="running_partial"):
        CheckpointState(
            checkpoint_id="ck-1",
            document_id="doc-1",
            job_id="job-1",
            document_version=1,
            head_snapshot_id="head-1",
            timeline_manifest_id="timeline-1",
            working_snapshot_id="work-1",
            next_segment_cursor=1,
            completed_segment_ids=["seg-1"],
            remaining_segment_ids=["seg-2"],
            status="running_partial",
            resume_token=None,
            updated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
