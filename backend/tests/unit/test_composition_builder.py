import numpy as np

from backend.app.inference.editable_types import (
    BlockCompositionAssetPayload,
    BoundaryAssetPayload,
    RenderBlock,
    DocumentCompositionManifestPayload,
    SegmentRenderAssetPayload,
)
from backend.app.schemas.edit_session import EditableEdge
from backend.app.services.block_planner import BlockPlanner
from backend.app.services.composition_builder import CompositionBuilder


def _segment_asset(
    *,
    segment_id: str,
    order_key: int,
    left: list[float],
    core: list[float],
    right: list[float],
) -> SegmentRenderAssetPayload:
    del order_key
    left_audio = np.asarray(left, dtype=np.float32)
    core_audio = np.asarray(core, dtype=np.float32)
    right_audio = np.asarray(right, dtype=np.float32)
    return SegmentRenderAssetPayload(
        render_asset_id=f"render-{segment_id}",
        segment_id=segment_id,
        render_version=1,
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


def _boundary_asset(*, edge_id: str, left_segment_id: str, right_segment_id: str, audio: list[float]) -> BoundaryAssetPayload:
    del edge_id
    boundary_audio = np.asarray(audio, dtype=np.float32)
    return BoundaryAssetPayload(
        boundary_asset_id=f"boundary-{left_segment_id}-{right_segment_id}",
        left_segment_id=left_segment_id,
        left_render_version=1,
        right_segment_id=right_segment_id,
        right_render_version=1,
        edge_version=1,
        boundary_strategy="latent_overlap_then_equal_power_crossfade",
        boundary_sample_count=int(boundary_audio.size),
        boundary_audio=boundary_audio,
        trace=None,
    )


def _edge(*, left_segment_id: str, right_segment_id: str, pause_duration_seconds: float) -> EditableEdge:
    return EditableEdge(
        edge_id=f"edge-{left_segment_id}-{right_segment_id}",
        document_id="doc-1",
        left_segment_id=left_segment_id,
        right_segment_id=right_segment_id,
        pause_duration_seconds=pause_duration_seconds,
    )


def test_compose_block_inserts_boundary_then_pause_and_tracks_segment_spans():
    builder = CompositionBuilder(sample_rate=4)
    first = _segment_asset(segment_id="seg-1", order_key=1, left=[0.1], core=[0.2, 0.3], right=[0.4])
    second = _segment_asset(segment_id="seg-2", order_key=2, left=[0.5], core=[0.6], right=[0.7, 0.8])
    boundary = _boundary_asset(edge_id="edge-seg-1-seg-2", left_segment_id="seg-1", right_segment_id="seg-2", audio=[0.9])
    edge = _edge(left_segment_id="seg-1", right_segment_id="seg-2", pause_duration_seconds=0.5)

    block = builder.compose_block(
        segments=[first, second],
        boundaries=[boundary],
        edges=[edge],
    )

    assert np.allclose(block.audio, np.asarray([0.1, 0.2, 0.3, 0.9, 0.0, 0.0, 0.6, 0.7, 0.8], dtype=np.float32))
    assert [entry.segment_id for entry in block.segment_entries] == ["seg-1", "seg-2"]
    assert block.segment_entries[0].audio_sample_span == (0, 3)
    assert block.segment_entries[1].audio_sample_span == (6, 9)


def test_compose_document_offsets_block_spans_and_concatenates_audio():
    builder = CompositionBuilder(sample_rate=8)
    first_block = BlockCompositionAssetPayload(
        block_id="block-1",
        segment_ids=["seg-1"],
        sample_rate=8,
        audio=np.asarray([0.1, 0.2], dtype=np.float32),
        audio_sample_count=2,
        segment_entries=[],
    )
    second_block = BlockCompositionAssetPayload(
        block_id="block-2",
        segment_ids=["seg-2"],
        sample_rate=8,
        audio=np.asarray([0.3, 0.4, 0.5], dtype=np.float32),
        audio_sample_count=3,
        segment_entries=[],
    )

    manifest = builder.compose_document(
        document_id="doc-1",
        document_version=1,
        blocks=[first_block, second_block],
    )

    assert np.allclose(manifest.audio, np.asarray([0.1, 0.2, 0.3, 0.4, 0.5], dtype=np.float32))
    assert manifest.playable_sample_span == (0, 5)
    assert manifest.block_spans["block-1"] == (0, 2)
    assert manifest.block_spans["block-2"] == (2, 5)


def test_build_preview_returns_full_segment_boundary_or_block_audio():
    builder = CompositionBuilder(sample_rate=4)
    segment_asset = _segment_asset(segment_id="seg-1", order_key=1, left=[0.1], core=[0.2], right=[0.3])
    boundary_asset = _boundary_asset(edge_id="edge-seg-1-seg-2", left_segment_id="seg-1", right_segment_id="seg-2", audio=[0.4, 0.5])
    block_asset = BlockCompositionAssetPayload(
        block_id="block-1",
        segment_ids=["seg-1"],
        sample_rate=4,
        audio=np.asarray([0.6, 0.7], dtype=np.float32),
        audio_sample_count=2,
        segment_entries=[],
    )

    segment_preview = builder.build_preview(segment_asset=segment_asset)
    boundary_preview = builder.build_preview(boundary_asset=boundary_asset)
    block_preview = builder.build_preview(block_asset=block_asset)

    assert segment_preview.preview_kind == "segment"
    assert np.allclose(segment_preview.audio, np.asarray([0.1, 0.2, 0.3], dtype=np.float32))
    assert boundary_preview.preview_kind == "edge"
    assert np.allclose(boundary_preview.audio, np.asarray([0.4, 0.5], dtype=np.float32))
    assert block_preview.preview_kind == "block"
    assert np.allclose(block_preview.audio, np.asarray([0.6, 0.7], dtype=np.float32))


def test_block_planner_splits_once_block_reaches_min_duration_window():
    planner = BlockPlanner(sample_rate=10, min_block_seconds=20, max_block_seconds=40, max_segment_count=50)
    segments = []
    for index in range(1, 4):
        from backend.app.schemas.edit_session import EditableSegment

        segments.append(
            EditableSegment(
                segment_id=f"seg-{index}",
                document_id="doc-1",
                order_key=index,
                stem=f"第{index}句",
                text_language="zh",
                terminal_raw="。",
                terminal_source="original",
                detected_language="zh",
                inference_exclusion_reason="none",
                assembled_audio_span=(0, 120),
            )
        )

    blocks = planner.build_blocks(segments)

    assert [block.segment_ids for block in blocks] == [["seg-1", "seg-2"], ["seg-3"]]


def test_block_planner_marks_affected_blocks_by_changed_segment_id():
    planner = BlockPlanner()
    blocks = [
        RenderBlock(block_id="block-1", segment_ids=["seg-1", "seg-2"], start_order_key=1, end_order_key=2, estimated_sample_count=10),
        RenderBlock(block_id="block-2", segment_ids=["seg-3"], start_order_key=3, end_order_key=3, estimated_sample_count=5),
    ]

    affected = planner.affected_blocks(changed_segment_ids={"seg-2", "seg-x"}, all_blocks=blocks)

    assert affected == {"block-1"}
