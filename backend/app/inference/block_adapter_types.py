from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


SegmentAlignmentMode = Literal["exact", "estimated", "block_only"]
ReusePolicy = Literal["adapter_default", "prefer_reuse", "force_full_render"]
OutputPolicy = Literal["prefer_exact", "allow_estimated", "block_only"]
JoinPolicy = Literal["natural", "preserve_pause", "prefer_enhanced"]
SegmentOutputSource = Literal["adapter_exact", "system_estimated", "unavailable"]
SpanPrecision = Literal["exact", "estimated"]
BoundaryRenderMode = Literal["enhanced", "fallback", "none"]
RenderScope = Literal["segment", "block"]
ScopeReasonCode = Literal[
    "boundary_context_incomplete",
    "neighbor_asset_not_reusable",
    "segment_scope_identity_conflict",
    "required_neighbor_missing",
    "block_scope_not_supported",
    "invalid_request_topology",
]


class ScopeUnsupported(RuntimeError):
    def __init__(
        self,
        *,
        scope: RenderScope,
        reason_code: ScopeReasonCode,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.scope = scope
        self.reason_code = reason_code
        self.details = details or {}


class SegmentScopeUnsupported(ScopeUnsupported):
    def __init__(
        self,
        *,
        reason_code: ScopeReasonCode,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(scope="segment", reason_code=reason_code, message=message, details=details)


class BlockScopeUnsupported(ScopeUnsupported):
    def __init__(
        self,
        *,
        reason_code: ScopeReasonCode,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(scope="block", reason_code=reason_code, message=message, details=details)


class BlockRequestSegment(BaseModel):
    segment_id: str = Field(description="段 ID。")
    order_key: int = Field(description="段排序键。")
    text: str = Field(description="该段输入文本。")
    language: str = Field(description="该段语言。")
    terminal_punctuation: str = Field(default="", description="可选句尾标点。")
    voice_binding_id: str | None = Field(default=None, description="可选 voice binding ID。")
    render_profile_id: str | None = Field(default=None, description="可选 render profile ID。")
    render_version: int = Field(default=0, description="该段当前已解析的 render_version。")
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
    preset_defaults: dict[str, Any] = Field(default_factory=dict, description="preset 默认字段。")
    secret_handles: dict[str, str] = Field(default_factory=dict, description="secret store handle 映射。")
    endpoint: dict[str, Any] | None = Field(default=None, description="外部 provider endpoint 配置。")
    account_binding: dict[str, Any] = Field(default_factory=dict, description="外部 provider 非 secret 账号绑定。")
    preset_fixed_fields: dict[str, Any] = Field(default_factory=dict, description="preset 固定字段。")
    adapter_options: dict[str, Any] = Field(default_factory=dict, description="adapter 运行时选项。")
    binding_fingerprint: str = Field(description="模型绑定指纹。")


class EdgeControl(BaseModel):
    edge_id: str = Field(description="边 ID。")
    left_segment_id: str = Field(description="左段 ID。")
    right_segment_id: str = Field(description="右段 ID。")
    pause_duration_seconds: float = Field(default=0.0, ge=0.0, description="段间停顿秒数。")
    join_policy_override: JoinPolicy | None = Field(default=None, description="可选 join policy 覆盖。")
    locked: bool = Field(default=False, description="当前边是否锁定。")


class BoundaryContext(BaseModel):
    edge_id: str = Field(description="边 ID。")
    left_segment_id: str = Field(description="左段 ID。")
    right_segment_id: str = Field(description="右段 ID。")
    pause_duration_seconds: float = Field(default=0.0, ge=0.0, description="段间停顿秒数。")
    requested_boundary_strategy: str = Field(description="调用方请求的边界策略。")
    join_policy: JoinPolicy = Field(description="该边上下文对应的 join 意图。")
    locked: bool = Field(default=False, description="该边策略是否锁定。")


class ReusableSourceAssetDescriptor(BaseModel):
    segment_id: str = Field(description="段 ID。")
    render_asset_id: str | None = Field(default=None, description="当前可直接读取的正式段资产 ID。")
    base_render_asset_id: str | None = Field(default=None, description="后续局部推理可复用的 source/base 资产 ID。")
    render_version: int = Field(default=0, description="该段当前 render_version。")


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
    supports_exact_alignment: bool = Field(default=False, description="是否显式支持 exact 对齐。")
    supports_estimated_alignment: bool = Field(default=False, description="是否显式支持 estimated 对齐。")
    supports_block_only_alignment: bool = Field(default=False, description="是否显式支持 block_only 对齐。")
    supports_boundary_enhancement: bool = Field(default=False, description="是否显式支持边界增强。")
    supports_incremental_render: bool = Field(default=False, description="是否显式支持增量复用。")
    supports_segment_level_voice_binding: bool = Field(default=False, description="是否显式支持段级 voice binding。")
    supports_pause_only_compose: bool = Field(default=False, description="是否支持 pause-only formal block compose。")
    supports_cancellation: bool = Field(default=False, description="是否显式支持取消。")

    @model_validator(mode="after")
    def _hydrate_v1_capabilities(self) -> "AdapterCapabilities":
        if self.exact_segment_output:
            self.supports_exact_alignment = True
        if self.estimated_segment_output:
            self.supports_estimated_alignment = True
        if self.boundary_enhancement:
            self.supports_boundary_enhancement = True
        if self.incremental_render:
            self.supports_incremental_render = True
        if self.segment_level_voice_binding:
            self.supports_segment_level_voice_binding = True
        if self.cancellable:
            self.supports_cancellation = True
        if self.block_render:
            self.supports_block_only_alignment = True
        if self.native_join_fusion:
            self.supports_pause_only_compose = True

        if self.supports_exact_alignment:
            self.exact_segment_output = True
        if self.supports_estimated_alignment:
            self.estimated_segment_output = True
        if self.supports_boundary_enhancement:
            self.boundary_enhancement = True
        if self.supports_incremental_render:
            self.incremental_render = True
        if self.supports_segment_level_voice_binding:
            self.segment_level_voice_binding = True
        if self.supports_cancellation:
            self.cancellable = True
        return self


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


class AllowedDegradationPolicy(BaseModel):
    requested_mode: SegmentAlignmentMode = Field(default="exact", description="调用方理想结果精度。")
    allowed_modes: list[SegmentAlignmentMode] = Field(default_factory=lambda: ["exact"], description="允许 adapter 返回的降级精度列表。")

    @model_validator(mode="after")
    def _validate_requested_mode(self) -> "AllowedDegradationPolicy":
        if self.requested_mode not in self.allowed_modes:
            self.allowed_modes = [self.requested_mode, *[mode for mode in self.allowed_modes if mode != self.requested_mode]]
        return self


class AllowedScopeEscalationPolicy(BaseModel):
    requested_scope: RenderScope = Field(default="block", description="调用方首选执行范围。")
    allowed_scopes: list[RenderScope] = Field(default_factory=lambda: ["block"], description="允许 adapter 升级到的作用域。")

    @model_validator(mode="after")
    def _validate_requested_scope(self) -> "AllowedScopeEscalationPolicy":
        if self.requested_scope not in self.allowed_scopes:
            self.allowed_scopes = [self.requested_scope, *[scope for scope in self.allowed_scopes if scope != self.requested_scope]]
        return self


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
    execution_unit_id: str = Field(default="", description="本次 adapter 执行单元 ID。")
    formal_block_id: str = Field(default="", description="该执行单元最终归属的 formal block ID。")
    render_scope: RenderScope = Field(default="block", description="当前请求的渲染作用域。")
    escalated_from_scope: RenderScope | None = Field(default=None, description="若当前请求由更小作用域升级而来，则记录来源。")
    block: BlockRequestBlock = Field(description="当前 block 结构。")
    model_binding: ResolvedModelBinding = Field(description="规范模型选择字段。")
    voice: dict[str, Any] = Field(default_factory=dict, description="迁移期兼容 voice 视图。")
    model: dict[str, Any] = Field(default_factory=dict, description="迁移期兼容 model 视图。")
    reference: dict[str, Any] = Field(default_factory=dict, description="迁移期兼容 reference 视图。")
    synthesis: dict[str, Any] = Field(default_factory=dict, description="跨模型稳定合成参数。")
    output_policy: OutputPolicy = Field(default="prefer_exact", description="上层期望的输出粒度。")
    requested_alignment_mode: SegmentAlignmentMode = Field(default="exact", description="显式请求的对齐精度。")
    join_policy: JoinPolicy = Field(default="natural", description="块内衔接意图。")
    requested_join_policy: JoinPolicy | None = Field(default=None, description="调用方请求的 join policy。")
    effective_join_policy: JoinPolicy | None = Field(default=None, description="当前 scope 实际执行的 join policy。")
    edge_controls: list[EdgeControl] = Field(default_factory=list, description="段间控制输入。")
    boundary_contexts: list[BoundaryContext] = Field(default_factory=list, description="主后端显式整理后的边界上下文。")
    reusable_source_assets: list[ReusableSourceAssetDescriptor] = Field(default_factory=list, description="当前 execution unit 可复用的 source/base 资产描述。")
    dirty_context: DirtyContext | None = Field(default=None, description="当前 block 的脏范围提示。")
    resolved_reference: dict[str, Any] = Field(default_factory=dict, description="adapter 直接消费的最终参考上下文。")
    resolved_parameters: dict[str, Any] = Field(default_factory=dict, description="adapter 直接消费的最终稳定参数。")
    allowed_degradation: AllowedDegradationPolicy = Field(default_factory=AllowedDegradationPolicy, description="允许的结果降级策略。")
    allowed_scope_escalation: AllowedScopeEscalationPolicy = Field(default_factory=AllowedScopeEscalationPolicy, description="允许的执行范围升级策略。")
    adapter_options: dict[str, dict[str, Any]] = Field(default_factory=dict, description="adapter 私有扩展区。")
    block_policy: BlockPolicy = Field(default_factory=BlockPolicy, description="当前 block policy。")
    block_policy_version: str = Field(default="v1", description="block policy 版本。")

    @model_validator(mode="after")
    def _hydrate_join_policy_protocol(self) -> "BlockRenderRequest":
        if not self.execution_unit_id:
            self.execution_unit_id = self.request_id
        if not self.formal_block_id:
            self.formal_block_id = self.block.block_id
        if self.requested_join_policy is None:
            self.requested_join_policy = self.join_policy
        if self.effective_join_policy is None:
            self.effective_join_policy = self.join_policy
        if not self.resolved_reference:
            self.resolved_reference = dict(self.model_binding.resolved_reference or {})
        if not self.resolved_parameters:
            self.resolved_parameters = dict(self.model_binding.resolved_parameters)
        if not self.boundary_contexts:
            self.boundary_contexts = [
                BoundaryContext(
                    edge_id=edge_control.edge_id,
                    left_segment_id=edge_control.left_segment_id,
                    right_segment_id=edge_control.right_segment_id,
                    pause_duration_seconds=edge_control.pause_duration_seconds,
                    requested_boundary_strategy=edge_control.join_policy_override or self.join_policy,
                    join_policy=edge_control.join_policy_override or self.join_policy,
                    locked=edge_control.locked,
                )
                for edge_control in self.edge_controls
            ]
        if not self.allowed_degradation.allowed_modes:
            self.allowed_degradation = AllowedDegradationPolicy(requested_mode=self.requested_alignment_mode, allowed_modes=[self.requested_alignment_mode])
        if self.allowed_scope_escalation.requested_scope != self.render_scope:
            self.allowed_scope_escalation.requested_scope = self.render_scope
        if not self.allowed_scope_escalation.allowed_scopes:
            self.allowed_scope_escalation.allowed_scopes = [self.render_scope]
        return self


class AudioResult(BaseModel):
    sample_rate: int = Field(gt=0, description="结果采样率。")
    audio: list[float] = Field(default_factory=list, description="完整 block 音频采样。")
    audio_sample_count: int = Field(ge=0, description="完整 block 音频 sample 数。")

    @model_validator(mode="after")
    def _validate_audio(self) -> "AudioResult":
        if self.audio_sample_count != len(self.audio):
            raise ValueError("AudioResult.audio_sample_count must match audio length.")
        return self


class SegmentAlignmentResult(BaseModel):
    mode: SegmentAlignmentMode = Field(description="实际返回的对齐精度。")
    spans: list[SegmentSpan] = Field(default_factory=list, description="段级 sample span。")
    precision_reason: str | None = Field(default=None, description="对齐精度原因。")


class BoundaryResult(BaseModel):
    edge_id: str = Field(description="边 ID。")
    mode: BoundaryRenderMode = Field(description="该边界的实际处理模式。")
    sample_span: tuple[int, int] | None = Field(default=None, description="边界样本区间；未知时可为空。")
    diagnostics: dict[str, Any] = Field(default_factory=dict, description="边界相关诊断信息。")


class DegradationReport(BaseModel):
    requested_mode: SegmentAlignmentMode = Field(description="请求的目标精度。")
    delivered_mode: SegmentAlignmentMode = Field(description="最终返回的精度。")
    reasons: list[str] = Field(default_factory=list, description="降级或保持原因。")


class ScopeFeedback(BaseModel):
    requested_scope: RenderScope = Field(description="请求的执行范围。")
    actual_scope: RenderScope = Field(description="本次实际执行范围。")
    escalated_from_scope: RenderScope | None = Field(default=None, description="若由更小 scope 升级而来，则记录来源。")
    reason_code: ScopeReasonCode | None = Field(default=None, description="scope 反馈原因码。")
    details: dict[str, Any] = Field(default_factory=dict, description="附加 scope 诊断。")


class BlockRenderResult(BaseModel):
    block_id: str = Field(description="对应 block ID。")
    segment_ids: list[str] = Field(default_factory=list, description="结果对应的段顺序。")
    sample_rate: int = Field(gt=0, description="结果采样率。")
    audio: list[float] = Field(default_factory=list, description="完整 block 音频采样。")
    audio_sample_count: int = Field(ge=0, description="完整 block 音频 sample 数。")
    segment_alignment_mode: SegmentAlignmentMode = Field(description="段级定位精度。")
    segment_outputs: list[SegmentOutput] = Field(default_factory=list, description="可选段级独立结果。")
    segment_spans: list[SegmentSpan] = Field(default_factory=list, description="可选段级 sample span。")
    audio_result: AudioResult | None = Field(default=None, description="标准化音频结果。")
    segment_alignment_result: SegmentAlignmentResult | None = Field(default=None, description="标准化对齐结果。")
    boundary_results: list[BoundaryResult] = Field(default_factory=list, description="边界处理结果。")
    degradation_report: DegradationReport | None = Field(default=None, description="结果降级报告。")
    scope_feedback: ScopeFeedback | None = Field(default=None, description="执行范围反馈。")
    join_report: JoinReport | None = Field(default=None, description="可选衔接摘要。")
    adapter_trace: dict[str, Any] | None = Field(default=None, description="可选 adapter trace。")
    diagnostics: dict[str, Any] = Field(default_factory=dict, description="可选诊断信息。")

    @model_validator(mode="after")
    def _validate_alignment(self) -> "BlockRenderResult":
        if self.audio_result is None:
            self.audio_result = AudioResult(
                sample_rate=self.sample_rate,
                audio=self.audio,
                audio_sample_count=self.audio_sample_count,
            )
        if self.segment_alignment_result is None:
            self.segment_alignment_result = SegmentAlignmentResult(
                mode=self.segment_alignment_mode,
                spans=self.segment_spans,
                precision_reason="adapter_exact"
                if self.segment_alignment_mode == "exact"
                else ("block_only_alignment" if self.segment_alignment_mode == "block_only" else "estimated_alignment"),
            )
        if self.degradation_report is None:
            reasons: list[str] = []
            if self.segment_alignment_mode != "exact":
                reasons.append("alignment_mode_degraded")
            self.degradation_report = DegradationReport(
                requested_mode="exact",
                delivered_mode=self.segment_alignment_mode,
                reasons=reasons,
            )
        if self.scope_feedback is None:
            self.scope_feedback = ScopeFeedback(
                requested_scope="block",
                actual_scope="block",
            )

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
