from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


class InitializeEditSessionRequest(BaseModel):
    raw_text: str = Field(description="要初始化为 edit-session 的原始全文文本。")
    text_language: str = Field(default="auto", description="全文文本语言，通常为 `auto` 或 `zh`。")
    voice_id: str = Field(description="初始化使用的音色 ID。")
    model_id: str = Field(default="gpt-sovits-v2", description="兼容字段，初始化时记录的模型标识。")
    reference_audio_path: str | None = Field(default=None, description="可选的参考音频路径；未提供时使用 voice 配置默认值。")
    reference_text: str | None = Field(default=None, description="可选的参考文本；未提供时使用 voice 配置默认值。")
    reference_language: str | None = Field(default=None, description="可选的参考文本语言；未提供时使用 voice 配置默认值。")
    speed: float = Field(default=1.0, description="初始化默认语速。")
    top_k: int = Field(default=15, description="初始化默认采样 top_k。")
    top_p: float = Field(default=1.0, description="初始化默认采样 top_p。")
    temperature: float = Field(default=1.0, description="初始化默认采样温度。")
    pause_duration_seconds: float = Field(default=0.3, description="默认段间停顿秒数。")
    noise_scale: float = Field(default=0.35, description="初始化默认 noise scale。")
    segment_boundary_mode: str = Field(
        default="raw_strong_punctuation",
        description="初始化切段策略，例如 `raw_strong_punctuation` 或 `zh_period`。",
    )


class AudioDeliveryDescriptor(BaseModel):
    asset_id: str = Field(description="音频资产 ID。")
    audio_url: str = Field(description="可直接请求的音频地址。")
    content_type: Literal["audio/wav"] = Field(default="audio/wav", description="音频资源的 MIME 类型。")
    sample_rate: int = Field(description="音频采样率。")
    byte_length: int | None = Field(default=None, description="音频字节长度；若未知则为 null。")
    supports_range: bool = Field(default=True, description="该资源是否支持 HTTP Range 请求。")
    etag: str = Field(description="用于缓存与断点请求的实体标签。")
    expires_at: datetime | None = Field(default=None, description="临时资源的过期时间；正式资产通常为 null。")


class RenderProfile(BaseModel):
    render_profile_id: str = Field(description="render profile 的唯一标识。")
    scope: Literal["session", "group", "segment"] = Field(description="profile 生效范围。")
    name: str = Field(default="", description="profile 展示名称。")
    speed: float = Field(default=1.0, description="语速配置。")
    top_k: int = Field(default=15, description="采样 top_k。")
    top_p: float = Field(default=1.0, description="采样 top_p。")
    temperature: float = Field(default=1.0, description="采样温度。")
    noise_scale: float = Field(default=0.35, description="noise scale。")
    reference_audio_path: str | None = Field(default=None, description="可选的参考音频路径。")
    reference_text: str | None = Field(default=None, description="可选的参考文本。")
    reference_language: str | None = Field(default=None, description="可选的参考文本语言。")
    extra_overrides: dict[str, Any] = Field(default_factory=dict, description="额外透传给推理层的覆盖项。")


class VoiceBinding(BaseModel):
    voice_binding_id: str = Field(description="voice/model binding 的唯一标识。")
    scope: Literal["session", "group", "segment"] = Field(description="binding 生效范围。")
    voice_id: str = Field(description="音色 ID。")
    model_key: str = Field(description="模型标识。")
    sovits_path: str | None = Field(default=None, description="可选的 SoVITS 模型路径。")
    gpt_path: str | None = Field(default=None, description="可选的 GPT 模型路径。")
    speaker_meta: dict[str, Any] = Field(default_factory=dict, description="可选的说话人附加元数据。")


class SegmentGroup(BaseModel):
    group_id: str = Field(description="段分组 ID。")
    name: str = Field(default="", description="分组名称。")
    segment_ids: list[str] = Field(default_factory=list, description="当前属于该组的段 ID 列表。")
    render_profile_id: str | None = Field(default=None, description="该组绑定的 render profile ID。")
    voice_binding_id: str | None = Field(default=None, description="该组绑定的 voice/model binding ID。")
    created_by: Literal["append", "batch_patch", "manual"] = Field(default="manual", description="分组来源。")


class EditableSegment(BaseModel):
    segment_id: str = Field(description="段 ID。")
    document_id: str = Field(description="所属文档 ID。")
    order_key: int = Field(description="段在文档中的排序键。")
    previous_segment_id: str | None = Field(default=None, description="前一个相邻段 ID；若不存在则为 null。")
    next_segment_id: str | None = Field(default=None, description="后一个相邻段 ID；若不存在则为 null。")
    segment_kind: Literal["speech"] = Field(default="speech", description="段类型；当前仅支持 `speech`。")
    raw_text: str = Field(description="用户编辑的原始段文本。")
    normalized_text: str = Field(description="归一化后的段文本。")
    text_language: str = Field(description="该段文本语言。")
    render_version: int = Field(default=0, description="当前段正式渲染资产的版本号。")
    render_asset_id: str | None = Field(default=None, description="当前段正式渲染资产 ID；未生成时为 null。")
    group_id: str | None = Field(default=None, description="所属分组 ID；未分组时为 null。")
    render_profile_id: str | None = Field(default=None, description="当前段直接绑定的 render profile ID。")
    voice_binding_id: str | None = Field(default=None, description="当前段直接绑定的 voice/model binding ID。")
    render_status: Literal["pending", "rendering", "ready", "paused", "failed"] = Field(
        default="ready",
        description="当前段渲染状态。",
    )
    segment_revision: int = Field(default=1, description="段元数据修订号。")
    effective_duration_samples: int | None = Field(default=None, description="当前有效音频时长，单位 sample。")
    inference_override: dict[str, Any] = Field(default_factory=dict, description="兼容旧链路的段级推理覆盖项。")
    risk_flags: list[str] = Field(default_factory=list, description="该段当前附带的风险标记列表。")
    assembled_audio_span: tuple[int, int] | None = Field(
        default=None,
        description="该段在当前已装配时间线中的 sample 区间；不可用时为 null。",
    )


class EditableSegmentResponse(EditableSegment):
    pass


class CreateSegmentRequest(BaseModel):
    after_segment_id: str | None = Field(default=None, description="新段要插入到哪个段之后；为 null 时插入到最前面。")
    raw_text: str = Field(description="新段的原始文本。")
    text_language: str = Field(default="auto", description="该段文本语言。")
    inference_override: dict[str, Any] = Field(
        default_factory=dict,
        description="兼容旧入口的段级推理覆盖项；新链路更推荐 profile/binding 接口。",
    )


class RenderProfilePatchRequest(BaseModel):
    name: str | None = Field(default=None, description="新的 profile 名称。")
    speed: float | None = Field(default=None, description="新的语速。")
    top_k: int | None = Field(default=None, description="新的 top_k。")
    top_p: float | None = Field(default=None, description="新的 top_p。")
    temperature: float | None = Field(default=None, description="新的 temperature。")
    noise_scale: float | None = Field(default=None, description="新的 noise scale。")
    reference_audio_path: str | None = Field(default=None, description="新的参考音频路径。")
    reference_text: str | None = Field(default=None, description="新的参考文本。")
    reference_language: str | None = Field(default=None, description="新的参考文本语言。")
    extra_overrides: dict[str, Any] | None = Field(default=None, description="额外推理覆盖项。")

    @model_validator(mode="after")
    def _validate_has_patch_fields(self) -> "RenderProfilePatchRequest":
        if all(
            value is None
            for value in (
                self.name,
                self.speed,
                self.top_k,
                self.top_p,
                self.temperature,
                self.noise_scale,
                self.reference_audio_path,
                self.reference_text,
                self.reference_language,
                self.extra_overrides,
            )
        ):
            raise ValueError("At least one render profile field must be provided.")
        return self


class VoiceBindingPatchRequest(BaseModel):
    voice_id: str | None = Field(default=None, description="新的音色 ID。")
    model_key: str | None = Field(default=None, description="新的模型标识。")
    sovits_path: str | None = Field(default=None, description="新的 SoVITS 模型路径。")
    gpt_path: str | None = Field(default=None, description="新的 GPT 模型路径。")
    speaker_meta: dict[str, Any] | None = Field(default=None, description="新的说话人附加元数据。")

    @model_validator(mode="after")
    def _validate_has_patch_fields(self) -> "VoiceBindingPatchRequest":
        if all(
            value is None
            for value in (
                self.voice_id,
                self.model_key,
                self.sovits_path,
                self.gpt_path,
                self.speaker_meta,
            )
        ):
            raise ValueError("At least one voice binding field must be provided.")
        return self


class AppendSegmentsRequest(BaseModel):
    raw_text: str = Field(description="要追加到尾部的新文本。")
    text_language: str = Field(default="auto", description="追加文本语言。")
    after_segment_id: str | None = Field(default=None, description="可选的插入锚点；不传时默认追加到尾部。")
    segment_boundary_mode: str = Field(default="raw_strong_punctuation", description="追加文本切段策略。")
    target_group_id: str | None = Field(default=None, description="可选的目标组 ID；新段会加入该组。")
    group_render_profile: RenderProfilePatchRequest | None = Field(
        default=None,
        description="可选的组级 render profile patch；提供时可能自动创建组。",
    )
    group_voice_binding: VoiceBindingPatchRequest | None = Field(
        default=None,
        description="可选的组级 voice/model binding patch；提供时可能自动创建组。",
    )


class UpdateSegmentRequest(BaseModel):
    raw_text: str | None = Field(default=None, description="更新后的段文本。")
    text_language: str | None = Field(default=None, description="更新后的文本语言。")
    inference_override: dict[str, Any] | None = Field(default=None, description="兼容旧入口的推理覆盖项。")

    @model_validator(mode="after")
    def _validate_has_patch_fields(self) -> "UpdateSegmentRequest":
        if self.raw_text is None and self.text_language is None and self.inference_override is None:
            raise ValueError("At least one segment field must be provided.")
        return self


class SwapSegmentsRequest(BaseModel):
    first_segment_id: str = Field(description="第一个目标段 ID。")
    second_segment_id: str = Field(description="第二个目标段 ID。")

    @model_validator(mode="after")
    def _validate_distinct_segment_ids(self) -> "SwapSegmentsRequest":
        if self.first_segment_id == self.second_segment_id:
            raise ValueError("Swap segment ids must be different.")
        return self


class MoveSegmentRangeRequest(BaseModel):
    segment_ids: list[str] = Field(min_length=1, description="要整体移动的一组连续段 ID。")
    after_segment_id: str | None = Field(default=None, description="移动目标锚点；移动区间会放到该段之后。")

    @model_validator(mode="after")
    def _validate_unique_segment_ids(self) -> "MoveSegmentRangeRequest":
        if len(set(self.segment_ids)) != len(self.segment_ids):
            raise ValueError("Move range segment ids must be unique.")
        if self.after_segment_id is not None and self.after_segment_id in self.segment_ids:
            raise ValueError("Move target cannot be inside the moving range.")
        return self


class SplitSegmentRequest(BaseModel):
    segment_id: str = Field(description="要拆分的目标段 ID。")
    left_text: str = Field(description="拆分后左半段文本。")
    right_text: str = Field(description="拆分后右半段文本。")
    text_language: str | None = Field(default=None, description="可选的拆分后统一语言。")


class MergeSegmentsRequest(BaseModel):
    left_segment_id: str = Field(description="左侧目标段 ID。")
    right_segment_id: str = Field(description="右侧目标段 ID。")

    @model_validator(mode="after")
    def _validate_distinct_segment_ids(self) -> "MergeSegmentsRequest":
        if self.left_segment_id == self.right_segment_id:
            raise ValueError("Merge segment ids must be different.")
        return self


class EditableEdge(BaseModel):
    edge_id: str = Field(description="边 ID。")
    document_id: str = Field(description="所属文档 ID。")
    left_segment_id: str = Field(description="左侧相邻段 ID。")
    right_segment_id: str = Field(description="右侧相邻段 ID。")
    pause_duration_seconds: float = Field(default=0.3, description="用户配置的段间停顿秒数。")
    boundary_strategy: str = Field(
        default="latent_overlap_then_equal_power_crossfade",
        description="请求使用的边界拼接策略。",
    )
    effective_boundary_strategy: str | None = Field(default=None, description="实际生效的边界策略。")
    pause_sample_count: int | None = Field(default=None, description="当前停顿区间的 sample 数。")
    boundary_sample_count: int | None = Field(default=None, description="当前边界拼接区间的 sample 数。")
    edge_status: Literal["pending", "rendering", "ready", "failed"] = Field(
        default="ready",
        description="当前边渲染状态。",
    )
    edge_version: int = Field(default=1, description="边界资产版本号。")


class EditableEdgeResponse(EditableEdge):
    pass


class UpdateEdgeRequest(BaseModel):
    pause_duration_seconds: float | None = Field(default=None, description="新的段间停顿秒数。")
    boundary_strategy: str | None = Field(default=None, description="新的边界策略。")

    @model_validator(mode="after")
    def _validate_has_patch_fields(self) -> "UpdateEdgeRequest":
        if self.pause_duration_seconds is None and self.boundary_strategy is None:
            raise ValueError("At least one edge field must be provided.")
        return self


class ActiveDocumentState(BaseModel):
    document_id: str
    session_status: Literal["initializing", "ready", "failed"] = "initializing"
    baseline_snapshot_id: str | None = None
    head_snapshot_id: str | None = None
    active_job_id: str | None = None
    editable_mode: str = "segment"
    initialize_request: InitializeEditSessionRequest | None = None
    created_at: datetime = Field(default_factory=_now_utc)
    updated_at: datetime = Field(default_factory=_now_utc)


class DocumentSnapshot(BaseModel):
    snapshot_id: str = Field(description="快照 ID。")
    document_id: str = Field(description="文档 ID。")
    snapshot_kind: Literal["baseline", "head", "staging"] = Field(description="快照类型。")
    document_version: int = Field(description="该快照对应的文档版本号。")
    raw_text: str = Field(description="当前快照的全文原始文本。")
    normalized_text: str = Field(description="当前快照的归一化全文文本。")
    segment_ids: list[str] = Field(default_factory=list, description="当前快照内全部段 ID，按顺序排列。")
    edge_ids: list[str] = Field(default_factory=list, description="当前快照内全部边 ID。")
    block_ids: list[str] = Field(default_factory=list, description="当前时间线 block ID 列表；兼容旧视图。")
    groups: list[SegmentGroup] = Field(default_factory=list, description="当前版本中的全部段分组。")
    render_profiles: list[RenderProfile] = Field(default_factory=list, description="当前版本中的全部 render profile。")
    voice_bindings: list[VoiceBinding] = Field(default_factory=list, description="当前版本中的全部 voice/model binding。")
    default_render_profile_id: str | None = Field(default=None, description="默认 session-scope render profile ID。")
    default_voice_binding_id: str | None = Field(default=None, description="默认 session-scope voice binding ID。")
    composition_manifest_id: str | None = Field(default=None, description="兼容字段；若当前版本已有导出 composition，则为对应资产 ID。")
    playback_map_version: int | None = Field(default=None, description="兼容字段；保留给旧 playback-map 视图。")
    timeline_manifest_id: str | None = Field(default=None, description="当前权威 timeline manifest ID。")
    created_at: datetime = Field(default_factory=_now_utc, description="快照创建时间。")
    segments: list[EditableSegment] = Field(default_factory=list, description="内联返回的段详情列表。")
    edges: list[EditableEdge] = Field(default_factory=list, description="内联返回的边详情列表。")

    @model_validator(mode="after")
    def _sync_entity_ids(self) -> "DocumentSnapshot":
        if self.segments and not self.segment_ids:
            self.segment_ids = [segment.segment_id for segment in self.segments]
        if self.edges and not self.edge_ids:
            self.edge_ids = [edge.edge_id for edge in self.edges]
        return self


class RenderJobResponse(BaseModel):
    job_id: str = Field(description="渲染作业 ID。")
    document_id: str = Field(description="该作业所属文档 ID。")
    status: Literal[
        "queued",
        "preparing",
        "rendering",
        "composing",
        "committing",
        "pause_requested",
        "paused",
        "cancel_requested",
        "cancelled_partial",
        "completed",
        "failed",
    ] = Field(description="render job 当前状态。")
    progress: float = Field(default=0.0, ge=0.0, le=1.0, description="当前作业进度，范围 0~1。")
    message: str = Field(default="", description="面向调用方的当前进度说明。")
    cancel_requested: bool = Field(default=False, description="是否已收到取消请求。")
    pause_requested: bool = Field(default=False, description="是否已收到暂停请求。")
    current_segment_index: int | None = Field(default=None, ge=0, description="当前已处理的段计数。")
    total_segment_count: int | None = Field(default=None, ge=0, description="本次作业预计处理的段总数。")
    current_block_index: int | None = Field(default=None, ge=0, description="当前已完成的 block 计数。")
    total_block_count: int | None = Field(default=None, ge=0, description="本次作业预计处理的 block 总数。")
    result_document_version: int | None = Field(default=None, description="成功完成后提交出的 document_version。")
    checkpoint_id: str | None = Field(default=None, description="若作业暂停或 partial commit，关联的 checkpoint ID。")
    resume_token: str | None = Field(default=None, description="可恢复作业的 resume token。")
    updated_at: datetime = Field(default_factory=_now_utc, description="作业最后更新时间。")


class RenderJobRecord(RenderJobResponse):
    job_kind: str
    snapshot_id: str | None = None
    target_segment_ids: list[str] = Field(default_factory=list)
    target_edge_ids: list[str] = Field(default_factory=list)
    target_block_ids: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=_now_utc)


class RenderJobAcceptedResponse(BaseModel):
    job: RenderJobResponse = Field(description="已接受的 render job 当前状态。")


class CheckpointState(BaseModel):
    checkpoint_id: str = Field(description="checkpoint ID。")
    document_id: str = Field(description="所属文档 ID。")
    job_id: str = Field(description="生成该 checkpoint 的作业 ID。")
    document_version: int = Field(description="checkpoint 对应的文档版本。")
    head_snapshot_id: str = Field(description="提交后的 head snapshot ID。")
    timeline_manifest_id: str = Field(description="checkpoint 对应的 timeline manifest ID。")
    working_snapshot_id: str = Field(description="可恢复工作快照 ID。")
    next_segment_cursor: int = Field(ge=0, description="恢复时下一个待处理段的游标。")
    completed_segment_ids: list[str] = Field(default_factory=list, description="已完成段 ID 列表。")
    remaining_segment_ids: list[str] = Field(default_factory=list, description="剩余待完成段 ID 列表。")
    status: Literal["paused", "cancelled_partial", "resumable"] = Field(description="checkpoint 当前状态。")
    resume_token: str | None = Field(default=None, description="恢复该 checkpoint 的 token。")
    updated_at: datetime = Field(default_factory=_now_utc, description="checkpoint 最后更新时间。")


class CurrentCheckpointResponse(BaseModel):
    checkpoint: CheckpointState | None = Field(default=None, description="当前可恢复 checkpoint；若不存在则为 null。")


class PlaybackMapEntry(BaseModel):
    segment_id: str = Field(description="段 ID。")
    order_key: int = Field(description="段顺序。")
    audio_sample_span: tuple[int, int] = Field(description="该段在整条音频中的 sample 区间。")


class PlaybackMapResponse(BaseModel):
    document_id: str = Field(description="文档 ID。")
    document_version: int = Field(description="当前版本号。")
    composition_manifest_id: str | None = Field(default=None, description="若当前版本已有导出 composition，则为对应资产 ID。")
    playable_sample_span: tuple[int, int] | None = Field(default=None, description="整条可播放 sample 区间。")
    entries: list[PlaybackMapEntry] = Field(default_factory=list, description="按段顺序排列的播放区间列表。")


class TimelineBlockEntry(BaseModel):
    block_asset_id: str = Field(description="block 资产 ID。")
    segment_ids: list[str] = Field(default_factory=list, description="该 block 包含的段 ID 列表。")
    start_sample: int = Field(description="block 在整条时间线中的起始 sample。")
    end_sample: int = Field(description="block 在整条时间线中的结束 sample。")
    audio_sample_count: int = Field(description="block 音频 sample 数。")
    audio_url: str = Field(description="block 音频地址。")


class TimelineSegmentEntry(BaseModel):
    segment_id: str = Field(description="段 ID。")
    order_key: int = Field(description="段顺序。")
    start_sample: int = Field(description="段在整条时间线中的起始 sample。")
    end_sample: int = Field(description="段在整条时间线中的结束 sample。")
    render_status: str = Field(default="ready", description="段当前渲染状态。")
    group_id: str | None = Field(default=None, description="若该段属于某个 group，则为 group ID。")
    render_profile_id: str | None = Field(default=None, description="生效的 render profile ID。")
    voice_binding_id: str | None = Field(default=None, description="生效的 voice binding ID。")


class TimelineEdgeEntry(BaseModel):
    edge_id: str = Field(description="边 ID。")
    left_segment_id: str = Field(description="左侧段 ID。")
    right_segment_id: str = Field(description="右侧段 ID。")
    pause_duration_seconds: float = Field(description="用户设置的停顿秒数。")
    boundary_strategy: str = Field(description="请求的边界策略。")
    effective_boundary_strategy: str = Field(description="实际生效的边界策略。")
    boundary_start_sample: int = Field(description="边界音频起始 sample。")
    boundary_end_sample: int = Field(description="边界音频结束 sample。")
    pause_start_sample: int = Field(description="停顿区间起始 sample。")
    pause_end_sample: int = Field(description="停顿区间结束 sample。")


class TimelineMarkerEntry(BaseModel):
    marker_id: str = Field(description="marker ID。")
    marker_type: Literal[
        "segment_start",
        "segment_end",
        "edge_gap_start",
        "edge_gap_end",
        "block_start",
        "block_end",
    ] = Field(description="marker 类型，用于标记段、边与 block 的关键 sample 位置。")
    sample: int = Field(description="marker 所在 sample 位置。")
    related_id: str = Field(description="与该 marker 关联的段、边或 block ID。")


class TimelineManifest(BaseModel):
    timeline_manifest_id: str = Field(description="timeline manifest ID。")
    document_id: str = Field(description="文档 ID。")
    document_version: int = Field(description="该时间线对应的文档版本。")
    timeline_version: int = Field(description="时间线版本号。")
    sample_rate: int = Field(description="整条时间线采样率。")
    playable_sample_span: tuple[int, int] = Field(description="整条时间线可播放 sample 区间。")
    block_entries: list[TimelineBlockEntry] = Field(default_factory=list, description="按顺序排列的 block 条目。")
    segment_entries: list[TimelineSegmentEntry] = Field(default_factory=list, description="按顺序排列的 segment 条目。")
    edge_entries: list[TimelineEdgeEntry] = Field(default_factory=list, description="按顺序排列的 edge 条目。")
    markers: list[TimelineMarkerEntry] = Field(default_factory=list, description="供前端 seek 和标记显示使用的 marker 列表。")
    created_at: datetime = Field(default_factory=_now_utc, description="manifest 创建时间。")


class CompositionResponse(BaseModel):
    composition_manifest_id: str = Field(description="composition 资产 ID。")
    document_id: str = Field(description="文档 ID。")
    document_version: int = Field(description="该 composition 对应的文档版本。")
    materialized_audio_available: bool = Field(description="是否已有可直接下载的整条音频。")
    audio_delivery: AudioDeliveryDescriptor = Field(description="整条音频的下载描述。")

    @model_validator(mode="after")
    def _validate_non_expiring_delivery(self) -> "CompositionResponse":
        if self.audio_delivery.expires_at is not None:
            raise ValueError("CompositionResponse.audio_delivery.expires_at must be null for formal assets.")
        return self


class GroupListResponse(BaseModel):
    document_id: str = Field(description="文档 ID。")
    document_version: int = Field(description="当前版本号。")
    items: list[SegmentGroup] = Field(default_factory=list, description="当前版本中的全部组。")


class RenderProfileListResponse(BaseModel):
    document_id: str = Field(description="文档 ID。")
    document_version: int = Field(description="当前版本号。")
    items: list[RenderProfile] = Field(default_factory=list, description="当前版本中的全部 render profile。")


class VoiceBindingListResponse(BaseModel):
    document_id: str = Field(description="文档 ID。")
    document_version: int = Field(description="当前版本号。")
    items: list[VoiceBinding] = Field(default_factory=list, description="当前版本中的全部 voice/model binding。")


class ExportRequestBase(BaseModel):
    document_version: int = Field(ge=1, description="要导出的已提交 document_version。")
    target_dir: str = Field(description="导出目标目录，相对路径会解析到受控 export root 下。")
    overwrite_policy: Literal["fail", "replace", "new_folder"] = Field(
        default="fail",
        description="目标目录已存在时的处理策略。",
    )


class SegmentExportRequest(ExportRequestBase):
    pass


class CompositionExportRequest(ExportRequestBase):
    pass


class SegmentBatchRenderProfilePatchRequest(BaseModel):
    segment_ids: list[str] = Field(min_length=1, description="要批量绑定 render profile 的段 ID 列表。")
    patch: RenderProfilePatchRequest = Field(description="要应用到这批段的新 profile patch。")

    @model_validator(mode="after")
    def _validate_unique_segment_ids(self) -> "SegmentBatchRenderProfilePatchRequest":
        if len(set(self.segment_ids)) != len(self.segment_ids):
            raise ValueError("Batch render profile segment ids must be unique.")
        return self


class SegmentBatchVoiceBindingPatchRequest(BaseModel):
    segment_ids: list[str] = Field(min_length=1, description="要批量绑定 voice/model 的段 ID 列表。")
    patch: VoiceBindingPatchRequest = Field(description="要应用到这批段的新 voice binding patch。")

    @model_validator(mode="after")
    def _validate_unique_segment_ids(self) -> "SegmentBatchVoiceBindingPatchRequest":
        if len(set(self.segment_ids)) != len(self.segment_ids):
            raise ValueError("Batch voice binding segment ids must be unique.")
        return self


class ExportOutputManifest(BaseModel):
    export_kind: Literal["segments", "composition"] = Field(description="导出类型。")
    target_dir: str = Field(description="最终导出目录。")
    files: list[str] = Field(default_factory=list, description="导出目录下的全部文件路径。")
    segment_files: list[str] = Field(default_factory=list, description="分段导出的 wav 文件列表。")
    composition_file: str | None = Field(default=None, description="整条音频导出的 wav 文件路径。")
    composition_manifest_id: str | None = Field(default=None, description="若导出类型为 composition，则为对应正式资产 ID。")
    manifest_file: str = Field(description="导出 manifest.json 路径。")
    exported_at: datetime = Field(default_factory=_now_utc, description="导出完成时间。")


class ExportJobResponse(BaseModel):
    export_job_id: str = Field(description="导出作业 ID。")
    document_id: str = Field(description="所属文档 ID。")
    document_version: int = Field(description="导出的文档版本。")
    timeline_manifest_id: str = Field(description="导出使用的 timeline manifest ID。")
    export_kind: Literal["segments", "composition"] = Field(description="导出类型。")
    status: Literal["queued", "exporting", "completed", "failed"] = Field(description="导出作业当前状态。")
    target_dir: str = Field(description="解析后的最终目标目录。")
    overwrite_policy: Literal["fail", "replace", "new_folder"] = Field(description="目标目录冲突时的处理策略。")
    progress: float = Field(default=0.0, ge=0.0, le=1.0, description="当前导出进度，范围 0~1。")
    message: str = Field(default="", description="当前导出进度说明。")
    output_manifest: ExportOutputManifest | None = Field(default=None, description="导出成功后的输出清单。")
    staging_dir: str | None = Field(default=None, description="导出执行中的 staging 目录；终态时通常为 null。")
    updated_at: datetime = Field(default_factory=_now_utc, description="作业最后更新时间。")


class ExportJobRecord(ExportJobResponse):
    created_at: datetime = Field(default_factory=_now_utc)


class ExportJobAcceptedResponse(BaseModel):
    job: ExportJobResponse = Field(description="已接受的 export job 当前状态。")


class PreviewRequest(BaseModel):
    segment_id: str | None = Field(default=None, description="要预览的段 ID。")
    edge_id: str | None = Field(default=None, description="要预览的边 ID。")
    block_id: str | None = Field(default=None, description="要预览的 block ID。")

    @model_validator(mode="after")
    def _validate_selector(self) -> "PreviewRequest":
        chosen = [self.segment_id, self.edge_id, self.block_id]
        selected_count = sum(value is not None for value in chosen)
        if selected_count != 1:
            raise ValueError("Exactly one of segment_id, edge_id, block_id must be provided.")
        return self


class PreviewResponse(BaseModel):
    preview_asset_id: str = Field(description="预览资产 ID。")
    preview_kind: Literal["segment", "edge", "block"] = Field(description="预览资产类型。")
    audio_delivery: AudioDeliveryDescriptor = Field(description="带过期时间的预览音频描述。")

    @model_validator(mode="after")
    def _validate_expiring_delivery(self) -> "PreviewResponse":
        if self.audio_delivery.expires_at is None:
            raise ValueError("PreviewResponse.audio_delivery.expires_at is required.")
        return self


class SegmentAssetResponse(BaseModel):
    render_asset_id: str = Field(description="段正式资产 ID。")
    segment_id: str = Field(description="所属段 ID。")
    render_version: int = Field(description="该资产对应的 render_version。")
    audio_delivery: AudioDeliveryDescriptor = Field(description="正式段音频的访问描述。")

    @model_validator(mode="after")
    def _validate_non_expiring_delivery(self) -> "SegmentAssetResponse":
        if self.audio_delivery.expires_at is not None:
            raise ValueError("SegmentAssetResponse.audio_delivery.expires_at must be null for formal assets.")
        return self


class BoundaryAssetResponse(BaseModel):
    boundary_asset_id: str = Field(description="边界正式资产 ID。")
    left_segment_id: str = Field(description="左侧段 ID。")
    right_segment_id: str = Field(description="右侧段 ID。")
    edge_version: int = Field(description="该资产对应的 edge_version。")
    audio_delivery: AudioDeliveryDescriptor = Field(description="正式边界音频的访问描述。")

    @model_validator(mode="after")
    def _validate_non_expiring_delivery(self) -> "BoundaryAssetResponse":
        if self.audio_delivery.expires_at is not None:
            raise ValueError("BoundaryAssetResponse.audio_delivery.expires_at must be null for formal assets.")
        return self


class BaselineSnapshotResponse(BaseModel):
    baseline_snapshot: DocumentSnapshot | None = Field(default=None, description="baseline 快照；若尚未初始化则为 null。")


class EditSessionSnapshotResponse(BaseModel):
    session_status: Literal["empty", "initializing", "ready", "failed"] = Field(default="empty", description="当前会话状态。")
    document_id: str | None = Field(default=None, description="当前活动文档 ID。")
    document_version: int | None = Field(default=None, description="当前 head 对应的版本号。")
    baseline_version: int | None = Field(default=None, description="baseline 版本号。")
    head_version: int | None = Field(default=None, description="head 版本号。")
    total_segment_count: int = Field(default=0, description="当前版本的段总数。")
    total_edge_count: int = Field(default=0, description="当前版本的边总数。")
    ready_segment_count: int = Field(default=0, description="已有正式段资产的段数量。")
    ready_block_count: int = Field(default=0, description="当前 timeline 中 ready block 数量。")
    timeline_manifest_id: str | None = Field(default=None, description="当前版本的权威 timeline manifest ID。")
    composition_manifest_id: str | None = Field(default=None, description="若当前版本已有导出 composition，则为其资产 ID。")
    composition_audio_url: str | None = Field(default=None, description="兼容整条音频地址；未导出时为 null。")
    playable_sample_span: tuple[int, int] | None = Field(default=None, description="当前版本整体可播放 sample 区间。")
    active_job: RenderJobResponse | None = Field(default=None, description="当前活动作业；若无则为 null。")
    segments: list[EditableSegmentResponse] = Field(default_factory=list, description="内联返回的段列表；大文档时可能为空。")
    edges: list[EditableEdgeResponse] = Field(default_factory=list, description="内联返回的边列表；大文档时可能为空。")


class SegmentListResponse(BaseModel):
    document_id: str = Field(description="文档 ID。")
    document_version: int = Field(description="当前版本号。")
    items: list[EditableSegmentResponse] = Field(default_factory=list, description="当前页段列表。")
    next_cursor: int | None = Field(default=None, description="下一页游标；无下一页时为 null。")


class EdgeListResponse(BaseModel):
    document_id: str = Field(description="文档 ID。")
    document_version: int = Field(description="当前版本号。")
    items: list[EditableEdgeResponse] = Field(default_factory=list, description="当前页边列表。")
    next_cursor: int | None = Field(default=None, description="下一页游标；无下一页时为 null。")
