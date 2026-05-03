from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any, Callable

import numpy as np

from backend.app.inference.block_adapter_types import (
    AdapterCapabilities,
    AudioResult,
    BlockRenderRequest,
    BlockRenderResult,
    BoundaryResult,
    DegradationReport,
    JoinReport,
    ResolvedModelBinding,
    ScopeFeedback,
    SegmentAlignmentResult,
    SegmentOutput,
    SegmentSpan,
)
from backend.app.inference.editable_types import SegmentRenderAssetPayload, build_render_asset_id, fingerprint_inference_config
from backend.app.inference.qwen3_tts_runtime import Qwen3TTSSegmentRequest, Qwen3TTSRuntime
from backend.app.services.composition_builder import CompositionBuilder


@dataclass(frozen=True)
class _PreparedSegment:
    request_segment: Any
    model_binding: ResolvedModelBinding


@dataclass(frozen=True)
class _ReusableLoadState:
    segment_assets: dict[str, SegmentRenderAssetPayload]
    sample_rate: int | None


class Qwen3TTSLocalAdapter:
    def __init__(
        self,
        *,
        runtime: Qwen3TTSRuntime,
        composition_builder: CompositionBuilder | None = None,
        reusable_asset_accessor=None,
        cancellation_checker: Callable[[], bool] | None = None,
        segment_asset_callback: Callable[[SegmentRenderAssetPayload, Any, bool], None] | None = None,
    ) -> None:
        self._runtime = runtime
        self._composition_builder = composition_builder or CompositionBuilder(sample_rate=24000)
        self._reusable_asset_accessor = reusable_asset_accessor
        self._cancellation_checker = cancellation_checker
        self._segment_asset_callback = segment_asset_callback

    @staticmethod
    def capabilities() -> AdapterCapabilities:
        return AdapterCapabilities(
            block_render=True,
            exact_segment_output=True,
            segment_level_voice_binding=True,
            incremental_render=True,
            local_gpu_runtime=True,
            cancellable=True,
        )

    def render_block(self, request: BlockRenderRequest) -> BlockRenderResult:
        self._raise_if_cancelled()
        prepared_segments = [self._prepare_segment(request_segment) for request_segment in request.block.segments]
        reusable_state = self._load_reusable_assets(request=request)
        segment_assets: list[SegmentRenderAssetPayload] = []
        reused_segment_ids: list[str] = []
        sample_rate = reusable_state.sample_rate
        for prepared in prepared_segments:
            self._raise_if_cancelled()
            reusable_asset = reusable_state.segment_assets.get(prepared.request_segment.segment_id)
            if reusable_asset is not None:
                segment_assets.append(reusable_asset)
                reused_segment_ids.append(prepared.request_segment.segment_id)
                self._notify_segment_asset(reusable_asset, prepared.request_segment, reused=True)
                continue
            runtime_result = self._runtime.render_segment(self._build_runtime_request(prepared))
            sample_rate = runtime_result.sample_rate if sample_rate is None else sample_rate
            if runtime_result.sample_rate != sample_rate:
                raise ValueError("Qwen3-TTS segment sample rates must match within one block.")
            asset = self._build_segment_asset(prepared=prepared, runtime_result=runtime_result)
            segment_assets.append(asset)
            self._notify_segment_asset(asset, prepared.request_segment, reused=False)
        if sample_rate is None:
            raise ValueError("Qwen3-TTS block render did not resolve a sample rate.")

        join_downgrade_reasons = {}
        if request.join_policy == "prefer_enhanced" and len(segment_assets) > 1:
            join_downgrade_reasons = {edge.edge_id: "crossfade_only" for edge in request.edge_controls}
        block_asset = CompositionBuilder(sample_rate=sample_rate).compose_block(
            segment_assets,
            [],
            self._build_editable_edges(request),
            block_id=request.block.block_id,
            segment_alignment_mode="exact",
            join_report_summary={
                "requested_policy": request.requested_join_policy or request.join_policy,
                "applied_mode": "preserve_pause" if request.join_policy == "prefer_enhanced" else request.join_policy,
                "enhancement_applied": False,
            },
        )
        segment_spans = [
            SegmentSpan(
                segment_id=entry.segment_id,
                sample_start=int(entry.audio_sample_span[0]),
                sample_end=int(entry.audio_sample_span[1]),
                precision="exact",
            )
            for entry in block_asset.segment_entries
        ]
        return BlockRenderResult(
            block_id=request.block.block_id,
            segment_ids=[segment.segment_id for segment in request.block.segments],
            sample_rate=sample_rate,
            audio=block_asset.audio.astype(np.float32, copy=False).tolist(),
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
            audio_result=AudioResult(
                sample_rate=sample_rate,
                audio=block_asset.audio.astype(np.float32, copy=False).tolist(),
                audio_sample_count=block_asset.audio_sample_count,
            ),
            segment_alignment_result=SegmentAlignmentResult(
                mode="exact",
                spans=segment_spans,
                precision_reason="adapter_exact",
            ),
            boundary_results=[
                BoundaryResult(
                    edge_id=edge.edge_id,
                    mode="fallback",
                    diagnostics={"reason": "crossfade_only"},
                )
                for edge in request.edge_controls
            ],
            degradation_report=DegradationReport(
                requested_mode=request.requested_alignment_mode,
                delivered_mode="exact",
                reasons=sorted(set(join_downgrade_reasons.values())),
            ),
            scope_feedback=ScopeFeedback(
                requested_scope=request.render_scope,
                actual_scope=request.render_scope,
                escalated_from_scope=request.escalated_from_scope,
            ),
            join_report=JoinReport(
                requested_policy=request.requested_join_policy or request.join_policy,
                applied_mode="preserve_pause" if request.join_policy == "prefer_enhanced" else request.join_policy,
                enhancement_applied=False,
                implementation="qwen3_tts_local_adapter",
            ),
            adapter_trace={"reused_segment_ids": reused_segment_ids},
            diagnostics={"join_downgrade_reasons": join_downgrade_reasons},
        )

    @staticmethod
    def _prepare_segment(request_segment: Any) -> _PreparedSegment:
        resolved_model_binding = getattr(request_segment, "resolved_model_binding", None)
        model_binding = ResolvedModelBinding.model_validate(resolved_model_binding)
        return _PreparedSegment(
            request_segment=request_segment,
            model_binding=model_binding,
        )

    def _build_runtime_request(self, prepared: _PreparedSegment) -> Qwen3TTSSegmentRequest:
        model_binding = prepared.model_binding
        preset_defaults = dict(model_binding.preset_defaults)
        preset_fixed_fields = dict(model_binding.preset_fixed_fields)
        adapter_options = dict(model_binding.adapter_options)
        return Qwen3TTSSegmentRequest(
            segment_id=prepared.request_segment.segment_id,
            text=prepared.request_segment.text,
            model_dir=self._read_required_asset_path(model_binding.resolved_assets, "model_dir"),
            generation_mode=self._resolve_generation_mode(model_binding),
            language=self._coalesce_text(
                preset_defaults.get("language"),
                model_binding.resolved_reference.get("language") if model_binding.resolved_reference else None,
                prepared.request_segment.language,
            ),
            speaker=self._coalesce_text(preset_defaults.get("speaker")),
            instruct=self._coalesce_text(preset_defaults.get("instruct")),
            reference_audio_path=self._coalesce_text(
                model_binding.resolved_reference.get("audio_uri") if model_binding.resolved_reference else None
            ),
            reference_text=self._coalesce_text(
                preset_defaults.get("reference_text"),
                model_binding.resolved_reference.get("text") if model_binding.resolved_reference else None,
            ),
            top_k=int(model_binding.resolved_parameters.get("top_k", 20)),
            top_p=float(model_binding.resolved_parameters.get("top_p", 0.8)),
            temperature=float(model_binding.resolved_parameters.get("temperature", 0.7)),
            device=self._coalesce_text(adapter_options.get("device")),
            dtype=self._coalesce_text(adapter_options.get("dtype")),
            attn_implementation=self._coalesce_text(adapter_options.get("attn_implementation")),
            extra_generate_kwargs={
                key: value
                for key, value in adapter_options.items()
                if key not in {"device", "dtype", "attn_implementation"}
            },
        )

    def _build_segment_asset(
        self,
        *,
        prepared: _PreparedSegment,
        runtime_result,
    ) -> SegmentRenderAssetPayload:
        audio = np.asarray(runtime_result.audio, dtype=np.float32)
        fingerprint = fingerprint_inference_config(
            {
                "binding_fingerprint": prepared.model_binding.binding_fingerprint,
                "segment_id": prepared.request_segment.segment_id,
                "render_version": prepared.request_segment.render_version,
                "audio_sample_count": int(audio.size),
            }
        )
        return SegmentRenderAssetPayload(
            render_asset_id=build_render_asset_id(
                segment_id=prepared.request_segment.segment_id,
                render_version=prepared.request_segment.render_version,
                semantic_tokens=[],
                fingerprint=fingerprint,
            ),
            segment_id=prepared.request_segment.segment_id,
            render_version=prepared.request_segment.render_version,
            sample_rate=runtime_result.sample_rate,
            semantic_tokens=[],
            phone_ids=[],
            decoder_frame_count=0,
            audio_sample_count=int(audio.size),
            left_margin_sample_count=0,
            core_sample_count=int(audio.size),
            right_margin_sample_count=0,
            left_margin_audio=np.zeros(0, dtype=np.float32),
            core_audio=audio,
            right_margin_audio=np.zeros(0, dtype=np.float32),
            trace=dict(getattr(runtime_result, "trace", {}) or {}),
        )

    def _load_reusable_assets(self, *, request: BlockRenderRequest) -> _ReusableLoadState:
        dirty_context = request.dirty_context
        if (
            dirty_context is None
            or dirty_context.reuse_policy != "prefer_reuse"
            or not dirty_context.previous_block_asset_id
            or self._reusable_asset_accessor is None
        ):
            return _ReusableLoadState(segment_assets={}, sample_rate=None)
        try:
            block_asset = self._reusable_asset_accessor.load_block_asset(dirty_context.previous_block_asset_id)
        except FileNotFoundError:
            return _ReusableLoadState(segment_assets={}, sample_rate=None)
        reusable_assets: dict[str, SegmentRenderAssetPayload] = {}
        dirty_segment_ids = set(dirty_context.dirty_segment_ids)
        for entry in block_asset.segment_entries:
            if entry.segment_id in dirty_segment_ids:
                continue
            asset_id = entry.base_render_asset_id or entry.render_asset_id
            if not asset_id:
                continue
            try:
                reusable_assets[entry.segment_id] = self._reusable_asset_accessor.load_segment_asset(asset_id)
            except FileNotFoundError:
                continue
        return _ReusableLoadState(segment_assets=reusable_assets, sample_rate=block_asset.sample_rate)

    @staticmethod
    def _build_editable_edges(request: BlockRenderRequest) -> list[Any]:
        edges: list[Any] = []
        for edge_control in request.edge_controls:
            edges.append(
                SimpleNamespace(
                    edge_id=edge_control.edge_id,
                    left_segment_id=edge_control.left_segment_id,
                    right_segment_id=edge_control.right_segment_id,
                    pause_duration_seconds=edge_control.pause_duration_seconds,
                    boundary_strategy="crossfade_only",
                    effective_boundary_strategy="crossfade_only",
                    edge_version=0,
                )
            )
        return edges

    @staticmethod
    def _resolve_generation_mode(model_binding: ResolvedModelBinding) -> str:
        raw_value = model_binding.preset_fixed_fields.get("generation_mode")
        if isinstance(raw_value, str) and raw_value.strip():
            return raw_value.strip()
        if model_binding.resolved_reference and model_binding.resolved_reference.get("audio_uri"):
            return "voice_clone"
        if model_binding.preset_defaults.get("speaker"):
            return "custom_voice"
        return "voice_design"

    @staticmethod
    def _read_required_asset_path(assets: dict[str, Any], asset_key: str) -> str:
        raw_asset = assets.get(asset_key)
        if not isinstance(raw_asset, dict):
            raise ValueError(f"Qwen3-TTS missing required asset '{asset_key}'.")
        for key in ("path", "source_path", "relative_path"):
            raw_value = raw_asset.get(key)
            if isinstance(raw_value, str) and raw_value.strip():
                return raw_value
        raise ValueError(f"Qwen3-TTS missing path for asset '{asset_key}'.")

    @staticmethod
    def _coalesce_text(*values: Any) -> str | None:
        for value in values:
            if isinstance(value, str) and value.strip():
                return value
        return None

    def _raise_if_cancelled(self) -> None:
        if callable(self._cancellation_checker) and self._cancellation_checker():
            raise RuntimeError("Block rendering cancelled.")

    def _notify_segment_asset(self, asset: SegmentRenderAssetPayload, request_segment: Any, *, reused: bool) -> None:
        if callable(self._segment_asset_callback):
            self._segment_asset_callback(asset, request_segment, reused)
