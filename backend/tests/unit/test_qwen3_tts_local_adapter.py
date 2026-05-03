from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from backend.app.inference.block_adapter_types import (
    BlockRenderRequest,
    BlockRequestBlock,
    BlockRequestSegment,
    DirtyContext,
    EdgeControl,
    ResolvedModelBinding,
)
from backend.app.inference.editable_types import BlockCompositionAssetPayload, SegmentCompositionEntry, SegmentRenderAssetPayload
from backend.app.services.composition_builder import CompositionBuilder


class _FakeQwenRuntime:
    def __init__(self, outputs_by_segment_id: dict[str, tuple[list[float], int]]) -> None:
        self.outputs_by_segment_id = outputs_by_segment_id
        self.calls: list[object] = []

    def render_segment(self, request):
        self.calls.append(request)
        audio, sample_rate = self.outputs_by_segment_id[request.segment_id]
        return SimpleNamespace(
            segment_id=request.segment_id,
            audio=np.asarray(audio, dtype=np.float32),
            sample_rate=sample_rate,
            trace={"generation_mode": request.generation_mode},
        )


class _ReadonlyAssetAccessor:
    def __init__(self, *, block_asset: BlockCompositionAssetPayload, segment_assets: dict[str, SegmentRenderAssetPayload]) -> None:
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


def _segment_asset(*, segment_id: str, render_version: int, core: list[float]) -> SegmentRenderAssetPayload:
    core_audio = np.asarray(core, dtype=np.float32)
    return SegmentRenderAssetPayload(
        render_asset_id=f"render-{segment_id}-v{render_version}",
        segment_id=segment_id,
        render_version=render_version,
        sample_rate=4,
        semantic_tokens=[],
        phone_ids=[],
        decoder_frame_count=0,
        audio_sample_count=int(core_audio.size),
        left_margin_sample_count=0,
        core_sample_count=int(core_audio.size),
        right_margin_sample_count=0,
        left_margin_audio=np.zeros(0, dtype=np.float32),
        core_audio=core_audio,
        right_margin_audio=np.zeros(0, dtype=np.float32),
        trace={"source": "runtime"},
    )


def _resolved_model_binding(*, binding_fingerprint: str, preset_id: str = "vivian") -> ResolvedModelBinding:
    return ResolvedModelBinding(
        adapter_id="qwen3_tts_local",
        model_instance_id="ws_qwen:main:default",
        preset_id=preset_id,
        resolved_assets={
            "model_dir": {
                "path": "F:/models/qwen3",
                "fingerprint": "model-dir-fp",
            }
        },
        resolved_reference={
            "reference_id": "ref-1",
            "audio_uri": "F:/refs/demo.wav",
            "text": "This is a reference clip.",
            "language": "English",
            "source": "preset",
            "fingerprint": "ref-fp",
        },
        resolved_parameters={
            "speed": 1.0,
            "top_k": 20,
            "top_p": 0.8,
            "temperature": 0.7,
            "noise_scale": 0.35,
        },
        preset_defaults={
            "speaker": "Vivian",
            "language": "Chinese",
            "instruct": "平静地说",
        },
        preset_fixed_fields={
            "generation_mode": "custom_voice",
        },
        secret_handles={},
        binding_fingerprint=binding_fingerprint,
    )


def _segment_request(segment_id: str, order_key: int, *, binding_fingerprint: str) -> BlockRequestSegment:
    binding = _resolved_model_binding(binding_fingerprint=binding_fingerprint)
    return BlockRequestSegment(
        segment_id=segment_id,
        order_key=order_key,
        text=f"{segment_id} 文本。",
        language="zh",
        terminal_punctuation="。",
        voice_binding_id="binding-a",
        render_profile_id="profile-1",
        render_version=1,
        resolved_binding={
            "voice_binding_id": "binding-a",
            "voice_id": "qwen_voice",
            "model_key": "ws_qwen:main:default",
            "model_instance_id": "ws_qwen:main:default",
            "preset_id": "vivian",
        },
        resolved_model_binding=binding.model_dump(mode="json"),
        resolved_reference=binding.resolved_reference,
    )


def _build_request(*, segments: list[BlockRequestSegment], dirty_context: DirtyContext | None = None) -> BlockRenderRequest:
    first_binding = ResolvedModelBinding.model_validate(segments[0].resolved_model_binding)
    edge_controls: list[EdgeControl] = []
    if len(segments) > 1:
        for left, right in zip(segments, segments[1:], strict=False):
            edge_controls.append(
                EdgeControl(
                    edge_id=f"edge-{left.segment_id}-{right.segment_id}",
                    left_segment_id=left.segment_id,
                    right_segment_id=right.segment_id,
                    pause_duration_seconds=0.5,
                    join_policy_override="prefer_enhanced",
                    locked=False,
                )
            )
    return BlockRenderRequest(
        request_id="req-1",
        document_id="doc-1",
        render_scope="segment",
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
        edge_controls=edge_controls,
        dirty_context=dirty_context,
        join_policy="prefer_enhanced",
    )


def test_qwen3_tts_local_adapter_capabilities_cover_phase8_contract():
    from backend.app.inference.adapters.qwen3_tts_local_adapter import Qwen3TTSLocalAdapter

    capabilities = Qwen3TTSLocalAdapter.capabilities()

    assert capabilities.block_render is True
    assert capabilities.exact_segment_output is True
    assert capabilities.segment_level_voice_binding is True
    assert capabilities.incremental_render is True
    assert capabilities.local_gpu_runtime is True
    assert capabilities.cancellable is True
    assert capabilities.boundary_enhancement is False
    assert capabilities.native_join_fusion is False


def test_qwen3_tts_local_adapter_renders_multi_segment_block_with_exact_spans_and_crossfade_only_boundaries():
    from backend.app.inference.adapters.qwen3_tts_local_adapter import Qwen3TTSLocalAdapter

    request = _build_request(
        segments=[
            _segment_request("seg-1", 1, binding_fingerprint="binding-a"),
            _segment_request("seg-2", 2, binding_fingerprint="binding-a"),
        ]
    )
    runtime = _FakeQwenRuntime(
        outputs_by_segment_id={
            "seg-1": ([0.1, 0.2], 4),
            "seg-2": ([0.3], 4),
        }
    )
    callback_events: list[tuple[str, bool]] = []

    result = Qwen3TTSLocalAdapter(
        runtime=runtime,
        composition_builder=CompositionBuilder(sample_rate=4),
        segment_asset_callback=lambda asset, request_segment, reused: callback_events.append((request_segment.segment_id, reused)),
    ).render_block(request)

    assert [call.segment_id for call in runtime.calls] == ["seg-1", "seg-2"]
    assert callback_events == [("seg-1", False), ("seg-2", False)]
    assert np.allclose(result.audio, [0.1, 0.2, 0.0, 0.0, 0.3])
    assert [(span.segment_id, span.sample_start, span.sample_end) for span in result.segment_spans] == [
        ("seg-1", 0, 2),
        ("seg-2", 4, 5),
    ]
    assert result.boundary_results[0].mode == "fallback"
    assert result.join_report is not None
    assert result.join_report.applied_mode == "preserve_pause"
    assert result.scope_feedback is not None
    assert result.scope_feedback.actual_scope == "segment"


def test_qwen3_tts_local_adapter_reuses_clean_segments_from_previous_block():
    from backend.app.inference.adapters.qwen3_tts_local_adapter import Qwen3TTSLocalAdapter

    request = _build_request(
        segments=[
            _segment_request("seg-1", 1, binding_fingerprint="binding-a"),
            _segment_request("seg-2", 2, binding_fingerprint="binding-a"),
        ],
        dirty_context=DirtyContext(
            dirty_segment_ids=["seg-2"],
            dirty_edge_ids=["edge-seg-1-seg-2"],
            previous_block_asset_id="block-asset-old",
            reuse_policy="prefer_reuse",
        ),
    )
    runtime = _FakeQwenRuntime(outputs_by_segment_id={"seg-2": ([0.5, 0.6], 4)})
    reusable_segment = _segment_asset(segment_id="seg-1", render_version=1, core=[0.1, 0.2])
    asset_accessor = _ReadonlyAssetAccessor(
        block_asset=BlockCompositionAssetPayload(
            block_id="block-1",
            block_asset_id="block-asset-old",
            segment_ids=["seg-1", "seg-2"],
            sample_rate=4,
            audio=np.asarray([0.1, 0.2, 0.0, 0.0, 0.3], dtype=np.float32),
            audio_sample_count=5,
            segment_entries=[
                SegmentCompositionEntry(
                    segment_id="seg-1",
                    audio_sample_span=(0, 2),
                    render_asset_id=reusable_segment.render_asset_id,
                ),
                SegmentCompositionEntry(
                    segment_id="seg-2",
                    audio_sample_span=(4, 5),
                    render_asset_id="render-seg-2-v1",
                ),
            ],
        ),
        segment_assets={reusable_segment.render_asset_id: reusable_segment},
    )
    callback_events: list[tuple[str, bool]] = []

    result = Qwen3TTSLocalAdapter(
        runtime=runtime,
        composition_builder=CompositionBuilder(sample_rate=4),
        reusable_asset_accessor=asset_accessor,
        segment_asset_callback=lambda asset, request_segment, reused: callback_events.append((request_segment.segment_id, reused)),
    ).render_block(request)

    assert asset_accessor.loaded_blocks == ["block-asset-old"]
    assert asset_accessor.loaded_segments == [reusable_segment.render_asset_id]
    assert [call.segment_id for call in runtime.calls] == ["seg-2"]
    assert callback_events == [("seg-1", True), ("seg-2", False)]
    assert np.allclose(result.audio, [0.1, 0.2, 0.0, 0.0, 0.5, 0.6])


def test_qwen3_tts_local_adapter_honors_cancellation_checker():
    from backend.app.inference.adapters.qwen3_tts_local_adapter import Qwen3TTSLocalAdapter

    request = _build_request(segments=[_segment_request("seg-1", 1, binding_fingerprint="binding-a")])
    runtime = _FakeQwenRuntime(outputs_by_segment_id={"seg-1": ([0.1], 4)})

    with pytest.raises(RuntimeError, match="cancelled"):
        Qwen3TTSLocalAdapter(
            runtime=runtime,
            cancellation_checker=lambda: True,
        ).render_block(request)
