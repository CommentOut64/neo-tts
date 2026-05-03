from backend.app.schemas.edit_session import DocumentSnapshot, EditableEdge, EditableSegment
from backend.app.services.block_planner import BlockPlanner
from backend.app.services.render_planner import RenderPlanner


def _segment(segment_id: str, order_key: int) -> EditableSegment:
    return EditableSegment(
        segment_id=segment_id,
        document_id="doc-1",
        order_key=order_key,
        previous_segment_id=f"seg-{order_key - 1}" if order_key > 1 else None,
        next_segment_id=f"seg-{order_key + 1}" if order_key < 3 else None,
        stem=f"第{order_key}句",
        text_language="zh",
        terminal_raw="。",
        terminal_source="original",
        detected_language="zh",
        inference_exclusion_reason="none",
        render_version=1,
        render_asset_id=f"render-{segment_id}-v1",
        render_status="ready",
        effective_duration_samples=10,
        assembled_audio_span=(0, 10),
    )


def _edge(left_segment_id: str, right_segment_id: str, *, edge_version: int = 1) -> EditableEdge:
    return EditableEdge(
        edge_id=f"edge-{left_segment_id}-{right_segment_id}",
        document_id="doc-1",
        left_segment_id=left_segment_id,
        right_segment_id=right_segment_id,
        pause_duration_seconds=0.3,
        boundary_strategy="latent_overlap_then_equal_power_crossfade",
        edge_version=edge_version,
    )


def _snapshot(*, segments: list[EditableSegment], edges: list[EditableEdge]) -> DocumentSnapshot:
    return DocumentSnapshot(
        snapshot_id="head-1",
        document_id="doc-1",
        snapshot_kind="head",
        document_version=1,
        segment_ids=[segment.segment_id for segment in segments],
        edge_ids=[edge.edge_id for edge in edges],
        segments=segments,
        edges=edges,
    )


def _planner() -> RenderPlanner:
    return RenderPlanner(
        block_planner=BlockPlanner(
            sample_rate=1,
            min_block_seconds=100,
            max_block_seconds=1000,
            max_segment_count=50,
        )
    )


def _planner_with_two_segment_blocks() -> RenderPlanner:
    return RenderPlanner(
        block_planner=BlockPlanner(
            sample_rate=1,
            min_block_seconds=100,
            max_block_seconds=1000,
            max_segment_count=2,
        )
    )


def _block_ids(*segments: EditableSegment) -> set[str]:
    planner = BlockPlanner(
        sample_rate=1,
        min_block_seconds=100,
        max_block_seconds=1000,
        max_segment_count=50,
    )
    return {block.block_id for block in planner.build_blocks(list(segments))}


def test_for_segment_update_targets_changed_segment_neighbor_edges_and_blocks():
    planner = _planner()
    before_segments = [_segment("seg-1", 1), _segment("seg-2", 2), _segment("seg-3", 3)]
    after_segments = [segment.model_copy(deep=True) for segment in before_segments]
    after_segments[1].stem = "第二句已修改"
    after_segments[1].terminal_raw = "。"
    after_segments[1].render_version = 2
    after_segments[1].render_asset_id = None
    after_segments[1].assembled_audio_span = None

    plan = planner.for_segment_update(
        before_snapshot=_snapshot(segments=before_segments, edges=[_edge("seg-1", "seg-2"), _edge("seg-2", "seg-3")]),
        after_snapshot=_snapshot(segments=after_segments, edges=[_edge("seg-1", "seg-2"), _edge("seg-2", "seg-3")]),
        segment_id="seg-2",
    )

    assert plan.target_segment_ids == {"seg-2"}
    assert plan.target_edge_ids == {"edge-seg-1-seg-2", "edge-seg-2-seg-3"}
    assert plan.target_block_ids == _block_ids(*after_segments)
    assert plan.compose_only is False
    assert plan.earliest_changed_order_key == 2
    assert plan.timeline_reflow_required is True
    assert plan.change_reason == "segment_update"


def test_for_segment_update_with_small_blocks_targets_only_affected_block_ids():
    planner = _planner_with_two_segment_blocks()
    before_segments = [_segment("seg-1", 1), _segment("seg-2", 2), _segment("seg-3", 3)]
    after_segments = [segment.model_copy(deep=True) for segment in before_segments]
    after_segments[0].stem = "第一句已修改"
    after_segments[0].terminal_raw = "。"
    after_segments[0].render_version = 2
    after_segments[0].render_asset_id = None
    after_segments[0].assembled_audio_span = None

    plan = planner.for_segment_update(
        before_snapshot=_snapshot(segments=before_segments, edges=[_edge("seg-1", "seg-2"), _edge("seg-2", "seg-3")]),
        after_snapshot=_snapshot(segments=after_segments, edges=[_edge("seg-1", "seg-2"), _edge("seg-2", "seg-3")]),
        segment_id="seg-1",
    )

    assert plan.target_segment_ids == {"seg-1"}
    assert plan.target_block_ids == _block_ids(*after_segments[:2])
    assert plan.target_block_ids.isdisjoint(_block_ids(after_segments[2]))


def test_for_edge_update_pause_only_skips_boundary_rerender_and_marks_compose_only():
    planner = _planner()
    segments = [_segment("seg-1", 1), _segment("seg-2", 2)]
    before_edge = _edge("seg-1", "seg-2", edge_version=1)
    after_edge = before_edge.model_copy(update={"pause_duration_seconds": 0.8})

    plan = planner.for_edge_update(
        before_snapshot=_snapshot(segments=segments, edges=[before_edge]),
        after_snapshot=_snapshot(segments=segments, edges=[after_edge]),
        edge_id=before_edge.edge_id,
        pause_only=True,
    )

    assert plan.target_segment_ids == set()
    assert plan.target_edge_ids == set()
    assert plan.target_block_ids == _block_ids(*segments)
    assert plan.compose_only is True
    assert plan.earliest_changed_order_key == 1
    assert plan.timeline_reflow_required is True
    assert plan.change_reason == "edge_pause_update"


def test_for_edge_update_boundary_strategy_change_targets_boundary_rerender():
    planner = _planner()
    segments = [_segment("seg-1", 1), _segment("seg-2", 2)]
    before_edge = _edge("seg-1", "seg-2", edge_version=1)
    after_edge = before_edge.model_copy(
        update={
            "boundary_strategy": "crossfade_only",
            "edge_version": 2,
        }
    )

    plan = planner.for_edge_update(
        before_snapshot=_snapshot(segments=segments, edges=[before_edge]),
        after_snapshot=_snapshot(segments=segments, edges=[after_edge]),
        edge_id=before_edge.edge_id,
        pause_only=False,
    )

    assert plan.target_segment_ids == set()
    assert plan.target_edge_ids == {before_edge.edge_id}
    assert plan.target_block_ids == _block_ids(*segments)
    assert plan.compose_only is False


def test_for_segment_insert_targets_new_segment_and_new_neighbor_edges():
    planner = _planner()
    before_segments = [_segment("seg-1", 1), _segment("seg-3", 2)]
    after_segments = [
        before_segments[0].model_copy(update={"next_segment_id": "seg-2"}),
        EditableSegment(
            segment_id="seg-2",
            document_id="doc-1",
            order_key=2,
            previous_segment_id="seg-1",
            next_segment_id="seg-3",
            stem="插入句",
            text_language="zh",
            terminal_raw="。",
            terminal_source="original",
            detected_language="zh",
            inference_exclusion_reason="none",
            render_version=1,
            render_asset_id=None,
        ),
        before_segments[1].model_copy(update={"order_key": 3, "previous_segment_id": "seg-2"}),
    ]

    plan = planner.for_segment_insert(
        before_snapshot=_snapshot(segments=before_segments, edges=[_edge("seg-1", "seg-3")]),
        after_snapshot=_snapshot(segments=after_segments, edges=[_edge("seg-1", "seg-2"), _edge("seg-2", "seg-3")]),
        segment_id="seg-2",
    )

    assert plan.target_segment_ids == {"seg-2"}
    assert plan.target_edge_ids == {"edge-seg-1-seg-2", "edge-seg-2-seg-3"}
    assert plan.target_block_ids == _block_ids(*after_segments)
    assert plan.compose_only is False


def test_for_segment_delete_targets_new_bridging_edge_only():
    planner = _planner()
    before_segments = [_segment("seg-1", 1), _segment("seg-2", 2), _segment("seg-3", 3)]
    after_segments = [
        before_segments[0].model_copy(update={"next_segment_id": "seg-3"}),
        before_segments[2].model_copy(update={"order_key": 2, "previous_segment_id": "seg-1", "next_segment_id": None}),
    ]

    plan = planner.for_segment_delete(
        before_snapshot=_snapshot(segments=before_segments, edges=[_edge("seg-1", "seg-2"), _edge("seg-2", "seg-3")]),
        after_snapshot=_snapshot(segments=after_segments, edges=[_edge("seg-1", "seg-3")]),
        segment_id="seg-2",
    )

    assert plan.target_segment_ids == set()
    assert plan.target_edge_ids == {"edge-seg-1-seg-3"}
    assert plan.target_block_ids == _block_ids(*after_segments)
    assert plan.compose_only is False


def test_for_segment_swap_targets_changed_edges_and_blocks_without_segment_rerender():
    planner = _planner()
    before_segments = [_segment("seg-1", 1), _segment("seg-2", 2), _segment("seg-3", 3), _segment("seg-4", 4)]
    after_segments = [
        before_segments[0].model_copy(update={"next_segment_id": "seg-3"}),
        before_segments[2].model_copy(update={"order_key": 2, "previous_segment_id": "seg-1", "next_segment_id": "seg-2"}),
        before_segments[1].model_copy(update={"order_key": 3, "previous_segment_id": "seg-3", "next_segment_id": "seg-4"}),
        before_segments[3].model_copy(update={"previous_segment_id": "seg-2", "next_segment_id": None}),
    ]

    plan = planner.for_segment_swap(
        before_snapshot=_snapshot(
            segments=before_segments,
            edges=[_edge("seg-1", "seg-2"), _edge("seg-2", "seg-3"), _edge("seg-3", "seg-4")],
        ),
        after_snapshot=_snapshot(
            segments=after_segments,
            edges=[_edge("seg-1", "seg-3"), _edge("seg-3", "seg-2"), _edge("seg-2", "seg-4")],
        ),
        swapped_segment_ids={"seg-2", "seg-3"},
    )

    assert plan.target_segment_ids == set()
    assert plan.target_edge_ids == {"edge-seg-1-seg-3", "edge-seg-3-seg-2", "edge-seg-2-seg-4"}
    assert plan.target_block_ids == _block_ids(*after_segments)
    assert plan.compose_only is False
