from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from backend.app.core.exceptions import EditSessionNotFoundError
from backend.app.repositories.edit_session_repository import EditSessionRepository
from backend.app.schemas.edit_session import (
    ActiveDocumentState,
    BaselineSnapshotResponse,
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
