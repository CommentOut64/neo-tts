from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from backend.app.core.exceptions import EditSessionNotFoundError
from backend.app.repositories.edit_session_repository import EditSessionRepository
from backend.app.schemas.edit_session import (
    ActiveDocumentState,
    BaselineSnapshotResponse,
    ConfigurationCommitResponse,
    CurrentCheckpointResponse,
    DocumentSnapshot,
    EditSessionSnapshotResponse,
    EditableEdgeResponse,
    EditableSegmentResponse,
    GroupListResponse,
    InitializeEditSessionRequest,
    RenderProfileListResponse,
    RenderJobResponse,
    TimelineManifest,
    VoiceBindingListResponse,
)
from backend.app.services.edit_asset_store import EditAssetStore
from backend.app.services.edit_session_runtime import EditSessionRuntime
from backend.app.services.voice_service import VoiceService


def should_inline_segment_summary(total_segment_count: int) -> bool:
    return total_segment_count < 1000


class EditSessionService:
    def __init__(
        self,
        *,
        repository: EditSessionRepository,
        asset_store: EditAssetStore,
        runtime: EditSessionRuntime,
        voice_service: VoiceService,
    ) -> None:
        self._repository = repository
        self._asset_store = asset_store
        self._runtime = runtime
        self._voice_service = voice_service

    def prepare_initialize_request(self, request: InitializeEditSessionRequest) -> InitializeEditSessionRequest:
        voice = self._voice_service.get_voice(request.voice_id)
        return request.model_copy(
            update={
                "reference_audio_path": request.reference_audio_path or voice.ref_audio,
                "reference_text": request.reference_text or voice.ref_text,
                "reference_language": request.reference_language or voice.ref_lang,
            }
        )

    def initialize_document(self, request: InitializeEditSessionRequest) -> tuple[ActiveDocumentState, RenderJobResponse]:
        now = datetime.now(timezone.utc)
        document_id = uuid4().hex
        job_id = uuid4().hex
        session = ActiveDocumentState(
            document_id=document_id,
            session_status="initializing",
            baseline_snapshot_id=None,
            head_snapshot_id=None,
            active_job_id=job_id,
            editable_mode="segment",
            initialize_request=request,
            created_at=now,
            updated_at=now,
        )
        job = RenderJobResponse(
            job_id=job_id,
            document_id=document_id,
            status="queued",
            progress=0.0,
            message=f"初始化任务已创建，voice={request.voice_id}。",
            cancel_requested=False,
            pause_requested=False,
            updated_at=now,
        )
        self._repository.upsert_active_session(session)
        return session, job

    def get_snapshot(self) -> EditSessionSnapshotResponse:
        active_session = self._repository.get_active_session()
        if active_session is None:
            return EditSessionSnapshotResponse(session_status="empty")

        baseline_snapshot = (
            self._repository.get_snapshot(active_session.baseline_snapshot_id)
            if active_session.baseline_snapshot_id
            else None
        )
        head_snapshot = (
            self._repository.get_snapshot(active_session.head_snapshot_id)
            if active_session.head_snapshot_id
            else None
        )
        current_snapshot = head_snapshot or baseline_snapshot
        timeline = self._load_timeline(current_snapshot)
        active_job = (
            self._runtime.get_job(active_session.active_job_id)
            if active_session.active_job_id is not None
            else None
        )
        composition_manifest_id = self._get_available_composition_manifest_id(current_snapshot)
        composition_audio_url = (
            f"/v1/edit-session/assets/compositions/{composition_manifest_id}/audio"
            if composition_manifest_id is not None
            else None
        )
        total_segment_count = len(current_snapshot.segments) if current_snapshot is not None else 0
        inline_entities = should_inline_segment_summary(total_segment_count)
        segments = (
            [EditableSegmentResponse.model_validate(segment.model_dump()) for segment in current_snapshot.segments]
            if current_snapshot is not None and inline_entities
            else []
        )
        edges = (
            [EditableEdgeResponse.model_validate(edge.model_dump()) for edge in current_snapshot.edges]
            if current_snapshot is not None and inline_entities
            else []
        )
        return EditSessionSnapshotResponse(
            session_status=active_session.session_status,
            document_id=active_session.document_id,
            document_version=current_snapshot.document_version if current_snapshot is not None else None,
            default_render_profile_id=current_snapshot.default_render_profile_id if current_snapshot is not None else None,
            default_voice_binding_id=current_snapshot.default_voice_binding_id if current_snapshot is not None else None,
            baseline_version=baseline_snapshot.document_version if baseline_snapshot is not None else None,
            head_version=head_snapshot.document_version if head_snapshot is not None else None,
            total_segment_count=total_segment_count,
            total_edge_count=len(current_snapshot.edges) if current_snapshot is not None else 0,
            ready_segment_count=(
                sum(segment.render_asset_id is not None for segment in current_snapshot.segments)
                if current_snapshot is not None
                else 0
            ),
            ready_block_count=len(timeline.block_entries) if timeline is not None else (len(current_snapshot.block_ids) if current_snapshot is not None else 0),
            timeline_manifest_id=current_snapshot.timeline_manifest_id if current_snapshot is not None else None,
            composition_manifest_id=composition_manifest_id,
            composition_audio_url=composition_audio_url,
            playable_sample_span=timeline.playable_sample_span if timeline is not None else (
                (
                    0,
                    max(
                        entry.assembled_audio_span[1]
                        for entry in current_snapshot.segments
                        if entry.assembled_audio_span is not None
                    ),
                )
                if current_snapshot is not None
                and any(entry.assembled_audio_span is not None for entry in current_snapshot.segments)
                else None
            ),
            active_job=active_job,
            segments=segments,
            edges=edges,
        )

    def commit_configuration_snapshot(
        self,
        *,
        before_snapshot: DocumentSnapshot,
        after_snapshot: DocumentSnapshot,
        pending_segment_ids: set[str] | None = None,
    ) -> ConfigurationCommitResponse:
        active_session = self.require_active_session()
        next_document_version = max(before_snapshot.document_version, after_snapshot.document_version)
        if next_document_version <= before_snapshot.document_version:
            next_document_version = before_snapshot.document_version + 1

        next_snapshot = (
            self._mark_segments_pending(after_snapshot, pending_segment_ids)
            if pending_segment_ids
            else after_snapshot
        )

        next_timeline_manifest_id = next_snapshot.timeline_manifest_id
        next_playback_map_version = next_snapshot.playback_map_version
        if next_snapshot.timeline_manifest_id is not None:
            current_timeline = self._asset_store.load_timeline_manifest(next_snapshot.timeline_manifest_id)
            next_timeline = self._build_committed_timeline_manifest(
                current_timeline=current_timeline,
                snapshot=next_snapshot,
                document_version=next_document_version,
            )
            self._asset_store.write_formal_json_atomic(
                f"timelines/{next_timeline.timeline_manifest_id}/manifest.json",
                next_timeline.model_dump(mode="json"),
            )
            next_timeline_manifest_id = next_timeline.timeline_manifest_id
            next_playback_map_version = next_document_version

        head_snapshot = next_snapshot.model_copy(
            deep=True,
            update={
                "snapshot_id": f"head-{uuid4().hex}",
                "snapshot_kind": "head",
                "document_version": next_document_version,
                "timeline_manifest_id": next_timeline_manifest_id,
                "playback_map_version": next_playback_map_version,
            },
        )
        self._repository.save_snapshot(head_snapshot)
        self._repository.upsert_active_session(
            active_session.model_copy(
                update={
                    "session_status": "ready",
                    "head_snapshot_id": head_snapshot.snapshot_id,
                    "active_job_id": None,
                    "updated_at": datetime.now(timezone.utc),
                }
            )
        )
        return ConfigurationCommitResponse(
            document_id=head_snapshot.document_id,
            document_version=head_snapshot.document_version,
            head_snapshot_id=head_snapshot.snapshot_id,
        )

    def _build_committed_timeline_manifest(
        self,
        *,
        current_timeline: TimelineManifest,
        snapshot: DocumentSnapshot,
        document_version: int,
    ) -> TimelineManifest:
        segments_by_id = {segment.segment_id: segment for segment in snapshot.segments}
        edges_by_id = {edge.edge_id: edge for edge in snapshot.edges}
        return current_timeline.model_copy(
            deep=True,
            update={
                "timeline_manifest_id": f"timeline-{uuid4().hex}",
                "document_version": document_version,
                "timeline_version": document_version,
                "segment_entries": [
                    entry.model_copy(
                        update={
                            "render_status": segments_by_id.get(entry.segment_id).render_status
                            if entry.segment_id in segments_by_id
                            else entry.render_status,
                            "group_id": segments_by_id.get(entry.segment_id).group_id
                            if entry.segment_id in segments_by_id
                            else entry.group_id,
                            "render_profile_id": segments_by_id.get(entry.segment_id).render_profile_id
                            if entry.segment_id in segments_by_id
                            else entry.render_profile_id,
                            "voice_binding_id": segments_by_id.get(entry.segment_id).voice_binding_id
                            if entry.segment_id in segments_by_id
                            else entry.voice_binding_id,
                        }
                    )
                    for entry in current_timeline.segment_entries
                ],
                "edge_entries": [
                    entry.model_copy(
                        update={
                            "pause_duration_seconds": edges_by_id.get(entry.edge_id).pause_duration_seconds
                            if entry.edge_id in edges_by_id
                            else entry.pause_duration_seconds,
                            "boundary_strategy": edges_by_id.get(entry.edge_id).boundary_strategy
                            if entry.edge_id in edges_by_id
                            else entry.boundary_strategy,
                            "effective_boundary_strategy": edges_by_id.get(entry.edge_id).effective_boundary_strategy
                            if entry.edge_id in edges_by_id and edges_by_id.get(entry.edge_id).effective_boundary_strategy
                            else entry.effective_boundary_strategy,
                        }
                    )
                    for entry in current_timeline.edge_entries
                ],
            },
        )

    @staticmethod
    def _mark_segments_pending(
        snapshot: DocumentSnapshot,
        pending_segment_ids: set[str],
    ) -> DocumentSnapshot:
        if not pending_segment_ids:
            return snapshot
        return snapshot.model_copy(
            deep=True,
            update={
                "segments": [
                    segment.model_copy(
                        update={
                            "render_status": "pending",
                        }
                    )
                    if segment.segment_id in pending_segment_ids
                    else segment.model_copy(deep=True)
                    for segment in snapshot.segments
                ]
            },
        )

    def delete_session(self) -> None:
        self._repository.clear()
        self._asset_store.clear_all()
        self._runtime.reset()

    def get_baseline(self) -> BaselineSnapshotResponse:
        active_session = self._repository.get_active_session()
        if active_session is None or active_session.baseline_snapshot_id is None:
            return BaselineSnapshotResponse(baseline_snapshot=None)
        baseline_snapshot = self._repository.get_snapshot(active_session.baseline_snapshot_id)
        return BaselineSnapshotResponse(baseline_snapshot=baseline_snapshot)

    def get_head_snapshot(self) -> DocumentSnapshot:
        active_session = self.require_active_session()
        if active_session.head_snapshot_id is None:
            raise EditSessionNotFoundError("Head snapshot not found.")
        snapshot = self._repository.get_snapshot(active_session.head_snapshot_id)
        if snapshot is None:
            raise EditSessionNotFoundError("Head snapshot not found.")
        return snapshot

    def get_timeline(self) -> TimelineManifest:
        snapshot = self.get_head_snapshot()
        timeline = self._load_timeline(snapshot)
        if timeline is None:
            raise EditSessionNotFoundError("Timeline manifest not found.")
        return timeline

    def get_current_checkpoint(self) -> CurrentCheckpointResponse:
        active_session = self._repository.get_active_session()
        if active_session is None:
            return CurrentCheckpointResponse(checkpoint=None)
        return CurrentCheckpointResponse(
            checkpoint=self._repository.get_latest_checkpoint(active_session.document_id),
        )

    def get_groups(self) -> GroupListResponse:
        snapshot = self.get_head_snapshot()
        return GroupListResponse(
            document_id=snapshot.document_id,
            document_version=snapshot.document_version,
            items=[group.model_copy(deep=True) for group in snapshot.groups],
        )

    def get_render_profiles(self) -> RenderProfileListResponse:
        snapshot = self.get_head_snapshot()
        return RenderProfileListResponse(
            document_id=snapshot.document_id,
            document_version=snapshot.document_version,
            items=[profile.model_copy(deep=True) for profile in snapshot.render_profiles],
        )

    def get_voice_bindings(self) -> VoiceBindingListResponse:
        snapshot = self.get_head_snapshot()
        return VoiceBindingListResponse(
            document_id=snapshot.document_id,
            document_version=snapshot.document_version,
            items=[binding.model_copy(deep=True) for binding in snapshot.voice_bindings],
        )

    def require_active_session(self) -> ActiveDocumentState:
        active_session = self._repository.get_active_session()
        if active_session is None:
            raise EditSessionNotFoundError("Active edit session not found.")
        return active_session

    def _get_available_composition_manifest_id(self, snapshot: DocumentSnapshot | None) -> str | None:
        if snapshot is None:
            return None
        if snapshot.composition_manifest_id is not None:
            return snapshot.composition_manifest_id
        export_job = self._repository.get_latest_completed_export_job(
            document_id=snapshot.document_id,
            document_version=snapshot.document_version,
            export_kind="composition",
        )
        if export_job is None or export_job.output_manifest is None:
            return None
        return export_job.output_manifest.composition_manifest_id

    def _load_timeline(self, snapshot: DocumentSnapshot | None) -> TimelineManifest | None:
        if snapshot is None or snapshot.timeline_manifest_id is None:
            return None
        return self._asset_store.load_timeline_manifest(snapshot.timeline_manifest_id)
