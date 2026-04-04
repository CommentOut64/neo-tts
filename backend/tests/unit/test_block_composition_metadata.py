import numpy as np

from backend.app.inference.editable_types import BoundaryAssetPayload, SegmentRenderAssetPayload
from backend.app.schemas.edit_session import EditableEdge
from backend.app.services.composition_builder import CompositionBuilder


def _segment_asset(
    *,
    segment_id: str,
    render_asset_id: str,
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
        render_asset_id=render_asset_id,
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


def _boundary_asset(*, left_segment_id: str, right_segment_id: str, audio: list[float]) -> BoundaryAssetPayload:
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


def test_compose_block_emits_segment_edge_and_marker_metadata():
    builder = CompositionBuilder(sample_rate=4)
    first = _segment_asset(
        segment_id="seg-1",
        render_asset_id="render-seg-1-v1",
        order_key=1,
        left=[0.1],
        core=[0.2, 0.3],
        right=[0.4],
    )
    second = _segment_asset(
        segment_id="seg-2",
        render_asset_id="render-seg-2-v1",
        order_key=2,
        left=[0.5],
        core=[0.6],
        right=[0.7, 0.8],
    )
    boundary = _boundary_asset(left_segment_id="seg-1", right_segment_id="seg-2", audio=[0.9])
    edge = EditableEdge(
        edge_id="edge-seg-1-seg-2",
        document_id="doc-1",
        left_segment_id="seg-1",
        right_segment_id="seg-2",
        pause_duration_seconds=0.5,
    )

    block = builder.compose_block(
        segments=[first, second],
        boundaries=[boundary],
        edges=[edge],
        block_id="logical-block-1",
    )

    assert block.block_id == "logical-block-1"
    assert block.block_asset_id
    assert [entry.segment_id for entry in block.segment_entries] == ["seg-1", "seg-2"]
    assert block.segment_entries[0].audio_sample_span == (0, 3)
    assert block.segment_entries[0].render_asset_id == "render-seg-1-v1"
    assert block.segment_entries[1].audio_sample_span == (6, 9)
    assert block.segment_entries[1].render_asset_id == "render-seg-2-v1"
    assert len(block.edge_entries) == 1
    assert block.edge_entries[0].edge_id == "edge-seg-1-seg-2"
    assert block.edge_entries[0].boundary_sample_span == (3, 4)
    assert block.edge_entries[0].pause_sample_span == (4, 6)
    assert {
        (entry.marker_type, entry.sample, entry.related_id)
        for entry in block.marker_entries
    } == {
        ("block_start", 0, "logical-block-1"),
        ("segment_start", 0, "seg-1"),
        ("segment_end", 3, "seg-1"),
        ("edge_gap_start", 4, "edge-seg-1-seg-2"),
        ("edge_gap_end", 6, "edge-seg-1-seg-2"),
        ("segment_start", 6, "seg-2"),
        ("segment_end", 9, "seg-2"),
        ("block_end", 9, "logical-block-1"),
    }

