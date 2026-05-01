from datetime import datetime, timezone

import pytest

from backend.app.inference.adapter_definition import (
    AdapterBlockLimits,
    AdapterDefinition,
)
from backend.app.inference.block_adapter_errors import BlockAdapterError
from backend.app.inference.block_adapter_registry import AdapterRegistry
from backend.app.inference.block_adapter_types import AdapterCapabilities
from backend.app.inference.block_adapter_types import ResolvedModelBinding
from backend.app.inference.editable_types import RenderBlock
from backend.app.schemas.edit_session import (
    DocumentSnapshot,
    EditableEdge,
    EditableSegment,
    RenderProfile,
    TimelineBlockEntry,
    TimelineManifest,
    VoiceBinding,
)
from backend.app.services.block_render_request_builder import BlockRenderRequestBuilder
from backend.app.services.render_config_resolver import (
    ResolvedEdgeConfig,
    ResolvedReferenceSelection,
    ResolvedSegmentConfig,
)


def _segment(
    segment_id: str,
    order_key: int,
    voice_binding_id: str,
    *,
    stem: str | None = None,
    terminal_raw: str = "。",
) -> EditableSegment:
    return EditableSegment(
        segment_id=segment_id,
        document_id="doc-1",
        order_key=order_key,
        previous_segment_id=f"seg-{order_key - 1}" if order_key > 1 else None,
        next_segment_id=f"seg-{order_key + 1}" if order_key < 9 else None,
        stem=stem or f"第{order_key}句",
        text_language="zh",
        terminal_raw=terminal_raw,
        terminal_source="original",
        detected_language="zh",
        inference_exclusion_reason="none",
        render_version=1,
        render_asset_id=f"render-{segment_id}-v1",
        voice_binding_id=voice_binding_id,
        render_profile_id="profile-session",
        assembled_audio_span=(0, 10),
    )


def _binding(
    binding_id: str,
    voice_id: str,
    model_key: str,
    *,
    model_instance_id: str,
    preset_id: str,
) -> VoiceBinding:
    return VoiceBinding(
        voice_binding_id=binding_id,
        scope="segment",
        voice_id=voice_id,
        model_key=model_key,
        model_instance_id=model_instance_id,
        preset_id=preset_id,
    )


def _edge(left_segment_id: str, right_segment_id: str, *, strategy: str, pause: float = 0.3) -> EditableEdge:
    return EditableEdge(
        edge_id=f"edge-{left_segment_id}-{right_segment_id}",
        document_id="doc-1",
        left_segment_id=left_segment_id,
        right_segment_id=right_segment_id,
        pause_duration_seconds=pause,
        boundary_strategy=strategy,
        boundary_strategy_locked=False,
    )


def _snapshot(
    *,
    segments: list[EditableSegment],
    edges: list[EditableEdge],
    voice_bindings: list[VoiceBinding],
) -> DocumentSnapshot:
    return DocumentSnapshot(
        snapshot_id="head-1",
        document_id="doc-1",
        snapshot_kind="head",
        document_version=1,
        segment_ids=[segment.segment_id for segment in segments],
        edge_ids=[edge.edge_id for edge in edges],
        render_profiles=[RenderProfile(render_profile_id="profile-session", scope="session", name="session")],
        voice_bindings=voice_bindings,
        default_render_profile_id="profile-session",
        default_voice_binding_id=voice_bindings[0].voice_binding_id,
        segments=segments,
        edges=edges,
    )


def _timeline(block_asset_id: str, segment_ids: list[str]) -> TimelineManifest:
    return TimelineManifest(
        timeline_manifest_id="timeline-1",
        document_id="doc-1",
        document_version=1,
        timeline_version=1,
        sample_rate=32000,
        playable_sample_span=(0, 100),
        block_entries=[
            TimelineBlockEntry(
                block_asset_id=block_asset_id,
                segment_ids=segment_ids,
                start_sample=0,
                end_sample=100,
                audio_sample_count=100,
                audio_url=f"/blocks/{block_asset_id}",
            )
        ],
        created_at=datetime.now(timezone.utc),
    )


def _render_block(segment_ids: list[str], *, sample_count: int = 6400) -> RenderBlock:
    return RenderBlock(
        block_id=f"block-{'-'.join(segment_ids)}",
        segment_ids=segment_ids,
        start_order_key=1,
        end_order_key=len(segment_ids),
        estimated_sample_count=sample_count,
    )


def _resolved_model_binding(
    *,
    adapter_id: str,
    model_instance_id: str,
    preset_id: str,
    binding_fingerprint: str,
) -> ResolvedModelBinding:
    return ResolvedModelBinding(
        adapter_id=adapter_id,
        model_instance_id=model_instance_id,
        preset_id=preset_id,
        resolved_assets={
            "gpt_weight": f"weights/{model_instance_id}-{preset_id}.ckpt",
        },
        resolved_reference={
            "reference_id": f"ref-{preset_id}",
            "audio_uri": f"managed://{preset_id}.wav",
            "text": "参考文本",
            "language": "zh",
            "source": "preset",
            "fingerprint": f"ref-fp-{preset_id}",
        },
        resolved_parameters={"speed": 1.0},
        secret_handles={},
        binding_fingerprint=binding_fingerprint,
    )


def _resolved_segment(
    segment: EditableSegment,
    binding: VoiceBinding,
    *,
    adapter_id: str,
    model_instance_id: str,
    preset_id: str,
    binding_fingerprint: str,
    reference_fingerprint: str | None = None,
) -> ResolvedSegmentConfig:
    return ResolvedSegmentConfig(
        segment=segment,
        render_profile=RenderProfile(
            render_profile_id="profile-session",
            scope="session",
            name="session",
            speed=1.0,
            top_k=15,
            top_p=1.0,
            temperature=1.0,
            noise_scale=0.35,
            reference_text="参考文本",
            reference_language="zh",
            reference_audio_path="preset.wav",
        ),
        voice_binding=binding,
        render_context_fingerprint=f"ctx-{segment.segment_id}",
        model_cache_key=binding_fingerprint,
        resolved_model_binding=_resolved_model_binding(
            adapter_id=adapter_id,
            model_instance_id=model_instance_id,
            preset_id=preset_id,
            binding_fingerprint=binding_fingerprint,
        ),
        resolved_reference=ResolvedReferenceSelection(
            binding_key=f"{binding.voice_id}:{binding.model_key}",
            source="preset",
            reference_scope="voice_preset",
            reference_identity=f"{binding.voice_id}:preset",
            reference_audio_path="preset.wav",
            reference_audio_fingerprint=reference_fingerprint or f"audio-{segment.segment_id}",
            reference_text="参考文本",
            reference_text_fingerprint=f"text-{segment.segment_id}",
            reference_language="zh",
        ),
    )


def _resolved_edge(edge: EditableEdge, left: VoiceBinding, right: VoiceBinding, strategy: str) -> ResolvedEdgeConfig:
    return ResolvedEdgeConfig(
        edge=edge,
        left_binding=left,
        right_binding=right,
        effective_boundary_strategy=strategy,
    )


def _adapter_registry(*definitions: AdapterDefinition) -> AdapterRegistry:
    registry = AdapterRegistry()
    for definition in definitions:
        registry.register(definition)
    return registry


def _adapter_definition(
    adapter_id: str,
    *,
    segment_level_voice_binding: bool = True,
    incremental_render: bool = False,
    max_segment_count: int | None = 50,
    max_block_chars: int | None = 300,
) -> AdapterDefinition:
    return AdapterDefinition(
        adapter_id=adapter_id,
        display_name=adapter_id,
        adapter_family=adapter_id.split("_", 1)[0],
        runtime_kind="local_in_process",
        capabilities=AdapterCapabilities(
            block_render=True,
            exact_segment_output=True,
            segment_level_voice_binding=segment_level_voice_binding,
            incremental_render=incremental_render,
        ),
        block_limits=AdapterBlockLimits(
            max_block_seconds=40,
            max_block_chars=max_block_chars,
            max_segment_count=max_segment_count,
            max_payload_bytes=1024 * 1024,
        ),
    )


def test_block_render_request_builder_sorts_segments_and_builds_stable_block_text():
    seg2 = _segment("seg-2", 2, "binding-a")
    seg1 = _segment("seg-1", 1, "binding-a", terminal_raw="！")
    seg1.render_version = 4
    seg2.render_version = 6
    binding = _binding(
        "binding-a",
        "voice-a",
        "model-a",
        model_instance_id="model-1",
        preset_id="preset-1",
    )
    snapshot = _snapshot(segments=[seg2, seg1], edges=[], voice_bindings=[binding])
    builder = BlockRenderRequestBuilder(adapter_registry=_adapter_registry(_adapter_definition("gpt_sovits_local")))

    requests = builder.build_requests(
        snapshot=snapshot,
        blocks=[_render_block(["seg-2", "seg-1"])],
        resolved_segments={
            "seg-1": _resolved_segment(
                seg1,
                binding,
                adapter_id="gpt_sovits_local",
                model_instance_id="model-1",
                preset_id="preset-1",
                binding_fingerprint="binding-a",
            ),
            "seg-2": _resolved_segment(
                seg2,
                binding,
                adapter_id="gpt_sovits_local",
                model_instance_id="model-1",
                preset_id="preset-1",
                binding_fingerprint="binding-a",
            ),
        },
        resolved_edges={},
        target_segment_ids={"seg-1", "seg-2"},
        target_edge_ids=set(),
        previous_timeline=None,
        reuse_policy="force_full_render",
    )

    assert len(requests) == 1
    request = requests[0]
    assert request.block.segment_ids == ["seg-1", "seg-2"]
    assert [segment.segment_id for segment in request.block.segments] == ["seg-1", "seg-2"]
    assert request.block.block_text == "第1句！\n第2句。"
    assert request.block.segments[0].resolved_binding == {
        "voice_binding_id": "binding-a",
        "voice_id": "voice-a",
        "model_key": "model-a",
        "model_instance_id": "model-1",
        "preset_id": "preset-1",
    }
    assert [segment.render_version for segment in request.block.segments] == [4, 6]
    assert request.block.block_text == requests[0].block.block_text


def test_block_render_request_builder_maps_edge_controls_join_policy_and_dirty_context():
    seg1 = _segment("seg-1", 1, "binding-a")
    seg2 = _segment("seg-2", 2, "binding-a")
    binding = _binding(
        "binding-a",
        "voice-a",
        "model-a",
        model_instance_id="model-1",
        preset_id="preset-1",
    )
    edge = _edge("seg-1", "seg-2", strategy="latent_overlap_then_equal_power_crossfade")
    snapshot = _snapshot(segments=[seg1, seg2], edges=[edge], voice_bindings=[binding])
    builder = BlockRenderRequestBuilder(
        adapter_registry=_adapter_registry(
            _adapter_definition("gpt_sovits_local", incremental_render=True),
        )
    )

    requests = builder.build_requests(
        snapshot=snapshot,
        blocks=[_render_block(["seg-1", "seg-2"])],
        resolved_segments={
            "seg-1": _resolved_segment(
                seg1,
                binding,
                adapter_id="gpt_sovits_local",
                model_instance_id="model-1",
                preset_id="preset-1",
                binding_fingerprint="binding-a",
            ),
            "seg-2": _resolved_segment(
                seg2,
                binding,
                adapter_id="gpt_sovits_local",
                model_instance_id="model-1",
                preset_id="preset-1",
                binding_fingerprint="binding-a",
            ),
        },
        resolved_edges={
            edge.edge_id: _resolved_edge(
                edge,
                binding,
                binding,
                "latent_overlap_then_equal_power_crossfade",
            )
        },
        target_segment_ids={"seg-2"},
        target_edge_ids={edge.edge_id},
        previous_timeline=_timeline("block-asset-old", ["seg-1", "seg-2"]),
        reuse_policy="prefer_reuse",
    )

    request = requests[0]
    assert request.join_policy == "prefer_enhanced"
    assert request.edge_controls[0].join_policy_override == "prefer_enhanced"
    assert request.edge_controls[0].pause_duration_seconds == 0.3
    assert request.dirty_context is not None
    assert request.dirty_context.previous_block_asset_id == "block-asset-old"
    assert request.dirty_context.dirty_segment_ids == ["seg-2"]
    assert request.dirty_context.dirty_edge_ids == [edge.edge_id]
    assert request.dirty_context.reuse_policy == "prefer_reuse"


def test_block_render_request_builder_prefers_segment_scope_window_for_dirty_middle_segment():
    seg1 = _segment("seg-1", 1, "binding-a")
    seg2 = _segment("seg-2", 2, "binding-a")
    seg3 = _segment("seg-3", 3, "binding-a")
    seg4 = _segment("seg-4", 4, "binding-a")
    binding = _binding(
        "binding-a",
        "voice-a",
        "model-a",
        model_instance_id="model-1",
        preset_id="preset-1",
    )
    edge12 = _edge("seg-1", "seg-2", strategy="latent_overlap_then_equal_power_crossfade")
    edge23 = _edge("seg-2", "seg-3", strategy="latent_overlap_then_equal_power_crossfade")
    edge34 = _edge("seg-3", "seg-4", strategy="crossfade_only")
    snapshot = _snapshot(
        segments=[seg1, seg2, seg3, seg4],
        edges=[edge12, edge23, edge34],
        voice_bindings=[binding],
    )
    builder = BlockRenderRequestBuilder(
        adapter_registry=_adapter_registry(
            _adapter_definition("gpt_sovits_local", incremental_render=True, segment_level_voice_binding=True),
        )
    )

    requests = builder.build_requests(
        snapshot=snapshot,
        blocks=[_render_block(["seg-1", "seg-2", "seg-3", "seg-4"])],
        resolved_segments={
            "seg-1": _resolved_segment(
                seg1,
                binding,
                adapter_id="gpt_sovits_local",
                model_instance_id="model-1",
                preset_id="preset-1",
                binding_fingerprint="binding-a",
                reference_fingerprint="ref-a",
            ),
            "seg-2": _resolved_segment(
                seg2,
                binding,
                adapter_id="gpt_sovits_local",
                model_instance_id="model-1",
                preset_id="preset-1",
                binding_fingerprint="binding-a",
                reference_fingerprint="ref-a",
            ),
            "seg-3": _resolved_segment(
                seg3,
                binding,
                adapter_id="gpt_sovits_local",
                model_instance_id="model-1",
                preset_id="preset-1",
                binding_fingerprint="binding-a",
                reference_fingerprint="ref-a",
            ),
            "seg-4": _resolved_segment(
                seg4,
                binding,
                adapter_id="gpt_sovits_local",
                model_instance_id="model-1",
                preset_id="preset-1",
                binding_fingerprint="binding-a",
                reference_fingerprint="ref-a",
            ),
        },
        resolved_edges={
            edge12.edge_id: _resolved_edge(edge12, binding, binding, "latent_overlap_then_equal_power_crossfade"),
            edge23.edge_id: _resolved_edge(edge23, binding, binding, "latent_overlap_then_equal_power_crossfade"),
            edge34.edge_id: _resolved_edge(edge34, binding, binding, "crossfade_only"),
        },
        target_segment_ids={"seg-2"},
        target_edge_ids={edge12.edge_id, edge23.edge_id},
        previous_timeline=_timeline("block-asset-old", ["seg-1", "seg-2", "seg-3", "seg-4"]),
        reuse_policy="prefer_reuse",
        render_scope="segment",
    )

    assert [(request.render_scope, request.block.segment_ids) for request in requests] == [
        ("segment", ["seg-1", "seg-2", "seg-3"]),
        ("segment", ["seg-4"]),
    ]
    assert requests[0].dirty_context is not None
    assert requests[0].dirty_context.dirty_segment_ids == ["seg-2"]
    assert requests[0].dirty_context.dirty_edge_ids == [edge12.edge_id, edge23.edge_id]
    assert requests[1].dirty_context is not None
    assert requests[1].dirty_context.dirty_segment_ids == []
    assert requests[1].dirty_context.dirty_edge_ids == []


def test_block_render_request_builder_splits_block_by_adapter_and_binding_homogeneity():
    seg1 = _segment("seg-1", 1, "binding-a")
    seg2 = _segment("seg-2", 2, "binding-b")
    seg3 = _segment("seg-3", 3, "binding-c")
    binding_a = _binding(
        "binding-a",
        "voice-a",
        "model-a",
        model_instance_id="model-1",
        preset_id="preset-1",
    )
    binding_b = _binding(
        "binding-b",
        "voice-b",
        "model-b",
        model_instance_id="model-2",
        preset_id="preset-2",
    )
    binding_c = _binding(
        "binding-c",
        "voice-c",
        "model-c",
        model_instance_id="model-3",
        preset_id="preset-3",
    )
    snapshot = _snapshot(
        segments=[seg1, seg2, seg3],
        edges=[],
        voice_bindings=[binding_a, binding_b, binding_c],
    )
    builder = BlockRenderRequestBuilder(
        adapter_registry=_adapter_registry(
            _adapter_definition("gpt_sovits_local", segment_level_voice_binding=False, max_segment_count=10),
            _adapter_definition("external_http_tts", segment_level_voice_binding=True, max_segment_count=10),
        )
    )

    requests = builder.build_requests(
        snapshot=snapshot,
        blocks=[_render_block(["seg-1", "seg-2", "seg-3"])],
        resolved_segments={
            "seg-1": _resolved_segment(
                seg1,
                binding_a,
                adapter_id="gpt_sovits_local",
                model_instance_id="model-1",
                preset_id="preset-1",
                binding_fingerprint="binding-a",
            ),
            "seg-2": _resolved_segment(
                seg2,
                binding_b,
                adapter_id="gpt_sovits_local",
                model_instance_id="model-2",
                preset_id="preset-2",
                binding_fingerprint="binding-b",
            ),
            "seg-3": _resolved_segment(
                seg3,
                binding_c,
                adapter_id="external_http_tts",
                model_instance_id="model-3",
                preset_id="preset-3",
                binding_fingerprint="binding-c",
            ),
        },
        resolved_edges={},
        target_segment_ids={"seg-1", "seg-2", "seg-3"},
        target_edge_ids=set(),
        previous_timeline=None,
        reuse_policy="adapter_default",
    )

    assert [request.block.segment_ids for request in requests] == [["seg-1"], ["seg-2"], ["seg-3"]]
    assert [request.model_binding.adapter_id for request in requests] == [
        "gpt_sovits_local",
        "gpt_sovits_local",
        "external_http_tts",
    ]


def test_block_render_request_builder_downgrades_reuse_policy_when_adapter_disables_incremental_render():
    seg1 = _segment("seg-1", 1, "binding-a")
    binding = _binding(
        "binding-a",
        "voice-a",
        "model-a",
        model_instance_id="model-1",
        preset_id="preset-1",
    )
    snapshot = _snapshot(segments=[seg1], edges=[], voice_bindings=[binding])
    builder = BlockRenderRequestBuilder(
        adapter_registry=_adapter_registry(
            _adapter_definition("gpt_sovits_local", incremental_render=False),
        )
    )

    requests = builder.build_requests(
        snapshot=snapshot,
        blocks=[_render_block(["seg-1"])],
        resolved_segments={
            "seg-1": _resolved_segment(
                seg1,
                binding,
                adapter_id="gpt_sovits_local",
                model_instance_id="model-1",
                preset_id="preset-1",
                binding_fingerprint="binding-a",
            )
        },
        resolved_edges={},
        target_segment_ids={"seg-1"},
        target_edge_ids=set(),
        previous_timeline=_timeline("block-asset-old", ["seg-1"]),
        reuse_policy="prefer_reuse",
    )

    assert requests[0].dirty_context is not None
    assert requests[0].dirty_context.reuse_policy == "adapter_default"


def test_block_render_request_builder_splits_chunk_when_segment_level_binding_identity_changes():
    seg1 = _segment("seg-1", 1, "binding-a")
    seg2 = _segment("seg-2", 2, "binding-b")
    binding_a = _binding(
        "binding-a",
        "voice-a",
        "model-a",
        model_instance_id="model-1",
        preset_id="preset-1",
    )
    binding_b = _binding(
        "binding-b",
        "voice-b",
        "model-b",
        model_instance_id="model-2",
        preset_id="preset-2",
    )
    snapshot = _snapshot(segments=[seg1, seg2], edges=[], voice_bindings=[binding_a, binding_b])
    builder = BlockRenderRequestBuilder(
        adapter_registry=_adapter_registry(
            _adapter_definition("gpt_sovits_local", segment_level_voice_binding=True, incremental_render=True),
        )
    )

    requests = builder.build_requests(
        snapshot=snapshot,
        blocks=[_render_block(["seg-1", "seg-2"])],
        resolved_segments={
            "seg-1": _resolved_segment(
                seg1,
                binding_a,
                adapter_id="gpt_sovits_local",
                model_instance_id="model-1",
                preset_id="preset-1",
                binding_fingerprint="binding-a",
                reference_fingerprint="ref-a",
            ),
            "seg-2": _resolved_segment(
                seg2,
                binding_b,
                adapter_id="gpt_sovits_local",
                model_instance_id="model-2",
                preset_id="preset-2",
                binding_fingerprint="binding-b",
                reference_fingerprint="ref-b",
            ),
        },
        resolved_edges={},
        target_segment_ids={"seg-1", "seg-2"},
        target_edge_ids=set(),
        previous_timeline=_timeline("block-asset-old", ["seg-1", "seg-2"]),
        reuse_policy="prefer_reuse",
    )

    assert [request.block.segment_ids for request in requests] == [["seg-1"], ["seg-2"]]
    assert [request.dirty_context.previous_block_asset_id for request in requests] == [
        "block-asset-old",
        "block-asset-old",
    ]


def test_block_render_request_builder_rejects_single_segment_that_exceeds_adapter_limits():
    seg1 = _segment(
        "seg-1",
        1,
        "binding-a",
        stem="这是一段明显超过限制的长文本" * 20,
    )
    binding = _binding(
        "binding-a",
        "voice-a",
        "model-a",
        model_instance_id="model-1",
        preset_id="preset-1",
    )
    snapshot = _snapshot(segments=[seg1], edges=[], voice_bindings=[binding])
    builder = BlockRenderRequestBuilder(
        adapter_registry=_adapter_registry(
            _adapter_definition("gpt_sovits_local", max_block_chars=20),
        )
    )

    with pytest.raises(BlockAdapterError, match="seg-1"):
        builder.build_requests(
            snapshot=snapshot,
            blocks=[_render_block(["seg-1"])],
            resolved_segments={
                "seg-1": _resolved_segment(
                    seg1,
                    binding,
                    adapter_id="gpt_sovits_local",
                    model_instance_id="model-1",
                    preset_id="preset-1",
                    binding_fingerprint="binding-a",
                )
            },
            resolved_edges={},
            target_segment_ids={"seg-1"},
            target_edge_ids=set(),
            previous_timeline=None,
            reuse_policy="force_full_render",
        )


def test_block_render_request_builder_keeps_explicit_dirty_context_for_initialize_requests():
    seg1 = _segment("seg-1", 1, "binding-a")
    binding = _binding(
        "binding-a",
        "voice-a",
        "model-a",
        model_instance_id="model-1",
        preset_id="preset-1",
    )
    snapshot = _snapshot(segments=[seg1], edges=[], voice_bindings=[binding])
    builder = BlockRenderRequestBuilder(
        adapter_registry=_adapter_registry(
            _adapter_definition("gpt_sovits_local", incremental_render=False),
        )
    )

    requests = builder.build_requests(
        snapshot=snapshot,
        blocks=[_render_block(["seg-1"])],
        resolved_segments={
            "seg-1": _resolved_segment(
                seg1,
                binding,
                adapter_id="gpt_sovits_local",
                model_instance_id="model-1",
                preset_id="preset-1",
                binding_fingerprint="binding-a",
            )
        },
        resolved_edges={},
        target_segment_ids=set(),
        target_edge_ids=set(),
        previous_timeline=None,
        reuse_policy="force_full_render",
    )

    assert requests[0].dirty_context is not None
    assert requests[0].dirty_context.previous_block_asset_id is None
    assert requests[0].dirty_context.reuse_policy == "force_full_render"


def test_block_render_request_builder_inherits_previous_block_asset_when_adapter_shrinks_block():
    seg1 = _segment("seg-1", 1, "binding-a")
    seg2 = _segment("seg-2", 2, "binding-a")
    seg3 = _segment("seg-3", 3, "binding-a")
    binding = _binding(
        "binding-a",
        "voice-a",
        "model-a",
        model_instance_id="model-1",
        preset_id="preset-1",
    )
    snapshot = _snapshot(segments=[seg1, seg2, seg3], edges=[], voice_bindings=[binding])
    builder = BlockRenderRequestBuilder(
        adapter_registry=_adapter_registry(
            _adapter_definition("gpt_sovits_local", max_segment_count=2),
        )
    )

    requests = builder.build_requests(
        snapshot=snapshot,
        blocks=[_render_block(["seg-1", "seg-2", "seg-3"])],
        resolved_segments={
            "seg-1": _resolved_segment(
                seg1,
                binding,
                adapter_id="gpt_sovits_local",
                model_instance_id="model-1",
                preset_id="preset-1",
                binding_fingerprint="binding-a",
            ),
            "seg-2": _resolved_segment(
                seg2,
                binding,
                adapter_id="gpt_sovits_local",
                model_instance_id="model-1",
                preset_id="preset-1",
                binding_fingerprint="binding-a",
            ),
            "seg-3": _resolved_segment(
                seg3,
                binding,
                adapter_id="gpt_sovits_local",
                model_instance_id="model-1",
                preset_id="preset-1",
                binding_fingerprint="binding-a",
            ),
        },
        resolved_edges={},
        target_segment_ids={"seg-2"},
        target_edge_ids=set(),
        previous_timeline=_timeline("block-asset-old", ["seg-1", "seg-2", "seg-3"]),
        reuse_policy="prefer_reuse",
    )

    assert [request.block.segment_ids for request in requests] == [["seg-1", "seg-2"], ["seg-3"]]
    assert requests[0].dirty_context is not None
    assert requests[0].dirty_context.previous_block_asset_id == "block-asset-old"
    assert requests[1].dirty_context is not None
    assert requests[1].dirty_context.previous_block_asset_id == "block-asset-old"
