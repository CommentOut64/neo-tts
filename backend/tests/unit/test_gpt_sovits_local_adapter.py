from __future__ import annotations

import inspect
from dataclasses import replace
from types import SimpleNamespace

import numpy as np

from backend.app.inference.block_adapter_types import (
    AdapterCapabilities,
    BlockRenderRequest,
    BlockRequestBlock,
    BlockRequestSegment,
    DirtyContext,
    EdgeControl,
    ResolvedModelBinding,
)
from backend.app.inference.editable_types import (
    BlockCompositionAssetPayload,
    BoundaryAssetPayload,
    SegmentCompositionEntry,
    SegmentRenderAssetPayload,
)
from backend.app.services.composition_builder import CompositionBuilder


def _segment_asset(
    *,
    segment_id: str,
    render_version: int,
    left: list[float],
    core: list[float],
    right: list[float],
    sample_rate: int = 4,
) -> SegmentRenderAssetPayload:
    left_audio = np.asarray(left, dtype=np.float32)
    core_audio = np.asarray(core, dtype=np.float32)
    right_audio = np.asarray(right, dtype=np.float32)
    return SegmentRenderAssetPayload(
        render_asset_id=f"render-{segment_id}-v{render_version}",
        segment_id=segment_id,
        render_version=render_version,
        sample_rate=sample_rate,
        semantic_tokens=[1, 2, 3],
        phone_ids=[11, 12],
        decoder_frame_count=3,
        audio_sample_count=int(left_audio.size + core_audio.size + right_audio.size),
        left_margin_sample_count=int(left_audio.size),
        core_sample_count=int(core_audio.size),
        right_margin_sample_count=int(right_audio.size),
        left_margin_audio=left_audio,
        core_audio=core_audio,
        right_margin_audio=right_audio,
        trace=None,
    )


def _resolved_model_binding(
    *,
    binding_fingerprint: str,
    model_instance_id: str,
    preset_id: str,
    reference_id: str,
) -> ResolvedModelBinding:
    return ResolvedModelBinding(
        adapter_id="gpt_sovits_local",
        model_instance_id=model_instance_id,
        preset_id=preset_id,
        resolved_assets={
            "gpt_weight": f"weights/{model_instance_id}.ckpt",
            "sovits_weight": f"weights/{model_instance_id}.pth",
        },
        resolved_reference={
            "reference_id": reference_id,
            "audio_uri": f"managed://{reference_id}.wav",
            "text": "参考文本",
            "language": "zh",
            "source": "preset",
            "fingerprint": f"fp-{reference_id}",
        },
        resolved_parameters={
            "speed": 1.0,
            "top_k": 15,
            "top_p": 1.0,
            "temperature": 1.0,
            "noise_scale": 0.35,
        },
        secret_handles={},
        binding_fingerprint=binding_fingerprint,
    )


def _segment_request(
    segment_id: str,
    order_key: int,
    *,
    voice_binding_id: str,
    voice_id: str,
    model_key: str,
    model_instance_id: str,
    preset_id: str,
    binding_fingerprint: str,
    reference_id: str,
) -> BlockRequestSegment:
    binding = _resolved_model_binding(
        binding_fingerprint=binding_fingerprint,
        model_instance_id=model_instance_id,
        preset_id=preset_id,
        reference_id=reference_id,
    )
    return BlockRequestSegment(
        segment_id=segment_id,
        order_key=order_key,
        text=f"{segment_id} 文本。",
        language="zh",
        terminal_punctuation="。",
        voice_binding_id=voice_binding_id,
        render_profile_id="profile-1",
        resolved_binding={
            "voice_binding_id": voice_binding_id,
            "voice_id": voice_id,
            "model_key": model_key,
            "model_instance_id": model_instance_id,
            "preset_id": preset_id,
        },
        resolved_model_binding=binding.model_dump(mode="json"),
        resolved_reference={
            "reference_id": reference_id,
            "audio_uri": f"managed://{reference_id}.wav",
            "text": "参考文本",
            "language": "zh",
            "source": "preset",
            "fingerprint": f"fp-{reference_id}",
        },
    )


def _build_request(
    *,
    segments: list[BlockRequestSegment],
    join_policy: str = "prefer_enhanced",
    dirty_context: DirtyContext | None = None,
    pause_duration_seconds: float = 0.5,
) -> BlockRenderRequest:
    first_binding = ResolvedModelBinding.model_validate(segments[0].resolved_model_binding)
    edge_controls: list[EdgeControl] = []
    if len(segments) > 1:
        for left, right in zip(segments, segments[1:], strict=False):
            edge_controls.append(
                EdgeControl(
                    edge_id=f"edge-{left.segment_id}-{right.segment_id}",
                    left_segment_id=left.segment_id,
                    right_segment_id=right.segment_id,
                    pause_duration_seconds=pause_duration_seconds,
                    join_policy_override="prefer_enhanced",
                    locked=False,
                )
            )
    return BlockRenderRequest(
        request_id="req-1",
        document_id="doc-1",
        block=BlockRequestBlock(
            block_id="block-1",
            segment_ids=[segment.segment_id for segment in segments],
            start_order_key=segments[0].order_key,
            end_order_key=segments[-1].order_key,
            estimated_sample_count=8,
            segments=segments,
            block_text="\n".join(segment.text for segment in segments),
        ),
        model_binding=first_binding,
        voice={"voice_id": segments[0].resolved_binding["voice_id"]},
        model={"model_key": segments[0].resolved_binding["model_key"]},
        reference={"reference_id": segments[0].resolved_reference["reference_id"]},
        synthesis=dict(first_binding.resolved_parameters),
        join_policy=join_policy,
        edge_controls=edge_controls,
        dirty_context=dirty_context,
    )


class _FakeEditableGateway:
    def __init__(
        self,
        *,
        segment_assets: dict[str, SegmentRenderAssetPayload],
        boundary_audio_by_edge_id: dict[str, list[float]] | None = None,
    ) -> None:
        self.context_calls: list[object] = []
        self.built_contexts: list[object] = []
        self.segment_calls: list[tuple[str, object]] = []
        self.rendered_segments: list[object] = []
        self.boundary_calls: list[tuple[str, str, str, object]] = []
        self._segment_assets = segment_assets
        self._boundary_audio_by_edge_id = boundary_audio_by_edge_id or {}

    def build_reference_context(self, resolved_context, *, progress_callback=None):
        del progress_callback
        self.context_calls.append(resolved_context)
        context = SimpleNamespace(
            voice_binding_id=getattr(resolved_context.resolved_voice_binding, "voice_binding_id", None),
            reference_id=resolved_context.reference_identity,
            backend_cache_key=None,
        )
        self.built_contexts.append(context)
        return context

    def render_segment_base(self, segment, context, *, progress_callback=None):
        del progress_callback
        self.segment_calls.append((segment.segment_id, context))
        self.rendered_segments.append(segment)
        return self._segment_assets[segment.segment_id]

    def render_boundary_asset(self, left_asset, right_asset, edge, context):
        self.boundary_calls.append((left_asset.segment_id, right_asset.segment_id, edge.edge_id, context))
        boundary_audio = np.asarray(self._boundary_audio_by_edge_id[edge.edge_id], dtype=np.float32)
        return BoundaryAssetPayload(
            boundary_asset_id=f"boundary-{edge.edge_id}",
            left_segment_id=edge.left_segment_id,
            left_render_version=left_asset.render_version,
            right_segment_id=edge.right_segment_id,
            right_render_version=right_asset.render_version,
            edge_version=0,
            sample_rate=left_asset.sample_rate,
            boundary_strategy=edge.boundary_strategy,
            boundary_sample_count=int(boundary_audio.size),
            boundary_audio=boundary_audio,
            trace={"edge_id": edge.edge_id},
        )


class _ReadonlyAssetAccessor:
    def __init__(
        self,
        *,
        block_asset: BlockCompositionAssetPayload,
        segment_assets: dict[str, SegmentRenderAssetPayload],
    ) -> None:
        self.block_asset = block_asset
        self.segment_assets = segment_assets
        self.loaded_blocks: list[str] = []
        self.loaded_segments: list[str] = []

    def load_block_asset(self, block_asset_id: str) -> BlockCompositionAssetPayload:
        self.loaded_blocks.append(block_asset_id)
        return self.block_asset

    def load_segment_asset(self, render_asset_id: str) -> SegmentRenderAssetPayload:
        self.loaded_segments.append(render_asset_id)
        return self.segment_assets[render_asset_id]


def test_gpt_sovits_local_adapter_capabilities_cover_phase4_contract():
    from backend.app.inference.adapters.gpt_sovits_local_adapter import GPTSoVITSLocalAdapter

    capabilities = GPTSoVITSLocalAdapter.capabilities()

    assert capabilities.block_render is True
    assert capabilities.exact_segment_output is True
    assert capabilities.segment_level_voice_binding is True
    assert capabilities.incremental_render is True
    assert capabilities.boundary_enhancement is True
    assert capabilities.native_join_fusion is True
    assert capabilities.local_gpu_runtime is True
    assert capabilities.cancellable is True
    assert capabilities.supports_exact_alignment is True
    assert capabilities.supports_block_only_alignment is True
    assert capabilities.supports_boundary_enhancement is True
    assert capabilities.supports_incremental_render is True
    assert capabilities.supports_segment_level_voice_binding is True
    assert capabilities.supports_pause_only_compose is True
    assert capabilities.supports_cancellation is True


def test_gpt_sovits_local_adapter_renders_multi_segment_block_with_exact_spans():
    from backend.app.inference.adapters.gpt_sovits_local_adapter import GPTSoVITSLocalAdapter

    request = _build_request(
        segments=[
            _segment_request(
                "seg-1",
                1,
                voice_binding_id="binding-a",
                voice_id="voice-a",
                model_key="model-a",
                model_instance_id="model-a",
                preset_id="preset-a",
                binding_fingerprint="binding-a",
                reference_id="ref-a",
            ),
            _segment_request(
                "seg-2",
                2,
                voice_binding_id="binding-a",
                voice_id="voice-a",
                model_key="model-a",
                model_instance_id="model-a",
                preset_id="preset-a",
                binding_fingerprint="binding-a",
                reference_id="ref-a",
            ),
        ]
    )
    gateway = _FakeEditableGateway(
        segment_assets={
            "seg-1": _segment_asset(segment_id="seg-1", render_version=1, left=[0.1], core=[0.2, 0.3], right=[0.4]),
            "seg-2": _segment_asset(segment_id="seg-2", render_version=1, left=[0.5], core=[0.6], right=[0.7, 0.8]),
        },
        boundary_audio_by_edge_id={"edge-seg-1-seg-2": [0.9]},
    )

    adapter = GPTSoVITSLocalAdapter(
        editable_gateway=gateway,
        composition_builder=CompositionBuilder(sample_rate=4),
    )
    result = adapter.render_block(request)

    assert gateway.segment_calls == [
        ("seg-1", gateway.built_contexts[0]),
        ("seg-2", gateway.built_contexts[0]),
    ]
    assert len(gateway.boundary_calls) == 1
    assert result.block_id == "block-1"
    assert result.segment_ids == ["seg-1", "seg-2"]
    assert result.sample_rate == 4
    assert result.audio_sample_count == 9
    assert np.allclose(result.audio, [0.1, 0.2, 0.3, 0.9, 0.0, 0.0, 0.6, 0.7, 0.8])
    assert result.segment_alignment_mode == "exact"
    assert [(span.segment_id, span.sample_start, span.sample_end) for span in result.segment_spans] == [
        ("seg-1", 0, 3),
        ("seg-2", 6, 9),
    ]
    assert result.join_report is not None
    assert result.join_report.requested_policy == "prefer_enhanced"
    assert result.join_report.applied_mode == "prefer_enhanced"
    assert result.join_report.enhancement_applied is True


def test_gpt_sovits_local_adapter_uses_segment_level_binding_and_downgrades_incompatible_boundary():
    from backend.app.inference.adapters.gpt_sovits_local_adapter import GPTSoVITSLocalAdapter

    request = _build_request(
        segments=[
            _segment_request(
                "seg-1",
                1,
                voice_binding_id="binding-a",
                voice_id="voice-a",
                model_key="model-a",
                model_instance_id="model-a",
                preset_id="preset-a",
                binding_fingerprint="binding-a",
                reference_id="ref-a",
            ),
            _segment_request(
                "seg-2",
                2,
                voice_binding_id="binding-b",
                voice_id="voice-b",
                model_key="model-b",
                model_instance_id="model-b",
                preset_id="preset-b",
                binding_fingerprint="binding-b",
                reference_id="ref-b",
            ),
        ]
    )
    gateway = _FakeEditableGateway(
        segment_assets={
            "seg-1": _segment_asset(segment_id="seg-1", render_version=1, left=[0.1], core=[0.2, 0.3], right=[0.4]),
            "seg-2": _segment_asset(segment_id="seg-2", render_version=1, left=[0.5], core=[0.6], right=[0.7, 0.8]),
        },
        boundary_audio_by_edge_id={"edge-seg-1-seg-2": [0.9]},
    )

    result = GPTSoVITSLocalAdapter(
        editable_gateway=gateway,
        composition_builder=CompositionBuilder(sample_rate=4),
    ).render_block(request)

    assert [call.resolved_voice_binding.voice_binding_id for call in gateway.context_calls] == ["binding-a", "binding-b"]
    assert gateway.boundary_calls == []
    assert result.join_report is not None
    assert result.join_report.requested_policy == "prefer_enhanced"
    assert result.join_report.applied_mode == "preserve_pause"
    assert result.join_report.enhancement_applied is False
    assert result.degradation_report is not None
    assert result.degradation_report.delivered_mode == "exact"
    assert result.boundary_results[0].mode == "fallback"
    assert result.scope_feedback is not None
    assert result.scope_feedback.requested_scope == request.render_scope
    assert result.diagnostics["join_downgrade_reasons"] == {
        "edge-seg-1-seg-2": "binding_or_reference_mismatch"
    }


def test_gpt_sovits_local_adapter_prefers_reuse_for_clean_segments_and_rerenders_dirty_targets():
    from backend.app.inference.adapters.gpt_sovits_local_adapter import GPTSoVITSLocalAdapter

    request = _build_request(
        segments=[
            _segment_request(
                "seg-1",
                1,
                voice_binding_id="binding-a",
                voice_id="voice-a",
                model_key="model-a",
                model_instance_id="model-a",
                preset_id="preset-a",
                binding_fingerprint="binding-a",
                reference_id="ref-a",
            ),
            _segment_request(
                "seg-2",
                2,
                voice_binding_id="binding-a",
                voice_id="voice-a",
                model_key="model-a",
                model_instance_id="model-a",
                preset_id="preset-a",
                binding_fingerprint="binding-a",
                reference_id="ref-a",
            ),
        ],
        dirty_context=DirtyContext(
            dirty_segment_ids=["seg-2"],
            dirty_edge_ids=["edge-seg-1-seg-2"],
            previous_block_asset_id="block-asset-old",
            reuse_policy="prefer_reuse",
        ),
    )
    gateway = _FakeEditableGateway(
        segment_assets={
            "seg-2": _segment_asset(segment_id="seg-2", render_version=2, left=[0.5], core=[2.0], right=[2.1]),
        },
        boundary_audio_by_edge_id={"edge-seg-1-seg-2": [0.9]},
    )
    reusable_segment = _segment_asset(segment_id="seg-1", render_version=1, left=[0.1], core=[0.2, 0.3], right=[0.4])
    asset_accessor = _ReadonlyAssetAccessor(
        block_asset=BlockCompositionAssetPayload(
            block_id="block-1",
            block_asset_id="block-asset-old",
            segment_ids=["seg-1", "seg-2"],
            sample_rate=4,
            audio=np.asarray([0.1, 0.2, 0.3, 0.9, 0.0, 0.0, 0.6, 0.7, 0.8], dtype=np.float32),
            audio_sample_count=9,
            segment_entries=[
                SegmentCompositionEntry(segment_id="seg-1", audio_sample_span=(0, 3), render_asset_id=reusable_segment.render_asset_id),
                SegmentCompositionEntry(segment_id="seg-2", audio_sample_span=(6, 9), render_asset_id="render-seg-2-v1"),
            ],
        ),
        segment_assets={reusable_segment.render_asset_id: reusable_segment},
    )

    result = GPTSoVITSLocalAdapter(
        editable_gateway=gateway,
        composition_builder=CompositionBuilder(sample_rate=4),
        reusable_asset_accessor=asset_accessor,
    ).render_block(request)

    assert asset_accessor.loaded_blocks == ["block-asset-old"]
    assert asset_accessor.loaded_segments == [reusable_segment.render_asset_id]
    assert [segment_id for segment_id, _ in gateway.segment_calls] == ["seg-2"]
    assert len(gateway.boundary_calls) == 1
    assert np.allclose(result.audio, [0.1, 0.2, 0.3, 0.9, 0.0, 0.0, 2.0, 2.1])
    assert [(span.segment_id, span.sample_start, span.sample_end) for span in result.segment_spans] == [
        ("seg-1", 0, 3),
        ("seg-2", 6, 8),
    ]


def test_gpt_sovits_local_adapter_downgrades_join_policy_when_reusable_segment_cannot_support_enhanced_boundary():
    from backend.app.inference.adapters.gpt_sovits_local_adapter import GPTSoVITSLocalAdapter

    request = _build_request(
        segments=[
            _segment_request(
                "seg-1",
                1,
                voice_binding_id="binding-a",
                voice_id="voice-a",
                model_key="model-a",
                model_instance_id="model-a",
                preset_id="preset-a",
                binding_fingerprint="binding-a",
                reference_id="ref-a",
            ),
            _segment_request(
                "seg-2",
                2,
                voice_binding_id="binding-a",
                voice_id="voice-a",
                model_key="model-a",
                model_instance_id="model-a",
                preset_id="preset-a",
                binding_fingerprint="binding-a",
                reference_id="ref-a",
            ),
        ],
        dirty_context=DirtyContext(
            dirty_segment_ids=["seg-2"],
            dirty_edge_ids=["edge-seg-1-seg-2"],
            previous_block_asset_id="block-asset-old",
            reuse_policy="prefer_reuse",
        ),
    )
    gateway = _FakeEditableGateway(
        segment_assets={
            "seg-1": _segment_asset(segment_id="seg-1", render_version=2, left=[0.1], core=[1.0], right=[1.1]),
            "seg-2": _segment_asset(segment_id="seg-2", render_version=2, left=[0.2], core=[2.0], right=[2.1]),
        },
        boundary_audio_by_edge_id={"edge-seg-1-seg-2": [0.9]},
    )
    derived_reusable_segment = replace(
        _segment_asset(segment_id="seg-1", render_version=1, left=[], core=[0.2, 0.3], right=[]),
        semantic_tokens=[],
        phone_ids=[],
        decoder_frame_count=0,
        trace={"derived_from_block": True},
    )
    asset_accessor = _ReadonlyAssetAccessor(
        block_asset=BlockCompositionAssetPayload(
            block_id="block-1",
            block_asset_id="block-asset-old",
            segment_ids=["seg-1", "seg-2"],
            sample_rate=4,
            audio=np.asarray([0.1, 0.2, 0.3, 0.9, 0.0, 0.0, 0.6, 0.7, 0.8], dtype=np.float32),
            audio_sample_count=9,
            segment_entries=[
                SegmentCompositionEntry(
                    segment_id="seg-1",
                    audio_sample_span=(0, 3),
                    render_asset_id=derived_reusable_segment.render_asset_id,
                ),
                SegmentCompositionEntry(segment_id="seg-2", audio_sample_span=(6, 9), render_asset_id="render-seg-2-v1"),
            ],
        ),
        segment_assets={derived_reusable_segment.render_asset_id: derived_reusable_segment},
    )

    result = GPTSoVITSLocalAdapter(
        editable_gateway=gateway,
        composition_builder=CompositionBuilder(sample_rate=4),
        reusable_asset_accessor=asset_accessor,
    ).render_block(request)

    assert asset_accessor.loaded_blocks == ["block-asset-old"]
    assert asset_accessor.loaded_segments == [derived_reusable_segment.render_asset_id]
    assert [segment_id for segment_id, _ in gateway.segment_calls] == ["seg-2"]
    assert gateway.boundary_calls == []
    assert result.join_report is not None
    assert result.join_report.requested_policy == "prefer_enhanced"
    assert result.join_report.applied_mode == "preserve_pause"
    assert result.join_report.enhancement_applied is False
    assert result.diagnostics["join_downgrade_reasons"] == {
        "edge-seg-1-seg-2": "neighbor_asset_not_reusable"
    }


def test_gpt_sovits_local_adapter_prefers_base_render_asset_id_for_reuse():
    from backend.app.inference.adapters.gpt_sovits_local_adapter import GPTSoVITSLocalAdapter

    request = _build_request(
        segments=[
            _segment_request(
                "seg-1",
                1,
                voice_binding_id="binding-a",
                voice_id="voice-a",
                model_key="model-a",
                model_instance_id="model-a",
                preset_id="preset-a",
                binding_fingerprint="binding-a",
                reference_id="ref-a",
            ),
            _segment_request(
                "seg-2",
                2,
                voice_binding_id="binding-a",
                voice_id="voice-a",
                model_key="model-a",
                model_instance_id="model-a",
                preset_id="preset-a",
                binding_fingerprint="binding-a",
                reference_id="ref-a",
            ),
        ],
        dirty_context=DirtyContext(
            dirty_segment_ids=["seg-2"],
            dirty_edge_ids=["edge-seg-1-seg-2"],
            previous_block_asset_id="block-asset-old",
            reuse_policy="prefer_reuse",
        ),
    )
    gateway = _FakeEditableGateway(
        segment_assets={
            "seg-2": _segment_asset(segment_id="seg-2", render_version=2, left=[0.5], core=[2.0], right=[2.1]),
        },
        boundary_audio_by_edge_id={"edge-seg-1-seg-2": [0.9]},
    )
    reusable_base_segment = _segment_asset(segment_id="seg-1", render_version=1, left=[0.1], core=[0.2, 0.3], right=[0.4])
    derived_exact_segment = replace(
        _segment_asset(segment_id="seg-1", render_version=1, left=[], core=[0.2, 0.3], right=[]),
        render_asset_id="derived-seg-1",
        semantic_tokens=[],
        phone_ids=[],
        decoder_frame_count=0,
        trace={"derived_from_block": True},
    )
    asset_accessor = _ReadonlyAssetAccessor(
        block_asset=BlockCompositionAssetPayload(
            block_id="block-1",
            block_asset_id="block-asset-old",
            segment_ids=["seg-1", "seg-2"],
            sample_rate=4,
            audio=np.asarray([0.1, 0.2, 0.3, 0.9, 0.0, 0.0, 0.6, 0.7, 0.8], dtype=np.float32),
            audio_sample_count=9,
            segment_entries=[
                SegmentCompositionEntry(
                    segment_id="seg-1",
                    audio_sample_span=(0, 3),
                    render_asset_id=derived_exact_segment.render_asset_id,
                    base_render_asset_id=reusable_base_segment.render_asset_id,
                ),
                SegmentCompositionEntry(segment_id="seg-2", audio_sample_span=(6, 9), render_asset_id="render-seg-2-v1"),
            ],
        ),
        segment_assets={
            derived_exact_segment.render_asset_id: derived_exact_segment,
            reusable_base_segment.render_asset_id: reusable_base_segment,
        },
    )

    result = GPTSoVITSLocalAdapter(
        editable_gateway=gateway,
        composition_builder=CompositionBuilder(sample_rate=4),
        reusable_asset_accessor=asset_accessor,
    ).render_block(request)

    assert asset_accessor.loaded_blocks == ["block-asset-old"]
    assert asset_accessor.loaded_segments == [reusable_base_segment.render_asset_id]
    assert gateway.boundary_calls == [("seg-1", "seg-2", "edge-seg-1-seg-2", gateway.built_contexts[0])]
    assert result.join_report is not None
    assert result.join_report.applied_mode == "prefer_enhanced"
    assert result.join_report.enhancement_applied is True
    assert result.boundary_results[0].mode == "enhanced"
    assert result.scope_feedback is not None
    assert result.scope_feedback.actual_scope == request.render_scope


def test_gpt_sovits_local_adapter_falls_back_to_exact_asset_when_base_render_asset_is_missing():
    from backend.app.inference.adapters.gpt_sovits_local_adapter import GPTSoVITSLocalAdapter

    request = _build_request(
        segments=[
            _segment_request(
                "seg-1",
                1,
                voice_binding_id="binding-a",
                voice_id="voice-a",
                model_key="model-a",
                model_instance_id="model-a",
                preset_id="preset-a",
                binding_fingerprint="binding-a",
                reference_id="ref-a",
            ),
            _segment_request(
                "seg-2",
                2,
                voice_binding_id="binding-a",
                voice_id="voice-a",
                model_key="model-a",
                model_instance_id="model-a",
                preset_id="preset-a",
                binding_fingerprint="binding-a",
                reference_id="ref-a",
            ),
        ],
        dirty_context=DirtyContext(
            dirty_segment_ids=["seg-2"],
            dirty_edge_ids=["edge-seg-1-seg-2"],
            previous_block_asset_id="block-asset-old",
            reuse_policy="prefer_reuse",
        ),
    )
    gateway = _FakeEditableGateway(
        segment_assets={
            "seg-2": _segment_asset(segment_id="seg-2", render_version=2, left=[0.5], core=[2.0], right=[2.1]),
        },
        boundary_audio_by_edge_id={"edge-seg-1-seg-2": [0.9]},
    )
    reusable_exact_segment = _segment_asset(segment_id="seg-1", render_version=1, left=[0.1], core=[0.2, 0.3], right=[0.4])

    class _MissingBaseAssetAccessor(_ReadonlyAssetAccessor):
        def load_segment_asset(self, render_asset_id: str) -> SegmentRenderAssetPayload:
            if render_asset_id == "missing-base-seg-1":
                self.loaded_segments.append(render_asset_id)
                raise FileNotFoundError(render_asset_id)
            return super().load_segment_asset(render_asset_id)

    asset_accessor = _MissingBaseAssetAccessor(
        block_asset=BlockCompositionAssetPayload(
            block_id="block-1",
            block_asset_id="block-asset-old",
            segment_ids=["seg-1", "seg-2"],
            sample_rate=4,
            audio=np.asarray([0.1, 0.2, 0.3, 0.9, 0.0, 0.0, 0.6, 0.7, 0.8], dtype=np.float32),
            audio_sample_count=9,
            segment_entries=[
                SegmentCompositionEntry(
                    segment_id="seg-1",
                    audio_sample_span=(0, 3),
                    render_asset_id=reusable_exact_segment.render_asset_id,
                    base_render_asset_id="missing-base-seg-1",
                ),
                SegmentCompositionEntry(segment_id="seg-2", audio_sample_span=(6, 9), render_asset_id="render-seg-2-v1"),
            ],
        ),
        segment_assets={reusable_exact_segment.render_asset_id: reusable_exact_segment},
    )

    result = GPTSoVITSLocalAdapter(
        editable_gateway=gateway,
        composition_builder=CompositionBuilder(sample_rate=4),
        reusable_asset_accessor=asset_accessor,
    ).render_block(request)

    assert asset_accessor.loaded_blocks == ["block-asset-old"]
    assert asset_accessor.loaded_segments == ["missing-base-seg-1", reusable_exact_segment.render_asset_id]
    assert [segment_id for segment_id, _ in gateway.segment_calls] == ["seg-2"]
    assert result.join_report is not None
    assert result.join_report.applied_mode == "prefer_enhanced"
    assert result.join_report.enhancement_applied is True


def test_gpt_sovits_local_adapter_builds_boundary_context_when_enhanced_edge_uses_only_reused_segments():
    from backend.app.inference.adapters.gpt_sovits_local_adapter import GPTSoVITSLocalAdapter

    request = _build_request(
        segments=[
            _segment_request(
                "seg-1",
                1,
                voice_binding_id="binding-a",
                voice_id="voice-a",
                model_key="model-a",
                model_instance_id="model-a",
                preset_id="preset-a",
                binding_fingerprint="binding-a",
                reference_id="ref-a",
            ),
            _segment_request(
                "seg-2",
                2,
                voice_binding_id="binding-a",
                voice_id="voice-a",
                model_key="model-a",
                model_instance_id="model-a",
                preset_id="preset-a",
                binding_fingerprint="binding-a",
                reference_id="ref-a",
            ),
        ],
        dirty_context=DirtyContext(
            dirty_segment_ids=[],
            dirty_edge_ids=["edge-seg-1-seg-2"],
            previous_block_asset_id="block-asset-old",
            reuse_policy="prefer_reuse",
        ),
    )
    reusable_left = _segment_asset(segment_id="seg-1", render_version=1, left=[0.1], core=[0.2, 0.3], right=[0.4])
    reusable_right = _segment_asset(segment_id="seg-2", render_version=1, left=[0.5], core=[0.6], right=[0.7, 0.8])
    gateway = _FakeEditableGateway(
        segment_assets={},
        boundary_audio_by_edge_id={"edge-seg-1-seg-2": [0.9]},
    )
    asset_accessor = _ReadonlyAssetAccessor(
        block_asset=BlockCompositionAssetPayload(
            block_id="block-1",
            block_asset_id="block-asset-old",
            segment_ids=["seg-1", "seg-2"],
            sample_rate=4,
            audio=np.asarray([0.1, 0.2, 0.3, 0.9, 0.0, 0.0, 0.6, 0.7, 0.8], dtype=np.float32),
            audio_sample_count=9,
            segment_entries=[
                SegmentCompositionEntry(segment_id="seg-1", audio_sample_span=(0, 3), render_asset_id=reusable_left.render_asset_id),
                SegmentCompositionEntry(segment_id="seg-2", audio_sample_span=(6, 9), render_asset_id=reusable_right.render_asset_id),
            ],
        ),
        segment_assets={
            reusable_left.render_asset_id: reusable_left,
            reusable_right.render_asset_id: reusable_right,
        },
    )

    result = GPTSoVITSLocalAdapter(
        editable_gateway=gateway,
        composition_builder=CompositionBuilder(sample_rate=4),
        reusable_asset_accessor=asset_accessor,
    ).render_block(request)

    assert gateway.segment_calls == []
    assert len(gateway.context_calls) == 1
    assert gateway.boundary_calls == [("seg-1", "seg-2", "edge-seg-1-seg-2", gateway.built_contexts[0])]
    assert result.join_report is not None
    assert result.join_report.enhancement_applied is True


def test_gpt_sovits_local_adapter_passes_request_render_version_to_legacy_segment_render():
    from backend.app.inference.adapters.gpt_sovits_local_adapter import GPTSoVITSLocalAdapter

    request = _build_request(
        segments=[
            _segment_request(
                "seg-1",
                1,
                voice_binding_id="binding-a",
                voice_id="voice-a",
                model_key="model-a",
                model_instance_id="model-a",
                preset_id="preset-a",
                binding_fingerprint="binding-a",
                reference_id="ref-a",
            ),
            _segment_request(
                "seg-2",
                2,
                voice_binding_id="binding-a",
                voice_id="voice-a",
                model_key="model-a",
                model_instance_id="model-a",
                preset_id="preset-a",
                binding_fingerprint="binding-a",
                reference_id="ref-a",
            ),
        ],
        join_policy="natural",
        pause_duration_seconds=0.0,
    )
    object.__setattr__(request.block.segments[0], "render_version", 7)
    object.__setattr__(request.block.segments[1], "render_version", 11)
    gateway = _FakeEditableGateway(
        segment_assets={
            "seg-1": _segment_asset(segment_id="seg-1", render_version=7, left=[0.1], core=[0.2], right=[0.3]),
            "seg-2": _segment_asset(segment_id="seg-2", render_version=11, left=[0.4], core=[0.5], right=[0.6]),
        },
        boundary_audio_by_edge_id={"edge-seg-1-seg-2": [0.7]},
    )

    GPTSoVITSLocalAdapter(
        editable_gateway=gateway,
        composition_builder=CompositionBuilder(sample_rate=4),
    ).render_block(request)

    assert [segment.render_version for segment in gateway.rendered_segments] == [7, 11]


def test_gpt_sovits_local_adapter_force_full_render_and_mixed_binding_reuse_both_fall_back_to_full_rerender():
    from backend.app.inference.adapters.gpt_sovits_local_adapter import GPTSoVITSLocalAdapter

    base_segments = [
        _segment_request(
            "seg-1",
            1,
            voice_binding_id="binding-a",
            voice_id="voice-a",
            model_key="model-a",
            model_instance_id="model-a",
            preset_id="preset-a",
            binding_fingerprint="binding-a",
            reference_id="ref-a",
        ),
        _segment_request(
            "seg-2",
            2,
            voice_binding_id="binding-b",
            voice_id="voice-b",
            model_key="model-b",
            model_instance_id="model-b",
            preset_id="preset-b",
            binding_fingerprint="binding-b",
            reference_id="ref-b",
        ),
    ]
    segment_assets = {
        "seg-1": _segment_asset(segment_id="seg-1", render_version=2, left=[0.1], core=[1.0], right=[1.1]),
        "seg-2": _segment_asset(segment_id="seg-2", render_version=2, left=[0.2], core=[2.0], right=[2.1]),
    }
    block_asset = BlockCompositionAssetPayload(
        block_id="block-1",
        block_asset_id="block-asset-old",
        segment_ids=["seg-1", "seg-2"],
        sample_rate=4,
        audio=np.asarray([0.9, 0.9], dtype=np.float32),
        audio_sample_count=2,
        segment_entries=[
            SegmentCompositionEntry(segment_id="seg-1", audio_sample_span=(0, 1), render_asset_id="render-seg-1-v1"),
            SegmentCompositionEntry(segment_id="seg-2", audio_sample_span=(1, 2), render_asset_id="render-seg-2-v1"),
        ],
    )
    asset_accessor = _ReadonlyAssetAccessor(block_asset=block_asset, segment_assets={})

    force_full_request = _build_request(
        segments=base_segments,
        dirty_context=DirtyContext(
            dirty_segment_ids=[],
            dirty_edge_ids=[],
            previous_block_asset_id="block-asset-old",
            reuse_policy="force_full_render",
        ),
    )
    mixed_binding_request = _build_request(
        segments=base_segments,
        dirty_context=DirtyContext(
            dirty_segment_ids=["seg-2"],
            dirty_edge_ids=[],
            previous_block_asset_id="block-asset-old",
            reuse_policy="prefer_reuse",
        ),
    )

    force_full_gateway = _FakeEditableGateway(segment_assets=segment_assets)
    mixed_binding_gateway = _FakeEditableGateway(segment_assets=segment_assets)

    GPTSoVITSLocalAdapter(
        editable_gateway=force_full_gateway,
        composition_builder=CompositionBuilder(sample_rate=4),
        reusable_asset_accessor=asset_accessor,
    ).render_block(force_full_request)
    GPTSoVITSLocalAdapter(
        editable_gateway=mixed_binding_gateway,
        composition_builder=CompositionBuilder(sample_rate=4),
        reusable_asset_accessor=asset_accessor,
    ).render_block(mixed_binding_request)

    assert [segment_id for segment_id, _ in force_full_gateway.segment_calls] == ["seg-1", "seg-2"]
    assert [segment_id for segment_id, _ in mixed_binding_gateway.segment_calls] == ["seg-1", "seg-2"]


def test_gpt_sovits_local_adapter_keeps_business_dependencies_outside_adapter_boundary():
    from backend.app.inference.adapters import gpt_sovits_local_adapter as adapter_module
    from backend.app.inference.adapters.gpt_sovits_local_adapter import GPTSoVITSLocalAdapter

    source = inspect.getsource(adapter_module)
    assert "RenderConfigResolver" not in source
    assert "EditSessionRepository" not in source
    assert "EditSessionRuntime" not in source
    assert "CheckpointService" not in source

    adapter = GPTSoVITSLocalAdapter(editable_gateway=_FakeEditableGateway(segment_assets={}))
    assert "_render_config_resolver" not in vars(adapter)
    assert "_repository" not in vars(adapter)
    assert "_runtime" not in vars(adapter)
    assert "_checkpoint_service" not in vars(adapter)
