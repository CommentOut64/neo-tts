from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Callable, Protocol

from backend.app.inference.block_adapter_types import (
    AdapterCapabilities,
    BlockRenderRequest,
    BlockRenderResult,
    JoinReport,
    ResolvedModelBinding,
    SegmentOutput,
    SegmentSpan,
)
from backend.app.inference.editable_types import (
    BlockCompositionAssetPayload,
    ResolvedRenderContext,
    ResolvedVoiceBinding,
    SegmentRenderAssetPayload,
)
from backend.app.schemas.edit_session import EditableEdge, EditableSegment
from backend.app.services.composition_builder import CompositionBuilder


class EditableGatewayLike(Protocol):
    def build_reference_context(
        self,
        resolved_context: ResolvedRenderContext,
        *,
        progress_callback: Callable[[dict], None] | None = None,
    ) -> Any: ...

    def render_segment_base(
        self,
        segment: EditableSegment,
        context: Any,
        *,
        progress_callback: Callable[[dict], None] | None = None,
    ) -> SegmentRenderAssetPayload: ...

    def render_boundary_asset(
        self,
        left_asset: SegmentRenderAssetPayload,
        right_asset: SegmentRenderAssetPayload,
        edge: EditableEdge,
        context: Any,
    ) -> Any: ...


class ReusableAssetAccessorLike(Protocol):
    def load_block_asset(self, block_asset_id: str) -> BlockCompositionAssetPayload: ...

    def load_segment_asset(self, render_asset_id: str) -> SegmentRenderAssetPayload: ...


@dataclass(frozen=True)
class _PreparedSegment:
    request_segment: Any
    model_binding: ResolvedModelBinding
    voice_binding: dict[str, Any]
    reference: dict[str, Any]


class GPTSoVITSLocalAdapter:
    def __init__(
        self,
        *,
        editable_gateway: EditableGatewayLike,
        composition_builder: CompositionBuilder | None = None,
        reusable_asset_accessor: ReusableAssetAccessorLike | None = None,
        cancellation_checker: Callable[[], bool] | None = None,
    ) -> None:
        self._editable_gateway = editable_gateway
        self._composition_builder = composition_builder or CompositionBuilder()
        self._reusable_asset_accessor = reusable_asset_accessor
        self._cancellation_checker = cancellation_checker

    @staticmethod
    def capabilities() -> AdapterCapabilities:
        return AdapterCapabilities(
            block_render=True,
            exact_segment_output=True,
            segment_level_voice_binding=True,
            incremental_render=True,
            boundary_enhancement=True,
            native_join_fusion=True,
            local_gpu_runtime=True,
            cancellable=True,
        )

    def render_block(self, request: BlockRenderRequest) -> BlockRenderResult:
        self._raise_if_cancelled()
        prepared_segments = [self._prepare_segment(segment) for segment in request.block.segments]
        reusable_assets = self._load_reusable_assets(request=request, prepared_segments=prepared_segments)
        contexts: dict[str, Any] = {}
        segment_assets: list[SegmentRenderAssetPayload] = []
        adapter_trace_segments: dict[str, dict[str, Any] | None] = {}
        reused_segment_ids: list[str] = []

        dirty_segment_ids = set(request.dirty_context.dirty_segment_ids) if request.dirty_context is not None else set()
        for prepared in prepared_segments:
            self._raise_if_cancelled()
            reused_asset = reusable_assets.get(prepared.request_segment.segment_id)
            if reused_asset is not None:
                segment_assets.append(reused_asset)
                reused_segment_ids.append(prepared.request_segment.segment_id)
                adapter_trace_segments[prepared.request_segment.segment_id] = reused_asset.trace
                continue
            context_key = self._build_context_cache_key(prepared)
            context = contexts.get(context_key)
            if context is None:
                context = self._editable_gateway.build_reference_context(self._build_resolved_render_context(prepared))
                contexts[context_key] = context
            asset = self._editable_gateway.render_segment_base(
                self._build_editable_segment(
                    prepared.request_segment,
                    render_version=prepared.request_segment.render_version,
                ),
                context,
            )
            segment_assets.append(asset)
            adapter_trace_segments[prepared.request_segment.segment_id] = asset.trace

        boundaries: list[Any] = []
        adapter_trace_boundaries: dict[str, dict[str, Any] | None] = {}
        join_downgrade_reasons: dict[str, str] = {}
        enhancement_applied = False
        applied_join_mode = request.join_policy
        segment_asset_by_id = {asset.segment_id: asset for asset in segment_assets}
        for edge_control in request.edge_controls:
            self._raise_if_cancelled()
            left = next(item for item in prepared_segments if item.request_segment.segment_id == edge_control.left_segment_id)
            right = next(item for item in prepared_segments if item.request_segment.segment_id == edge_control.right_segment_id)
            if self._should_render_enhanced_boundary(request=request, left=left, right=right, edge_control=edge_control):
                context = contexts[self._build_context_cache_key(left)]
                edge = self._build_editable_edge(
                    edge_control=edge_control,
                    boundary_strategy="latent_overlap_then_equal_power_crossfade",
                )
                boundary = self._editable_gateway.render_boundary_asset(
                    segment_asset_by_id[left.request_segment.segment_id],
                    segment_asset_by_id[right.request_segment.segment_id],
                    edge,
                    context,
                )
                boundaries.append(boundary)
                enhancement_applied = True
                adapter_trace_boundaries[edge_control.edge_id] = getattr(boundary, "trace", None)
                continue
            if request.join_policy == "prefer_enhanced" or edge_control.join_policy_override == "prefer_enhanced":
                applied_join_mode = "preserve_pause"
                join_downgrade_reasons[edge_control.edge_id] = "binding_or_reference_mismatch"

        block_asset = self._composition_builder.compose_block(
            segments=segment_assets,
            boundaries=boundaries,
            edges=[self._build_editable_edge(edge_control=edge_control) for edge_control in request.edge_controls],
            block_id=request.block.block_id,
            segment_alignment_mode="exact",
            join_report_summary={
                "requested_policy": request.join_policy,
                "applied_mode": applied_join_mode,
                "enhancement_applied": enhancement_applied,
            },
        )
        segment_spans = self._build_exact_segment_spans(block_asset)
        return BlockRenderResult(
            block_id=request.block.block_id,
            segment_ids=[segment.segment_id for segment in request.block.segments],
            sample_rate=block_asset.sample_rate,
            audio=block_asset.audio.astype(float, copy=False).tolist(),
            audio_sample_count=block_asset.audio_sample_count,
            segment_alignment_mode="exact",
            segment_outputs=[
                SegmentOutput(
                    segment_id=span.segment_id,
                    sample_span=span,
                    source="adapter_exact",
                )
                for span in segment_spans
            ],
            segment_spans=segment_spans,
            join_report=JoinReport(
                requested_policy=request.join_policy,
                applied_mode=applied_join_mode,
                enhancement_applied=enhancement_applied,
                implementation="gpt_sovits_local_adapter",
            ),
            adapter_trace={
                "segments": adapter_trace_segments,
                "boundaries": adapter_trace_boundaries,
                "reused_segment_ids": reused_segment_ids,
            },
            diagnostics={
                "join_downgrade_reasons": join_downgrade_reasons,
            },
        )

    def _load_reusable_assets(
        self,
        *,
        request: BlockRenderRequest,
        prepared_segments: list[_PreparedSegment],
    ) -> dict[str, SegmentRenderAssetPayload]:
        dirty_context = request.dirty_context
        if (
            dirty_context is None
            or dirty_context.reuse_policy != "prefer_reuse"
            or not dirty_context.previous_block_asset_id
            or self._reusable_asset_accessor is None
            or self._requires_full_rerender_for_reuse(prepared_segments)
        ):
            return {}

        previous_block = self._reusable_asset_accessor.load_block_asset(dirty_context.previous_block_asset_id)
        previous_entries = {entry.segment_id: entry for entry in previous_block.segment_entries}
        dirty_segment_ids = set(dirty_context.dirty_segment_ids)
        reusable_assets: dict[str, SegmentRenderAssetPayload] = {}
        for prepared in prepared_segments:
            segment_id = prepared.request_segment.segment_id
            if segment_id in dirty_segment_ids:
                continue
            entry = previous_entries.get(segment_id)
            if entry is None or not entry.render_asset_id:
                continue
            reusable_assets[segment_id] = self._reusable_asset_accessor.load_segment_asset(entry.render_asset_id)
        return reusable_assets

    @staticmethod
    def _requires_full_rerender_for_reuse(prepared_segments: list[_PreparedSegment]) -> bool:
        identity_keys = {
            (
                prepared.model_binding.binding_fingerprint,
                str(prepared.reference.get("fingerprint") or ""),
            )
            for prepared in prepared_segments
        }
        return len(identity_keys) > 1

    @staticmethod
    def _prepare_segment(segment: Any) -> _PreparedSegment:
        model_binding_payload = segment.resolved_model_binding or {}
        model_binding = ResolvedModelBinding.model_validate(model_binding_payload)
        voice_binding = dict(segment.resolved_binding or {})
        reference = dict(segment.resolved_reference or model_binding.resolved_reference or {})
        return _PreparedSegment(
            request_segment=segment,
            model_binding=model_binding,
            voice_binding=voice_binding,
            reference=reference,
        )

    @staticmethod
    def _build_context_cache_key(prepared: _PreparedSegment) -> str:
        payload = {
            "binding_fingerprint": prepared.model_binding.binding_fingerprint,
            "reference": prepared.reference,
            "parameters": prepared.model_binding.resolved_parameters,
        }
        return json.dumps(payload, ensure_ascii=True, sort_keys=True)

    @staticmethod
    def _build_resolved_render_context(prepared: _PreparedSegment) -> ResolvedRenderContext:
        parameters = dict(prepared.model_binding.resolved_parameters)
        reference = dict(prepared.reference)
        voice_binding = dict(prepared.voice_binding)
        return ResolvedRenderContext(
            voice_id=str(voice_binding.get("voice_id") or ""),
            model_key=str(voice_binding.get("model_key") or prepared.model_binding.model_instance_id),
            reference_audio_path=str(reference.get("audio_uri") or ""),
            reference_text=str(reference.get("text") or ""),
            reference_language=str(reference.get("language") or ""),
            reference_scope=str(reference.get("source") or ""),
            reference_identity=str(reference.get("reference_id") or ""),
            reference_audio_fingerprint=str(reference.get("fingerprint") or ""),
            reference_text_fingerprint="",
            speed=float(parameters.get("speed", 1.0)),
            top_k=int(parameters.get("top_k", 15)),
            top_p=float(parameters.get("top_p", 1.0)),
            temperature=float(parameters.get("temperature", 1.0)),
            noise_scale=float(parameters.get("noise_scale", 0.35)),
            resolved_voice_binding=ResolvedVoiceBinding(
                voice_binding_id=str(voice_binding.get("voice_binding_id") or ""),
                voice_id=str(voice_binding.get("voice_id") or ""),
                model_key=str(voice_binding.get("model_key") or prepared.model_binding.model_instance_id),
                adapter_id=prepared.model_binding.adapter_id,
                model_instance_id=prepared.model_binding.model_instance_id,
                preset_id=prepared.model_binding.preset_id,
                binding_fingerprint=prepared.model_binding.binding_fingerprint,
                gpt_path=GPTSoVITSLocalAdapter._resolve_asset_path(prepared.model_binding.resolved_assets.get("gpt_weight")),
                sovits_path=GPTSoVITSLocalAdapter._resolve_asset_path(prepared.model_binding.resolved_assets.get("sovits_weight")),
            ),
            render_profile_id=str(prepared.request_segment.render_profile_id or ""),
            render_profile_fingerprint=prepared.model_binding.binding_fingerprint,
        )

    @staticmethod
    def _resolve_asset_path(raw_asset: Any) -> str | None:
        if raw_asset is None:
            return None
        if isinstance(raw_asset, str):
            return raw_asset
        if isinstance(raw_asset, dict):
            for key in ("source_path", "path", "relative_path"):
                value = raw_asset.get(key)
                if isinstance(value, str) and value.strip():
                    return value
        return None

    @staticmethod
    def _build_editable_segment(request_segment: Any, *, render_version: int) -> EditableSegment:
        return EditableSegment(
            segment_id=request_segment.segment_id,
            document_id="block-render-request",
            order_key=request_segment.order_key,
            stem=request_segment.text.removesuffix(request_segment.terminal_punctuation or ""),
            text_language=request_segment.language,
            terminal_raw=request_segment.terminal_punctuation or "",
            terminal_source="original",
            detected_language=request_segment.language,
            inference_exclusion_reason="none",
            render_version=render_version,
        )

    @staticmethod
    def _build_editable_edge(
        *,
        edge_control: Any,
        boundary_strategy: str = "crossfade_only",
    ) -> EditableEdge:
        return EditableEdge(
            edge_id=edge_control.edge_id,
            document_id="block-render-request",
            left_segment_id=edge_control.left_segment_id,
            right_segment_id=edge_control.right_segment_id,
            pause_duration_seconds=edge_control.pause_duration_seconds,
            boundary_strategy=boundary_strategy,
            effective_boundary_strategy=boundary_strategy,
            boundary_strategy_locked=edge_control.locked,
            edge_version=0,
        )

    @staticmethod
    def _should_render_enhanced_boundary(
        *,
        request: BlockRenderRequest,
        left: _PreparedSegment,
        right: _PreparedSegment,
        edge_control: Any,
    ) -> bool:
        if request.join_policy != "prefer_enhanced" and edge_control.join_policy_override != "prefer_enhanced":
            return False
        return (
            left.model_binding.binding_fingerprint == right.model_binding.binding_fingerprint
            and str(left.reference.get("fingerprint") or "") == str(right.reference.get("fingerprint") or "")
        )

    @staticmethod
    def _build_exact_segment_spans(block_asset: BlockCompositionAssetPayload) -> list[SegmentSpan]:
        return [
            SegmentSpan(
                segment_id=entry.segment_id,
                sample_start=int(entry.audio_sample_span[0]),
                sample_end=int(entry.audio_sample_span[1]),
                precision="exact",
            )
            for entry in block_asset.segment_entries
        ]

    def _raise_if_cancelled(self) -> None:
        if callable(self._cancellation_checker) and self._cancellation_checker():
            raise RuntimeError("Block rendering cancelled.")
