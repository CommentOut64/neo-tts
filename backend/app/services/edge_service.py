from __future__ import annotations

from dataclasses import dataclass

from backend.app.core.exceptions import EditSessionNotFoundError
from backend.app.repositories.edit_session_repository import EditSessionRepository
from backend.app.schemas.edit_session import (
    DocumentSnapshot,
    EditableEdge,
    EditableSegment,
    UpdateEdgeRequest,
)


DEFAULT_BOUNDARY_STRATEGY = "latent_overlap_then_equal_power_crossfade"
DEFAULT_REORDER_BOUNDARY_STRATEGY = "crossfade_only"


@dataclass(frozen=True)
class EdgeMutationResult:
    snapshot: DocumentSnapshot
    edge: EditableEdge
    pause_only: bool


class EdgeService:
    def __init__(self, *, repository: EditSessionRepository) -> None:
        self._repository = repository

    def list_edges(
        self,
        *,
        limit: int,
        cursor: int | None,
        snapshot: DocumentSnapshot | None = None,
    ) -> list[EditableEdge]:
        head_snapshot = snapshot or self._get_head_snapshot()
        return self._repository.list_edges(
            head_snapshot.document_id,
            limit=limit,
            cursor=cursor,
            snapshot_id=head_snapshot.snapshot_id,
        )

    def update_edge(
        self,
        edge_id: str,
        patch: UpdateEdgeRequest,
        *,
        snapshot: DocumentSnapshot | None = None,
    ) -> EdgeMutationResult:
        head_snapshot = snapshot or self._get_head_snapshot()
        edges = [item.model_copy(deep=True) for item in head_snapshot.edges]
        target_index = next((index for index, item in enumerate(edges) if item.edge_id == edge_id), None)
        if target_index is None:
            raise EditSessionNotFoundError(f"Edge '{edge_id}' not found.")

        current_edge = edges[target_index]
        pause_only = patch.pause_duration_seconds is not None and patch.boundary_strategy is None
        next_edge = current_edge.model_copy(deep=True)
        if patch.pause_duration_seconds is not None:
            next_edge.pause_duration_seconds = patch.pause_duration_seconds
        if patch.boundary_strategy is not None:
            if (
                current_edge.boundary_strategy_locked
                and patch.boundary_strategy != current_edge.boundary_strategy
            ):
                raise ValueError("该拼接边界策略已锁定，暂不支持修改。")
            if patch.boundary_strategy != current_edge.boundary_strategy:
                next_edge.boundary_strategy = patch.boundary_strategy
                next_edge.edge_version = current_edge.edge_version + 1
                pause_only = False
            else:
                next_edge.boundary_strategy = patch.boundary_strategy

        edges[target_index] = next_edge
        updated_snapshot = self._clone_snapshot(
            head_snapshot,
            segments=[segment.model_copy(deep=True) for segment in head_snapshot.segments],
            edges=edges,
        )
        return EdgeMutationResult(snapshot=updated_snapshot, edge=next_edge, pause_only=pause_only)

    def rebuild_neighbor_edges(
        self,
        segments: list[EditableSegment],
        *,
        existing_edges: list[EditableEdge] | None = None,
        default_pause_duration_seconds: float = 0.3,
        default_boundary_strategy: str = DEFAULT_BOUNDARY_STRATEGY,
        lock_new_boundary_strategy: bool = False,
    ) -> list[EditableEdge]:
        if not segments:
            return []

        existing_by_pair = {
            (edge.left_segment_id, edge.right_segment_id): edge.model_copy(deep=True)
            for edge in (existing_edges or [])
        }
        rebuilt: list[EditableEdge] = []
        for left_segment, right_segment in zip(segments, segments[1:]):
            existing = existing_by_pair.get((left_segment.segment_id, right_segment.segment_id))
            if existing is not None:
                rebuilt.append(
                    existing.model_copy(
                        update={
                            "document_id": left_segment.document_id,
                            "left_segment_id": left_segment.segment_id,
                            "right_segment_id": right_segment.segment_id,
                        }
                    )
                )
                continue

            rebuilt.append(
                EditableEdge(
                    edge_id=f"edge-{left_segment.segment_id}-{right_segment.segment_id}",
                    document_id=left_segment.document_id,
                    left_segment_id=left_segment.segment_id,
                    right_segment_id=right_segment.segment_id,
                    pause_duration_seconds=default_pause_duration_seconds,
                    boundary_strategy=default_boundary_strategy,
                    boundary_strategy_locked=lock_new_boundary_strategy,
                    edge_version=1,
                )
            )
        return rebuilt

    def _get_head_snapshot(self) -> DocumentSnapshot:
        active_session = self._repository.get_active_session()
        if active_session is None or active_session.head_snapshot_id is None:
            raise EditSessionNotFoundError("Head snapshot not found.")
        snapshot = self._repository.get_snapshot(active_session.head_snapshot_id)
        if snapshot is None:
            raise EditSessionNotFoundError("Head snapshot not found.")
        return snapshot

    @staticmethod
    def _clone_snapshot(
        base_snapshot: DocumentSnapshot,
        *,
        segments: list[EditableSegment],
        edges: list[EditableEdge],
    ) -> DocumentSnapshot:
        return base_snapshot.model_copy(
            deep=True,
            update={
                "document_version": base_snapshot.document_version + 1,
                "raw_text": "".join(segment.raw_text for segment in segments),
                "normalized_text": "".join(segment.normalized_text for segment in segments),
                "segments": segments,
                "edges": edges,
                "block_ids": [],
                "composition_manifest_id": None,
                "playback_map_version": None,
            },
        )
