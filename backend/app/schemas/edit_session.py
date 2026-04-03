from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


class InitializeEditSessionRequest(BaseModel):
    raw_text: str
    text_language: str = "auto"
    voice_id: str
    model_id: str = "gpt-sovits-v2"
    reference_audio_path: str | None = None
    reference_text: str | None = None
    reference_language: str | None = None
    speed: float = 1.0
    top_k: int = 15
    top_p: float = 1.0
    temperature: float = 1.0
    pause_duration_seconds: float = 0.3
    noise_scale: float = 0.35
    segment_boundary_mode: str = "raw_strong_punctuation"


class AudioDeliveryDescriptor(BaseModel):
    asset_id: str
    audio_url: str
    content_type: Literal["audio/wav"] = "audio/wav"
    sample_rate: int
    byte_length: int | None = None
    supports_range: bool = True
    etag: str
    expires_at: datetime | None = None


class EditableSegment(BaseModel):
    segment_id: str
    document_id: str
    order_key: int
    previous_segment_id: str | None = None
    next_segment_id: str | None = None
    segment_kind: Literal["speech"] = "speech"
    raw_text: str
    normalized_text: str
    text_language: str
    render_version: int = 0
    render_asset_id: str | None = None
    inference_override: dict[str, Any] = Field(default_factory=dict)
    assembled_audio_span: tuple[int, int] | None = None


class EditableSegmentResponse(EditableSegment):
    pass


class EditableEdge(BaseModel):
    edge_id: str
    document_id: str
    left_segment_id: str
    right_segment_id: str
    pause_duration_seconds: float = 0.3
    boundary_strategy: str = "latent_overlap_then_equal_power_crossfade"
    edge_version: int = 1


class EditableEdgeResponse(EditableEdge):
    pass


class ActiveDocumentState(BaseModel):
    document_id: str
    session_status: Literal["initializing", "ready", "failed"] = "initializing"
    baseline_snapshot_id: str | None = None
    head_snapshot_id: str | None = None
    active_job_id: str | None = None
    editable_mode: str = "segment"
    created_at: datetime = Field(default_factory=_now_utc)
    updated_at: datetime = Field(default_factory=_now_utc)


class DocumentSnapshot(BaseModel):
    snapshot_id: str
    document_id: str
    snapshot_kind: Literal["baseline", "head", "staging"]
    document_version: int
    raw_text: str
    normalized_text: str
    segment_ids: list[str] = Field(default_factory=list)
    edge_ids: list[str] = Field(default_factory=list)
    block_ids: list[str] = Field(default_factory=list)
    composition_manifest_id: str | None = None
    playback_map_version: int | None = None
    created_at: datetime = Field(default_factory=_now_utc)
    segments: list[EditableSegment] = Field(default_factory=list)
    edges: list[EditableEdge] = Field(default_factory=list)

    @model_validator(mode="after")
    def _sync_entity_ids(self) -> "DocumentSnapshot":
        if self.segments and not self.segment_ids:
            self.segment_ids = [segment.segment_id for segment in self.segments]
        if self.edges and not self.edge_ids:
            self.edge_ids = [edge.edge_id for edge in self.edges]
        return self


class RenderJobResponse(BaseModel):
    job_id: str
    document_id: str
    status: Literal[
        "queued",
        "preparing",
        "rendering",
        "composing",
        "committing",
        "cancelling",
        "completed",
        "cancelled",
        "failed",
    ]
    progress: float = Field(default=0.0, ge=0.0, le=1.0)
    message: str = ""
    cancel_requested: bool = False
    current_segment_index: int | None = Field(default=None, ge=0)
    total_segment_count: int | None = Field(default=None, ge=0)
    current_block_index: int | None = Field(default=None, ge=0)
    total_block_count: int | None = Field(default=None, ge=0)
    result_document_version: int | None = None
    updated_at: datetime = Field(default_factory=_now_utc)


class RenderJobRecord(RenderJobResponse):
    job_kind: str
    snapshot_id: str | None = None
    target_segment_ids: list[str] = Field(default_factory=list)
    target_edge_ids: list[str] = Field(default_factory=list)
    target_block_ids: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=_now_utc)


class RenderJobAcceptedResponse(BaseModel):
    job: RenderJobResponse


class PlaybackMapEntry(BaseModel):
    segment_id: str
    order_key: int
    audio_sample_span: tuple[int, int]


class PlaybackMapResponse(BaseModel):
    document_id: str
    document_version: int
    composition_manifest_id: str | None = None
    playable_sample_span: tuple[int, int] | None = None
    entries: list[PlaybackMapEntry] = Field(default_factory=list)


class CompositionResponse(BaseModel):
    composition_manifest_id: str
    document_id: str
    document_version: int
    materialized_audio_available: bool
    audio_delivery: AudioDeliveryDescriptor

    @model_validator(mode="after")
    def _validate_non_expiring_delivery(self) -> "CompositionResponse":
        if self.audio_delivery.expires_at is not None:
            raise ValueError("CompositionResponse.audio_delivery.expires_at must be null for formal assets.")
        return self


class PreviewRequest(BaseModel):
    segment_id: str | None = None
    edge_id: str | None = None
    block_id: str | None = None

    @model_validator(mode="after")
    def _validate_selector(self) -> "PreviewRequest":
        chosen = [self.segment_id, self.edge_id, self.block_id]
        selected_count = sum(value is not None for value in chosen)
        if selected_count != 1:
            raise ValueError("Exactly one of segment_id, edge_id, block_id must be provided.")
        return self


class PreviewResponse(BaseModel):
    preview_asset_id: str
    preview_kind: Literal["segment", "edge", "block"]
    audio_delivery: AudioDeliveryDescriptor

    @model_validator(mode="after")
    def _validate_expiring_delivery(self) -> "PreviewResponse":
        if self.audio_delivery.expires_at is None:
            raise ValueError("PreviewResponse.audio_delivery.expires_at is required.")
        return self


class SegmentAssetResponse(BaseModel):
    render_asset_id: str
    segment_id: str
    render_version: int
    audio_delivery: AudioDeliveryDescriptor

    @model_validator(mode="after")
    def _validate_non_expiring_delivery(self) -> "SegmentAssetResponse":
        if self.audio_delivery.expires_at is not None:
            raise ValueError("SegmentAssetResponse.audio_delivery.expires_at must be null for formal assets.")
        return self


class BoundaryAssetResponse(BaseModel):
    boundary_asset_id: str
    left_segment_id: str
    right_segment_id: str
    edge_version: int
    audio_delivery: AudioDeliveryDescriptor

    @model_validator(mode="after")
    def _validate_non_expiring_delivery(self) -> "BoundaryAssetResponse":
        if self.audio_delivery.expires_at is not None:
            raise ValueError("BoundaryAssetResponse.audio_delivery.expires_at must be null for formal assets.")
        return self


class BaselineSnapshotResponse(BaseModel):
    baseline_snapshot: DocumentSnapshot | None = None


class EditSessionSnapshotResponse(BaseModel):
    session_status: Literal["empty", "initializing", "ready", "failed"] = "empty"
    document_id: str | None = None
    document_version: int | None = None
    baseline_version: int | None = None
    head_version: int | None = None
    total_segment_count: int = 0
    total_edge_count: int = 0
    ready_segment_count: int = 0
    ready_block_count: int = 0
    composition_manifest_id: str | None = None
    composition_audio_url: str | None = None
    playable_sample_span: tuple[int, int] | None = None
    active_job: RenderJobResponse | None = None
    segments: list[EditableSegmentResponse] = Field(default_factory=list)
    edges: list[EditableEdgeResponse] = Field(default_factory=list)
