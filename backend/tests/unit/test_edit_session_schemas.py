from datetime import datetime, timezone

from backend.app.schemas.edit_session import (
    AudioDeliveryDescriptor,
    CompositionResponse,
    EditableEdgeResponse,
    EditableSegmentResponse,
    InitializeEditSessionRequest,
    PreviewRequest,
    PreviewResponse,
    RenderJobResponse,
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
        updated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )

    assert job.model_dump()["current_segment_index"] == 1
    assert job.model_dump()["total_segment_count"] == 4
    assert job.model_dump()["current_block_index"] == 0
    assert job.model_dump()["total_block_count"] == 1


def test_audio_delivery_contract_is_metadata_only():
    descriptor = AudioDeliveryDescriptor(
        asset_id="asset-1",
        audio_url="/v1/edit-session/assets/previews/asset-1/audio",
        sample_rate=32000,
        byte_length=1024,
        etag="etag-1",
        expires_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )

    composition = CompositionResponse(
        composition_manifest_id="comp-1",
        document_id="doc-1",
        document_version=2,
        materialized_audio_available=True,
        audio_delivery=descriptor,
    )
    preview = PreviewResponse(
        preview_asset_id="preview-1",
        preview_kind="segment",
        audio_delivery=descriptor,
    )

    assert composition.audio_delivery.audio_url.endswith("/audio")
    assert composition.audio_delivery.content_type == "audio/wav"
    assert composition.audio_delivery.supports_range is True
    assert preview.audio_delivery.expires_at is not None


def test_preview_request_requires_exactly_one_target():
    request = PreviewRequest(segment_id="seg-1")

    assert request.segment_id == "seg-1"


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
    assert edge.pause_duration_seconds == 0.3
    assert edge.boundary_strategy == "latent_overlap_then_equal_power_crossfade"
