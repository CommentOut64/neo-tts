from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from backend.app.inference.editable_types import BlockCompositionAssetPayload, RenderBlock
from backend.app.repositories.edit_session_repository import EditSessionRepository
from backend.app.schemas.edit_session import (
    ActiveDocumentState,
    CheckpointBlockState,
    CheckpointState,
    DocumentSnapshot,
    EditableEdge,
    EditableSegment,
    RenderProfile,
    SegmentGroup,
    VoiceBinding,
)
from backend.app.services.block_planner import BlockPlanner
from backend.app.services.edit_asset_store import EditAssetStore
from backend.app.services.timeline_manifest_service import TimelineManifestService


class CheckpointService:
    def __init__(
        self,
        *,
        repository: EditSessionRepository,
        asset_store: EditAssetStore,
        block_planner: BlockPlanner | None = None,
        timeline_manifest_service: TimelineManifestService | None = None,
        **_: object,
    ) -> None:
        self._repository = repository
        self._asset_store = asset_store
        self._block_planner = block_planner or BlockPlanner()
        self._timeline_manifest_service = timeline_manifest_service or TimelineManifestService()

    def get_current_checkpoint(self, document_id: str) -> CheckpointState | None:
        return self._repository.get_latest_checkpoint(document_id)

    def clear_document_checkpoint(self, document_id: str) -> None:
        self._repository.delete_checkpoints_for_document(document_id)

    def save_partial_head(
        self,
        *,
        document_id: str,
        job_id: str,
        active_session: ActiveDocumentState,
        full_snapshot: DocumentSnapshot,
        completed_blocks: list[RenderBlock],
        remaining_blocks: list[RenderBlock],
        completed_block_assets: list[BlockCompositionAssetPayload],
        status: str,
    ) -> tuple[CheckpointState, DocumentSnapshot]:
        del active_session
        completed_segment_id_set = {
            segment_id
            for block in completed_blocks
            for segment_id in block.segment_ids
        }
        completed_segments = [
            segment.model_copy(deep=True)
            for segment in sorted(full_snapshot.segments, key=lambda item: item.order_key)
            if segment.segment_id in completed_segment_id_set
        ]
        partial_edges = [
            edge.model_copy(deep=True)
            for edge in full_snapshot.edges
            if edge.left_segment_id in completed_segment_id_set and edge.right_segment_id in completed_segment_id_set
        ]

        partial_snapshot = self._build_partial_snapshot(
            document_id=document_id,
            document_version=full_snapshot.document_version,
            segments=completed_segments,
            edges=partial_edges,
            groups=full_snapshot.groups,
            render_profiles=full_snapshot.render_profiles,
            voice_bindings=full_snapshot.voice_bindings,
            default_render_profile_id=full_snapshot.default_render_profile_id,
            default_voice_binding_id=full_snapshot.default_voice_binding_id,
        )
        timeline_manifest, _ = self._timeline_manifest_service.build(
            snapshot=partial_snapshot,
            blocks=completed_block_assets,
            sample_rate=(
                completed_block_assets[0].sample_rate
                if completed_block_assets
                else self._block_planner._min_block_samples  # noqa: SLF001
            ),
        )
        self._asset_store.write_formal_json_atomic(
            f"timelines/{timeline_manifest.timeline_manifest_id}/manifest.json",
            timeline_manifest.model_dump(mode="json"),
        )
        partial_snapshot = partial_snapshot.model_copy(
            deep=True,
            update={
                "block_ids": [entry.block_asset_id for entry in timeline_manifest.block_entries],
                "timeline_manifest_id": timeline_manifest.timeline_manifest_id,
            },
        )
        working_snapshot = full_snapshot.model_copy(
            deep=True,
            update={
                "snapshot_id": f"checkpoint-working-{uuid4().hex}",
                "snapshot_kind": "staging",
            },
        )
        self._repository.save_snapshot(partial_snapshot)
        self._repository.save_snapshot(working_snapshot)

        checkpoint = CheckpointState(
            checkpoint_id=f"checkpoint-{uuid4().hex}",
            document_id=document_id,
            job_id=job_id,
            document_version=full_snapshot.document_version,
            partial_snapshot_id=partial_snapshot.snapshot_id,
            partial_timeline_manifest_id=timeline_manifest.timeline_manifest_id,
            working_snapshot_id=working_snapshot.snapshot_id,
            completed_blocks=[self._to_checkpoint_block(block) for block in completed_blocks],
            remaining_blocks=[self._to_checkpoint_block(block) for block in remaining_blocks],
            status=status,
            resume_token=(f"resume-{uuid4().hex}" if status == "paused" else None),
            updated_at=datetime.now(timezone.utc),
        )
        self._repository.save_checkpoint(checkpoint)
        return checkpoint, partial_snapshot

    def _build_partial_snapshot(
        self,
        *,
        document_id: str,
        document_version: int,
        segments: list[EditableSegment],
        edges: list[EditableEdge],
        groups: list[SegmentGroup],
        render_profiles: list[RenderProfile],
        voice_bindings: list[VoiceBinding],
        default_render_profile_id: str | None,
        default_voice_binding_id: str | None,
    ) -> DocumentSnapshot:
        return DocumentSnapshot(
            snapshot_id=f"checkpoint-partial-{uuid4().hex}",
            document_id=document_id,
            snapshot_kind="checkpoint_partial",
            document_version=document_version,
            segment_ids=[segment.segment_id for segment in segments],
            edge_ids=[edge.edge_id for edge in edges],
            block_ids=[],
            groups=[group.model_copy(deep=True) for group in groups],
            render_profiles=[profile.model_copy(deep=True) for profile in render_profiles],
            voice_bindings=[binding.model_copy(deep=True) for binding in voice_bindings],
            default_render_profile_id=default_render_profile_id,
            default_voice_binding_id=default_voice_binding_id,
            timeline_manifest_id=None,
            segments=[segment.model_copy(deep=True) for segment in segments],
            edges=[edge.model_copy(deep=True) for edge in edges],
        )

    @staticmethod
    def _to_checkpoint_block(block: RenderBlock) -> CheckpointBlockState:
        return CheckpointBlockState(
            block_id=block.block_id,
            segment_ids=list(block.segment_ids),
            start_order_key=block.start_order_key,
            end_order_key=block.end_order_key,
            estimated_sample_count=block.estimated_sample_count,
        )
