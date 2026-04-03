from __future__ import annotations

from dataclasses import dataclass, field

from backend.app.schemas.edit_session import DocumentSnapshot
from backend.app.services.block_planner import BlockPlanner


@dataclass(frozen=True)
class TargetedRenderPlan:
    target_segment_ids: set[str] = field(default_factory=set)
    target_edge_ids: set[str] = field(default_factory=set)
    target_block_ids: set[str] = field(default_factory=set)
    compose_only: bool = False


class RenderPlanner:
    def __init__(self, *, block_planner: BlockPlanner | None = None) -> None:
        self._block_planner = block_planner or BlockPlanner()

    def for_segment_update(
        self,
        *,
        before_snapshot: DocumentSnapshot,
        after_snapshot: DocumentSnapshot,
        segment_id: str,
    ) -> TargetedRenderPlan:
        del before_snapshot
        neighbor_segment_ids = self._collect_after_neighbor_segment_ids(after_snapshot, segment_id)
        return TargetedRenderPlan(
            target_segment_ids={segment_id},
            target_edge_ids=self._collect_touching_edge_ids(after_snapshot, {segment_id}),
            target_block_ids=self._collect_block_ids(after_snapshot, neighbor_segment_ids | {segment_id}),
            compose_only=False,
        )

    def for_segment_insert(
        self,
        *,
        before_snapshot: DocumentSnapshot,
        after_snapshot: DocumentSnapshot,
        segment_id: str,
    ) -> TargetedRenderPlan:
        del before_snapshot
        neighbor_segment_ids = self._collect_after_neighbor_segment_ids(after_snapshot, segment_id)
        return TargetedRenderPlan(
            target_segment_ids={segment_id},
            target_edge_ids=self._collect_touching_edge_ids(after_snapshot, {segment_id}),
            target_block_ids=self._collect_block_ids(after_snapshot, neighbor_segment_ids | {segment_id}),
            compose_only=False,
        )

    def for_segment_delete(
        self,
        *,
        before_snapshot: DocumentSnapshot,
        after_snapshot: DocumentSnapshot,
        segment_id: str,
    ) -> TargetedRenderPlan:
        before_segments = {segment.segment_id: segment for segment in before_snapshot.segments}
        deleted_segment = before_segments.get(segment_id)
        if deleted_segment is None:
            raise LookupError(f"Segment '{segment_id}' not found in before_snapshot.")

        affected_segment_ids = {
            item
            for item in (deleted_segment.previous_segment_id, deleted_segment.next_segment_id)
            if item is not None
        }
        target_edge_ids = {
            edge.edge_id
            for edge in after_snapshot.edges
            if edge.left_segment_id in affected_segment_ids or edge.right_segment_id in affected_segment_ids
        }
        return TargetedRenderPlan(
            target_segment_ids=set(),
            target_edge_ids=target_edge_ids,
            target_block_ids=self._collect_block_ids(after_snapshot, affected_segment_ids),
            compose_only=False,
        )

    def for_edge_update(
        self,
        *,
        before_snapshot: DocumentSnapshot,
        after_snapshot: DocumentSnapshot,
        edge_id: str,
        pause_only: bool,
    ) -> TargetedRenderPlan:
        del before_snapshot
        edge = next((item for item in after_snapshot.edges if item.edge_id == edge_id), None)
        if edge is None:
            raise LookupError(f"Edge '{edge_id}' not found in after_snapshot.")

        changed_segment_ids = {edge.left_segment_id, edge.right_segment_id}
        return TargetedRenderPlan(
            target_segment_ids=set(),
            target_edge_ids=set() if pause_only else {edge.edge_id},
            target_block_ids=self._collect_block_ids(after_snapshot, changed_segment_ids),
            compose_only=pause_only,
        )

    def for_segment_swap(
        self,
        *,
        before_snapshot: DocumentSnapshot,
        after_snapshot: DocumentSnapshot,
        swapped_segment_ids: set[str],
    ) -> TargetedRenderPlan:
        before_pairs = {
            (edge.left_segment_id, edge.right_segment_id)
            for edge in before_snapshot.edges
        }
        changed_edges = {
            edge.edge_id
            for edge in after_snapshot.edges
            if (edge.left_segment_id, edge.right_segment_id) not in before_pairs
        }
        changed_segment_ids = {
            segment_id
            for edge in after_snapshot.edges
            if edge.edge_id in changed_edges
            for segment_id in (edge.left_segment_id, edge.right_segment_id)
        }
        changed_segment_ids.update(swapped_segment_ids)
        return TargetedRenderPlan(
            target_segment_ids=set(),
            target_edge_ids=changed_edges,
            target_block_ids=self._collect_block_ids(after_snapshot, changed_segment_ids),
            compose_only=False,
        )

    def _collect_after_neighbor_segment_ids(self, snapshot: DocumentSnapshot, segment_id: str) -> set[str]:
        segment = next((item for item in snapshot.segments if item.segment_id == segment_id), None)
        if segment is None:
            raise LookupError(f"Segment '{segment_id}' not found in after_snapshot.")
        return {
            item
            for item in (segment.previous_segment_id, segment.next_segment_id)
            if item is not None
        }

    def _collect_touching_edge_ids(self, snapshot: DocumentSnapshot, segment_ids: set[str]) -> set[str]:
        return {
            edge.edge_id
            for edge in snapshot.edges
            if edge.left_segment_id in segment_ids or edge.right_segment_id in segment_ids
        }

    def _collect_block_ids(self, snapshot: DocumentSnapshot, segment_ids: set[str]) -> set[str]:
        blocks = self._block_planner.build_blocks(snapshot.segments)
        return self._block_planner.affected_blocks(changed_segment_ids=segment_ids, all_blocks=blocks)
