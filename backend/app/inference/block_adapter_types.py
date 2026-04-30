from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


SegmentAlignmentMode = Literal["exact", "estimated", "block_only"]
ReusePolicy = Literal["adapter_default", "prefer_reuse", "force_full_render"]
OutputPolicy = Literal["prefer_exact", "allow_estimated", "block_only"]
JoinPolicy = Literal["natural", "preserve_pause", "prefer_enhanced"]
SegmentOutputSource = Literal["adapter_exact", "system_estimated", "unavailable"]
SpanPrecision = Literal["exact", "estimated"]


class BlockRequestSegment(BaseModel):
    segment_id: str = Field(description="段 ID。")
    order_key: int = Field(description="段排序键。")
    text: str = Field(description="该段输入文本。")
    language: str = Field(description="该段语言。")
    terminal_punctuation: str = Field(default="", description="可选句尾标点。")
    voice_binding_id: str | None = Field(default=None, description="可选 voice binding ID。")
    render_profile_id: str | None = Field(default=None, description="可选 render profile ID。")
    resolved_binding: dict[str, Any] | None = Field(default=None, description="段级兼容 binding 视图。")
    resolved_model_binding: dict[str, Any] | None = Field(default=None, description="段级解析模型绑定。")
    resolved_reference: dict[str, Any] | None = Field(default=None, description="段级解析参考。")


class BlockRequestBlock(BaseModel):
    block_id: str = Field(description="当前 block ID。")
    segment_ids: list[str] = Field(default_factory=list, description="当前 block 内段 ID 顺序。")
    start_order_key: int = Field(description="block 起始排序键。")
    end_order_key: int = Field(description="block 结束排序键。")
    estimated_sample_count: int = Field(default=0, ge=0, description="估算 sample 数。")
    segments: list[BlockRequestSegment] = Field(default_factory=list, description="block 内段结构。")
    block_text: str = Field(description="稳定生成的 block 合并文本。")

    @model_validator(mode="after")
    def _validate_segment_identity(self) -> "BlockRequestBlock":
        if self.segment_ids and self.segments:
            ordered_ids = [segment.segment_id for segment in self.segments]
            if ordered_ids != self.segment_ids:
                raise ValueError("BlockRequestBlock.segment_ids must match segments order.")
        return self


class ResolvedModelBinding(BaseModel):
    adapter_id: str = Field(description="目标 adapter ID。")
    model_instance_id: str = Field(description="注册模型实例 ID。")
    preset_id: str = Field(description="目标 preset ID。")
    resolved_assets: dict[str, Any] = Field(default_factory=dict, description="adapter 可消费资产映射。")
    resolved_reference: dict[str, Any] | None = Field(default=None, description="解析后的最终参考。")
    resolved_parameters: dict[str, Any] = Field(default_factory=dict, description="解析后的稳定参数。")
    secret_handles: dict[str, str] = Field(default_factory=dict, description="secret store handle 映射。")
    binding_fingerprint: str = Field(description="模型绑定指纹。")


class EdgeControl(BaseModel):
    edge_id: str = Field(description="边 ID。")
    left_segment_id: str = Field(description="左段 ID。")
    right_segment_id: str = Field(description="右段 ID。")
    pause_duration_seconds: float = Field(default=0.0, ge=0.0, description="段间停顿秒数。")
    join_policy_override: JoinPolicy | None = Field(default=None, description="可选 join policy 覆盖。")
    locked: bool = Field(default=False, description="当前边是否锁定。")


class DirtyContext(BaseModel):
    dirty_segment_ids: list[str] = Field(default_factory=list, description="当前 block 脏段列表。")
    dirty_edge_ids: list[str] = Field(default_factory=list, description="当前 block 脏边列表。")
    previous_block_asset_id: str | None = Field(default=None, description="上一次 block 资产 ID。")
    reuse_policy: ReusePolicy = Field(default="adapter_default", description="局部复用策略。")


class BlockPolicy(BaseModel):
    min_block_seconds: int = Field(default=20, ge=1, description="默认 block 最小时长。")
    max_block_seconds: int = Field(default=40, ge=1, description="默认 block 最大时长。")
    max_segment_count: int = Field(default=50, ge=1, description="默认 block 最大段数。")

    @model_validator(mode="after")
    def _validate_window(self) -> "BlockPolicy":
        if self.max_block_seconds < self.min_block_seconds:
            raise ValueError("BlockPolicy.max_block_seconds must be >= min_block_seconds.")
        return self


class AdapterCapabilities(BaseModel):
    block_render: bool = Field(default=True, description="所有 adapter 的基础能力。")
    exact_segment_output: bool = Field(default=False, description="是否支持精确段级输出。")
    estimated_segment_output: bool = Field(default=False, description="是否支持估算段级定位。")
    segment_level_voice_binding: bool = Field(default=False, description="是否支持同 block 段级 binding。")
    incremental_render: bool = Field(default=False, description="是否支持 block 内局部复用。")
    boundary_enhancement: bool = Field(default=False, description="是否支持边界增强。")
    native_join_fusion: bool = Field(default=False, description="是否支持原生 join 融合。")
    streaming_progress: bool = Field(default=False, description="是否支持流式进度。")
    cancellable: bool = Field(default=False, description="是否支持取消。")
    bounded_concurrency: bool = Field(default=False, description="是否声明并发上限。")
    local_gpu_runtime: bool = Field(default=False, description="是否是本地 GPU runtime。")
    external_http_api: bool = Field(default=False, description="是否走外部 HTTP API。")
    remote_runtime: bool = Field(default=False, description="是否走远端 runtime。")


class SegmentSpan(BaseModel):
    segment_id: str = Field(description="段 ID。")
    sample_start: int = Field(ge=0, description="起始 sample。")
    sample_end: int = Field(ge=0, description="结束 sample。")
    precision: SpanPrecision = Field(description="sample span 精度。")
    confidence: float | None = Field(default=None, ge=0.0, le=1.0, description="估算置信度。")
    source: str | None = Field(default=None, description="span 来源。")

    @model_validator(mode="after")
    def _validate_span(self) -> "SegmentSpan":
        if self.sample_end <= self.sample_start:
            raise ValueError("SegmentSpan.sample_end must be greater than sample_start.")
        if self.precision == "estimated" and (self.confidence is None or not self.source):
            raise ValueError("Estimated SegmentSpan requires confidence and source.")
        return self


class JoinReport(BaseModel):
    requested_policy: JoinPolicy = Field(description="请求的 join policy。")
    applied_mode: JoinPolicy = Field(description="实际采用的 join mode。")
    enhancement_applied: bool = Field(default=False, description="是否应用了增强。")
    implementation: str | None = Field(default=None, description="仅供诊断的实现名。")


class SegmentOutput(BaseModel):
    segment_id: str = Field(description="段 ID。")
    audio: list[float] | None = Field(default=None, description="可选独立段音频。")
    sample_span: SegmentSpan | None = Field(default=None, description="该段 sample span。")
    confidence: float | None = Field(default=None, ge=0.0, le=1.0, description="结果置信度。")
    source: SegmentOutputSource = Field(default="unavailable", description="段级输出来源。")

    @model_validator(mode="after")
    def _validate_source(self) -> "SegmentOutput":
        if self.source == "adapter_exact":
            if self.sample_span is None or self.sample_span.precision != "exact":
                raise ValueError("adapter_exact SegmentOutput requires an exact sample_span.")
        if self.source == "system_estimated":
            if self.sample_span is None or self.sample_span.precision != "estimated" or self.confidence is None:
                raise ValueError("system_estimated SegmentOutput requires estimated span and confidence.")
        if self.source == "unavailable" and (self.audio is not None or self.sample_span is not None):
            raise ValueError("unavailable SegmentOutput must not carry audio or sample_span.")
        return self


class BlockRenderRequest(BaseModel):
    request_id: str = Field(description="标准请求 ID。")
    document_id: str = Field(description="所属文档 ID。")
    block: BlockRequestBlock = Field(description="当前 block 结构。")
    model_binding: ResolvedModelBinding = Field(description="规范模型选择字段。")
    voice: dict[str, Any] = Field(default_factory=dict, description="迁移期兼容 voice 视图。")
    model: dict[str, Any] = Field(default_factory=dict, description="迁移期兼容 model 视图。")
    reference: dict[str, Any] = Field(default_factory=dict, description="迁移期兼容 reference 视图。")
    synthesis: dict[str, Any] = Field(default_factory=dict, description="跨模型稳定合成参数。")
    output_policy: OutputPolicy = Field(default="prefer_exact", description="上层期望的输出粒度。")
    join_policy: JoinPolicy = Field(default="natural", description="块内衔接意图。")
    edge_controls: list[EdgeControl] = Field(default_factory=list, description="段间控制输入。")
    dirty_context: DirtyContext | None = Field(default=None, description="当前 block 的脏范围提示。")
    adapter_options: dict[str, dict[str, Any]] = Field(default_factory=dict, description="adapter 私有扩展区。")
    block_policy: BlockPolicy = Field(default_factory=BlockPolicy, description="当前 block policy。")
    block_policy_version: str = Field(default="v1", description="block policy 版本。")


class BlockRenderResult(BaseModel):
    block_id: str = Field(description="对应 block ID。")
    segment_ids: list[str] = Field(default_factory=list, description="结果对应的段顺序。")
    sample_rate: int = Field(gt=0, description="结果采样率。")
    audio: list[float] = Field(default_factory=list, description="完整 block 音频采样。")
    audio_sample_count: int = Field(ge=0, description="完整 block 音频 sample 数。")
    segment_alignment_mode: SegmentAlignmentMode = Field(description="段级定位精度。")
    segment_outputs: list[SegmentOutput] = Field(default_factory=list, description="可选段级独立结果。")
    segment_spans: list[SegmentSpan] = Field(default_factory=list, description="可选段级 sample span。")
    join_report: JoinReport | None = Field(default=None, description="可选衔接摘要。")
    adapter_trace: dict[str, Any] | None = Field(default=None, description="可选 adapter trace。")
    diagnostics: dict[str, Any] = Field(default_factory=dict, description="可选诊断信息。")

    @model_validator(mode="after")
    def _validate_alignment(self) -> "BlockRenderResult":
        if self.audio_sample_count != len(self.audio):
            raise ValueError("BlockRenderResult.audio_sample_count must match audio length.")

        span_ids = [span.segment_id for span in self.segment_spans]
        if any(span.sample_end > self.audio_sample_count for span in self.segment_spans):
            raise ValueError("SegmentSpan must stay within block audio_sample_count.")

        if self.segment_alignment_mode == "exact":
            expected_ids = set(self.segment_ids)
            if not expected_ids or set(span_ids) != expected_ids:
                raise ValueError("exact BlockRenderResult requires exact segment_spans for every segment.")
            if any(span.precision != "exact" for span in self.segment_spans):
                raise ValueError("exact BlockRenderResult cannot contain estimated segment spans.")

        if self.segment_alignment_mode == "estimated":
            if any(span.precision != "estimated" for span in self.segment_spans):
                raise ValueError("estimated BlockRenderResult must use estimated segment spans only.")

        if self.segment_alignment_mode == "block_only":
            if self.segment_spans:
                raise ValueError("block_only BlockRenderResult must not fabricate segment spans.")
            if any(output.source != "unavailable" for output in self.segment_outputs):
                raise ValueError("block_only BlockRenderResult must not expose segment outputs.")

        return self
