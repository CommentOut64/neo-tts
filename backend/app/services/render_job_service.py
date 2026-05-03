from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import threading
import time
from types import SimpleNamespace
from typing import Callable
from uuid import uuid4

import numpy as np

from backend.app.core.logging import get_logger
from backend.app.core.exceptions import (
    ActiveRenderJobConflictError,
    AssetNotFoundError,
    EditSessionNotFoundError,
    SnapshotStateError,
)
from backend.app.inference.audio_processing import build_wav_bytes, float_audio_chunk_to_pcm16_bytes
from backend.app.inference.editable_gateway import EditableInferenceGateway
from backend.app.inference.editable_types import (
    BlockCompositionAssetPayload,
    BoundaryAssetPayload,
    DocumentCompositionManifestPayload,
    PreviewPayload,
    ReferenceContext,
    RenderBlock,
    ResolvedRenderContext,
    ResolvedVoiceBinding,
    SegmentRenderAssetPayload,
    build_boundary_asset_id,
)
from backend.app.inference.text_processing import split_text_segments_zh_period
from backend.app.repositories.edit_session_repository import EditSessionRepository
from backend.app.schemas.edit_session import (
    ActiveDocumentState,
    AppendSegmentsRequest,
    CheckpointState,
    ConfigurationCommitResponse,
    CompositionResponse,
    CreateSegmentRequest,
    DocumentSnapshot,
    EditableEdge,
    EditableSegment,
    GroupListResponse,
    InitializeEditSessionRequest,
    ReferenceBindingOverride,
    MergeSegmentsRequest,
    MoveSegmentRangeRequest,
    PlaybackMapResponse,
    PreviewRequest,
    PreviewResponse,
    ReorderSegmentsRequest,
    RenderProfile,
    RenderProfilePatchRequest,
    RenderProfileListResponse,
    SegmentAssetResponse,
    StandardizationPreviewRequest,
    StandardizationPreviewResponse,
    StandardizationPreviewSegment,
    SegmentBatchRenderProfilePatchRequest,
    SegmentBatchVoiceBindingPatchRequest,
    SegmentGroup,
    SplitSegmentRequest,
    BoundaryAssetResponse,
    RenderJobAcceptedResponse,
    RenderJobRecord,
    RenderJobResponse,
    SwapSegmentsRequest,
    TimelineBlockEntry,
    TimelineManifest,
    UpdateEdgeRequest,
    UpdateSegmentRequest,
    VoiceBinding,
    VoiceBindingListResponse,
    VoiceBindingPatchRequest,
)
from backend.app.services.block_planner import BlockPlanner
from backend.app.services.block_render_asset_persister import BlockRenderAssetPersister
from backend.app.services.block_render_request_builder import BlockRenderRequestBuilder
from backend.app.services.composition_builder import CompositionBuilder
from backend.app.services.formal_block_assembler import FormalBlockAssembler
from backend.app.services.edge_service import EdgeService
from backend.app.services.edit_asset_store import EditAssetStore
from backend.app.services.audio_delivery_service import AudioDeliveryService
from backend.app.services.edit_session_runtime import EditSessionRuntime
from backend.app.services.edit_session_service import EditSessionService
from backend.app.services.inference_runtime import InferenceRuntimeController
from backend.app.services.playback_map_service import PlaybackMapService
from backend.app.services.render_planner import RenderPlanner, TargetedRenderPlan
from backend.app.services.render_job_progress_policy import (
    PREPARE_END_PROGRESS,
    PREPARE_START_PROGRESS,
    build_prepare_progress,
    build_prepare_progress_from_local,
    build_render_segment_progress,
)
from backend.app.services.checkpoint_service import CheckpointService
from backend.app.services.segment_service import SegmentService
from backend.app.services.segment_group_service import SegmentGroupService
from backend.app.services.render_config_resolver import RenderConfigResolver
from backend.app.services.timeline_manifest_service import TimelineManifestService
from backend.app.services.reference_binding import build_binding_key
from backend.app.services.render_asset_lifecycle import RenderAssetLifecycle
from backend.app.text.segment_standardizer import (
    build_standardization_preview,
    split_text_segments_with_terminal_capsules,
    standardize_segment_text,
    standardize_segment_texts,
)
from backend.app.inference.block_adapter_registry import AdapterRegistry
from backend.app.inference.block_adapter_errors import BlockAdapterError
from backend.app.inference.block_adapter_types import SegmentScopeUnsupported
from backend.app.tts_registry.model_registry import ModelRegistry
from backend.app.tts_registry.secret_store import SecretStore

render_job_logger = get_logger("render_job_service")


class _CancelledJobError(RuntimeError):
    pass


class _PartialRenderCommitted(RuntimeError):
    def __init__(self, *, checkpoint: CheckpointState, status: str, message: str) -> None:
        super().__init__(message)
        self.checkpoint = checkpoint
        self.status = status
        self.message = message


@dataclass
class RenderPlan:
    job_id: str
    job_kind: str
    document_id: str
    request: InitializeEditSessionRequest
    document_version: int = 1
    context: ReferenceContext | None = None
    segments: list[EditableSegment] = field(default_factory=list)
    edges: list[EditableEdge] = field(default_factory=list)
    groups: list[SegmentGroup] = field(default_factory=list)
    render_profiles: list[RenderProfile] = field(default_factory=list)
    voice_bindings: list[VoiceBinding] = field(default_factory=list)
    default_render_profile_id: str | None = None
    default_voice_binding_id: str | None = None
    segment_assets: dict[str, SegmentRenderAssetPayload] = field(default_factory=dict)
    boundary_assets: dict[str, BoundaryAssetPayload] = field(default_factory=dict)
    blocks: list[RenderBlock] = field(default_factory=list)
    block_assets: list[BlockCompositionAssetPayload] = field(default_factory=list)
    composition_manifest: DocumentCompositionManifestPayload | None = None
    timeline_manifest: TimelineManifest | None = None
    context_cache: dict[str, ReferenceContext] = field(default_factory=dict)
    target_segment_ids: set[str] = field(default_factory=set)
    target_edge_ids: set[str] = field(default_factory=set)
    target_block_ids: set[str] = field(default_factory=set)
    compose_only: bool = False
    earliest_changed_order_key: int | None = None
    timeline_reflow_required: bool = False
    change_reason: str | None = None
    skip_render: bool = False
    skip_compose: bool = False
    emitted_block_ids: set[str] = field(default_factory=set)
    emitted_segment_ids: set[str] = field(default_factory=set)
    changed_block_asset_ids: set[str] = field(default_factory=set)
    inference_task_id: str | None = None
    inference_total_segments: int = 0
    execution_mode: str = "block_first"


@dataclass(frozen=True)
class QueuedInitializeJob:
    request: InitializeEditSessionRequest
    execution_mode: str


@dataclass(frozen=True)
class QueuedEditJob:
    job_kind: str
    request: InitializeEditSessionRequest
    snapshot: DocumentSnapshot
    target_segment_ids: set[str]
    target_edge_ids: set[str]
    target_block_ids: set[str]
    compose_only: bool = False
    earliest_changed_order_key: int | None = None
    timeline_reflow_required: bool = False
    change_reason: str | None = None
    skip_render: bool = False
    skip_compose: bool = False
    execution_mode: str = "block_first"


class RenderJobService:
    def __init__(
        self,
        *,
        repository: EditSessionRepository,
        asset_store: EditAssetStore,
        runtime: EditSessionRuntime,
        inference_runtime: InferenceRuntimeController | None = None,
        session_service: EditSessionService,
        gateway: EditableInferenceGateway,
        block_planner: BlockPlanner | None = None,
        composition_builder: CompositionBuilder | None = None,
        playback_map_service: PlaybackMapService | None = None,
        timeline_manifest_service: TimelineManifestService | None = None,
        segment_service: SegmentService | None = None,
        edge_service: EdgeService | None = None,
        segment_group_service: SegmentGroupService | None = None,
        render_planner: RenderPlanner | None = None,
        audio_delivery_service: AudioDeliveryService | None = None,
        checkpoint_service: CheckpointService | None = None,
        model_registry: ModelRegistry | None = None,
        adapter_registry: AdapterRegistry | None = None,
        secret_store: SecretStore | None = None,
        block_render_request_builder: BlockRenderRequestBuilder | None = None,
        block_render_asset_persister: BlockRenderAssetPersister | None = None,
        block_adapter_selector: Callable[..., object] | None = None,
        run_jobs_in_background: bool = True,
        preview_ttl_seconds: int = 600,
    ) -> None:
        self._repository = repository
        self._asset_store = asset_store
        self._runtime = runtime
        self._inference_runtime = inference_runtime
        self._session_service = session_service
        self._gateway = gateway
        self._block_planner = block_planner or BlockPlanner()
        self._composition_builder = composition_builder or CompositionBuilder()
        self._playback_map_service = playback_map_service or PlaybackMapService()
        self._timeline_manifest_service = timeline_manifest_service or TimelineManifestService()
        self._edge_service = edge_service or EdgeService(repository=repository)
        self._segment_service = segment_service or SegmentService(
            repository=repository,
            edge_service=self._edge_service,
        )
        self._segment_group_service = segment_group_service or SegmentGroupService()
        self._render_planner = render_planner or RenderPlanner(block_planner=self._block_planner)
        self._render_config_resolver = RenderConfigResolver(
            model_registry=model_registry,
            adapter_registry=adapter_registry,
            secret_store=secret_store,
            workspace_service=session_service,
        )
        self._adapter_registry = adapter_registry or AdapterRegistry()
        self._secret_store = secret_store
        self._audio_delivery_service = audio_delivery_service or AudioDeliveryService()
        self._block_render_request_builder = block_render_request_builder
        self._block_render_asset_persister = block_render_asset_persister
        self._block_adapter_selector = block_adapter_selector
        self._render_asset_lifecycle = RenderAssetLifecycle(
            repository=repository,
            asset_store=asset_store,
        )
        self._checkpoint_service = checkpoint_service or CheckpointService(
            repository=repository,
            asset_store=asset_store,
            gateway=gateway,
            block_planner=self._block_planner,
            composition_builder=self._composition_builder,
            timeline_manifest_service=self._timeline_manifest_service,
            model_registry=model_registry,
            adapter_registry=adapter_registry,
            secret_store=secret_store,
        )
        self._run_jobs_in_background = run_jobs_in_background
        self._preview_ttl_seconds = preview_ttl_seconds
        self._queued_requests: dict[str, QueuedInitializeJob] = {}
        self._queued_edit_jobs: dict[str, QueuedEditJob] = {}

    def _assert_can_commit_configuration(self) -> None:
        try:
            self._runtime.assert_can_start()
        except RuntimeError as exc:
            raise ActiveRenderJobConflictError(str(exc)) from exc

    def create_initialize_job(self, request: InitializeEditSessionRequest) -> RenderJobAcceptedResponse:
        try:
            self._runtime.assert_can_start()
        except RuntimeError as exc:
            raise ActiveRenderJobConflictError(str(exc)) from exc

        prepared_request = self._session_service.prepare_initialize_request(request)
        render_job_logger.info(
            "initialize request prepared voice_id={} model_id={} text_language={} segment_boundary_mode={} reference_audio_path={} reference_language={} reference_text_preview={}",
            prepared_request.voice_id,
            prepared_request.model_id,
            prepared_request.text_language,
            prepared_request.segment_boundary_mode,
            prepared_request.reference_audio_path,
            prepared_request.reference_language,
            (prepared_request.reference_text or "")[:80],
        )
        session, job = self._session_service.initialize_document(prepared_request)
        self._queued_requests[job.job_id] = QueuedInitializeJob(
            request=prepared_request,
            execution_mode="block_first",
        )
        job_record = RenderJobRecord(
            job_id=job.job_id,
            document_id=session.document_id,
            job_kind="initialize",
            status=job.status,
            snapshot_id=None,
            target_segment_ids=[],
            target_edge_ids=[],
            target_block_ids=[],
            progress=job.progress,
            message=job.message,
            cancel_requested=job.cancel_requested,
            pause_requested=job.pause_requested,
            result_document_version=None,
            updated_at=job.updated_at,
        )
        self._repository.save_render_job(job_record)
        self._runtime.start_job(job)
        self._persist_runtime_job(job.job_id)

        if self._run_jobs_in_background:
            worker = threading.Thread(target=self.run_initialize_job, args=(job.job_id,), daemon=True)
            worker.start()
        return RenderJobAcceptedResponse(job=self.get_job(job.job_id) or job)

    def create_insert_segment_job(self, body: CreateSegmentRequest) -> RenderJobAcceptedResponse:
        before_snapshot = self._session_service.get_head_snapshot()
        mutation = self._segment_service.insert_segment(
            after_segment_id=body.after_segment_id,
            raw_text=body.raw_text,
            text_language=body.text_language,
            inference_override=body.inference_override,
            snapshot=before_snapshot,
        )
        assert mutation.segment is not None
        impact = self._render_planner.for_segment_insert(
            before_snapshot=before_snapshot,
            after_snapshot=mutation.snapshot,
            segment_id=mutation.segment.segment_id,
        )
        return self._enqueue_edit_job(
            job_kind="segment_insert",
            message=f"已创建插段作业，目标段 {mutation.segment.segment_id}。",
            snapshot=mutation.snapshot,
            impact=impact,
        )

    def create_append_job(self, body: AppendSegmentsRequest) -> RenderJobAcceptedResponse:
        before_snapshot = self._session_service.get_head_snapshot()
        after_segment_id = body.after_segment_id
        if after_segment_id is None and before_snapshot.segments:
            after_segment_id = before_snapshot.segments[-1].segment_id

        working_snapshot = before_snapshot
        group_id: str | None = body.target_group_id
        existing_group_segment_ids: set[str] = set()
        if group_id is None and (body.group_render_profile is not None or body.group_voice_binding is not None):
            group_mutation = self._segment_group_service.ensure_group(
                snapshot=working_snapshot,
                target_group_id=None,
                created_by="append",
            )
            working_snapshot = group_mutation.snapshot
            group_id = group_mutation.group.group_id
        elif group_id is not None:
            group_mutation = self._segment_group_service.ensure_group(
                snapshot=working_snapshot,
                target_group_id=group_id,
                created_by="append",
            )
            working_snapshot = group_mutation.snapshot
            existing_group_segment_ids = set(group_mutation.group.segment_ids)

        group_config_changed = body.group_render_profile is not None or body.group_voice_binding is not None
        if group_id is not None and body.group_render_profile is not None:
            working_snapshot = self._segment_group_service.update_group_render_profile(
                group_id,
                body.group_render_profile,
                snapshot=working_snapshot,
            ).snapshot
        if group_id is not None and body.group_voice_binding is not None:
            base_binding = self._get_voice_binding(
                working_snapshot,
                self._resolve_group_assigned_voice_binding_id(working_snapshot, group_id),
            )
            working_snapshot = self._segment_group_service.update_group_voice_binding(
                group_id,
                body.group_voice_binding,
                snapshot=working_snapshot,
                projected_voice=self._resolve_projected_voice_for_binding_patch(
                    base_binding=base_binding,
                    patch=body.group_voice_binding,
                ),
            ).snapshot

        raw_segments = self._split_raw_segments(body.raw_text, segment_boundary_mode=body.segment_boundary_mode)
        mutation = self._segment_service.append_segments(
            after_segment_id=after_segment_id,
            raw_segments=raw_segments,
            text_language=body.text_language,
            group_id=group_id,
            render_profile_id=(
                self._resolve_group_assigned_render_profile_id(working_snapshot, group_id)
                if group_id is not None
                else working_snapshot.default_render_profile_id
            ),
            voice_binding_id=(
                self._resolve_group_assigned_voice_binding_id(working_snapshot, group_id)
                if group_id is not None
                else working_snapshot.default_voice_binding_id
            ),
            snapshot=working_snapshot,
        )
        if group_id is not None:
            mutation_snapshot = self._segment_group_service.attach_segments(
                snapshot=mutation.snapshot,
                group_id=group_id,
                segment_ids=[segment.segment_id for segment in mutation.segments],
            ).snapshot
        else:
            mutation_snapshot = mutation.snapshot
        rerender_existing_segment_ids = existing_group_segment_ids if group_config_changed else set()
        marked_snapshot = self._mark_segments_for_rerender(
            snapshot=mutation_snapshot,
            segment_ids=rerender_existing_segment_ids,
        )
        changed_segment_ids = {segment.segment_id for segment in mutation.segments} | rerender_existing_segment_ids
        impact = self._render_planner.for_snapshot_change(
            before_snapshot=before_snapshot,
            after_snapshot=marked_snapshot,
            changed_segment_ids=changed_segment_ids,
            change_reason="append",
        )
        return self._enqueue_edit_job(
            job_kind="append",
            message=f"已创建追加作业，新增 {len(mutation.segments)} 个目标段。",
            snapshot=marked_snapshot,
            impact=impact,
        )

    def create_update_segment_job(self, segment_id: str, patch: UpdateSegmentRequest) -> RenderJobAcceptedResponse:
        before_snapshot = self._session_service.get_head_snapshot()
        mutation = self._segment_service.update_segment(segment_id, patch, snapshot=before_snapshot)
        impact = self._render_planner.for_segment_update(
            before_snapshot=before_snapshot,
            after_snapshot=mutation.snapshot,
            segment_id=segment_id,
        )
        return self._enqueue_edit_job(
            job_kind="segment_update",
            message=f"已创建改段作业，目标段 {segment_id}。",
            snapshot=mutation.snapshot,
            impact=impact,
        )

    def create_delete_segment_job(self, segment_id: str) -> RenderJobAcceptedResponse:
        before_snapshot = self._session_service.get_head_snapshot()
        mutation = self._segment_service.delete_segment(segment_id, snapshot=before_snapshot)
        impact = self._render_planner.for_segment_delete(
            before_snapshot=before_snapshot,
            after_snapshot=mutation.snapshot,
            segment_id=segment_id,
        )
        return self._enqueue_edit_job(
            job_kind="segment_delete",
            message=f"已创建删段作业，目标段 {segment_id}。",
            snapshot=mutation.snapshot,
            impact=impact,
        )

    def create_swap_segments_job(self, body: SwapSegmentsRequest) -> RenderJobAcceptedResponse:
        before_snapshot = self._session_service.get_head_snapshot()
        mutation = self._segment_service.swap_segments(
            body.first_segment_id,
            body.second_segment_id,
            snapshot=before_snapshot,
        )
        impact = self._render_planner.for_segment_swap(
            before_snapshot=before_snapshot,
            after_snapshot=mutation.snapshot,
            swapped_segment_ids={body.first_segment_id, body.second_segment_id},
        )
        return self._enqueue_edit_job(
            job_kind="segment_swap",
            message=f"已创建换段作业，目标段 {body.first_segment_id} 与 {body.second_segment_id}。",
            snapshot=mutation.snapshot,
            impact=impact,
        )

    def create_move_range_job(self, body: MoveSegmentRangeRequest) -> RenderJobAcceptedResponse:
        before_snapshot = self._session_service.get_head_snapshot()
        mutation = self._segment_service.move_range(
            body.segment_ids,
            after_segment_id=body.after_segment_id,
            snapshot=before_snapshot,
        )
        impact = self._render_planner.for_snapshot_change(
            before_snapshot=before_snapshot,
            after_snapshot=mutation.snapshot,
            changed_segment_ids=set(body.segment_ids),
            change_reason="segment_move_range",
        )
        return self._enqueue_edit_job(
            job_kind="segment_move_range",
            message=f"已创建移段作业，目标段 {len(body.segment_ids)} 个。",
            snapshot=mutation.snapshot,
            impact=impact,
        )

    def create_reorder_segments_job(self, body: ReorderSegmentsRequest) -> RenderJobAcceptedResponse:
        before_snapshot = self._session_service.get_head_snapshot()
        self._assert_document_version_matches(
            expected_version=body.base_document_version,
            actual_version=before_snapshot.document_version,
        )
        mutation = self._segment_service.reorder_segments(
            body.ordered_segment_ids,
            snapshot=before_snapshot,
        )
        impact = self._render_planner.for_segment_reorder(
            before_snapshot=before_snapshot,
            after_snapshot=mutation.snapshot,
            reordered_segment_ids=set(body.ordered_segment_ids),
        )
        return self._enqueue_edit_job(
            job_kind="segment_reorder",
            message=f"已创建重排作业，目标段 {len(body.ordered_segment_ids)} 个。",
            snapshot=mutation.snapshot,
            impact=impact,
        )

    def create_split_segment_job(self, body: SplitSegmentRequest) -> RenderJobAcceptedResponse:
        before_snapshot = self._session_service.get_head_snapshot()
        mutation = self._segment_service.split_segment(
            body.segment_id,
            left_text=body.left_text,
            right_text=body.right_text,
            text_language=body.text_language,
            snapshot=before_snapshot,
        )
        impact = self._render_planner.for_snapshot_change(
            before_snapshot=before_snapshot,
            after_snapshot=mutation.snapshot,
            changed_segment_ids={segment.segment_id for segment in mutation.segments},
            change_reason="segment_split",
        )
        return self._enqueue_edit_job(
            job_kind="segment_split",
            message=f"已创建拆段作业，目标段 {body.segment_id}。",
            snapshot=mutation.snapshot,
            impact=impact,
        )

    def create_merge_segments_job(self, body: MergeSegmentsRequest) -> RenderJobAcceptedResponse:
        before_snapshot = self._session_service.get_head_snapshot()
        mutation = self._segment_service.merge_segments(
            body.left_segment_id,
            body.right_segment_id,
            snapshot=before_snapshot,
        )
        impact = self._render_planner.for_snapshot_change(
            before_snapshot=before_snapshot,
            after_snapshot=mutation.snapshot,
            changed_segment_ids={mutation.segment.segment_id} if mutation.segment is not None else set(),
            change_reason="segment_merge",
        )
        return self._enqueue_edit_job(
            job_kind="segment_merge",
            message=f"已创建合段作业，目标段 {body.left_segment_id} 与 {body.right_segment_id}。",
            snapshot=mutation.snapshot,
            impact=impact,
        )

    def create_update_edge_job(self, edge_id: str, patch: UpdateEdgeRequest) -> RenderJobAcceptedResponse:
        before_snapshot = self._session_service.get_head_snapshot()
        mutation = self._edge_service.update_edge(edge_id, patch, snapshot=before_snapshot)
        impact = self._render_planner.for_edge_update(
            before_snapshot=before_snapshot,
            after_snapshot=mutation.snapshot,
            edge_id=edge_id,
            pause_only=mutation.pause_only,
        )
        return self._enqueue_edit_job(
            job_kind="edge_update",
            message=f"已创建边更新作业，目标边 {edge_id}。",
            snapshot=mutation.snapshot,
            impact=impact,
        )

    def create_patch_session_render_profile_job(self, patch: RenderProfilePatchRequest) -> RenderJobAcceptedResponse:
        before_snapshot = self._session_service.get_head_snapshot()
        patch = self._prepare_render_profile_patch(patch)
        after_snapshot = self._segment_group_service.update_session_render_profile(patch, snapshot=before_snapshot)
        return self._enqueue_configuration_job(
            job_kind="session_render_profile_patch",
            message="已创建会话级渲染参数更新作业。",
            before_snapshot=before_snapshot,
            after_snapshot=after_snapshot,
            change_reason="session_render_profile_patch",
        )

    def create_patch_group_render_profile_job(
        self,
        group_id: str,
        patch: RenderProfilePatchRequest,
    ) -> RenderJobAcceptedResponse:
        before_snapshot = self._session_service.get_head_snapshot()
        patch = self._prepare_render_profile_patch(patch)
        after_snapshot = self._segment_group_service.update_group_render_profile(
            group_id,
            patch,
            snapshot=before_snapshot,
        ).snapshot
        return self._enqueue_configuration_job(
            job_kind="group_render_profile_patch",
            message=f"已创建分组渲染参数更新作业，目标分组 {group_id}。",
            before_snapshot=before_snapshot,
            after_snapshot=after_snapshot,
            change_reason="group_render_profile_patch",
        )

    def create_patch_segment_render_profile_job(
        self,
        segment_id: str,
        patch: RenderProfilePatchRequest,
    ) -> RenderJobAcceptedResponse:
        before_snapshot = self._session_service.get_head_snapshot()
        patch = self._prepare_render_profile_patch(patch)
        working_snapshot, profile = self._segment_group_service.create_render_profile(
            snapshot=before_snapshot,
            scope="segment",
            patch=patch,
            base_profile_id=self._resolve_segment_assigned_render_profile_id(before_snapshot, segment_id),
        )
        after_snapshot = self._segment_service.update_segment_render_profile(
            segment_id,
            profile.render_profile_id,
            snapshot=working_snapshot,
        ).snapshot
        return self._enqueue_configuration_job(
            job_kind="segment_render_profile_patch",
            message=f"已创建段级渲染参数更新作业，目标段 {segment_id}。",
            before_snapshot=before_snapshot,
            after_snapshot=after_snapshot,
            change_reason="segment_render_profile_patch",
        )

    def create_patch_session_voice_binding_job(self, patch: VoiceBindingPatchRequest) -> RenderJobAcceptedResponse:
        before_snapshot = self._session_service.get_head_snapshot()
        base_binding = self._get_voice_binding(before_snapshot, before_snapshot.default_voice_binding_id)
        after_snapshot = self._segment_group_service.update_session_voice_binding(
            patch,
            snapshot=before_snapshot,
            projected_voice=self._resolve_projected_voice_for_binding_patch(base_binding=base_binding, patch=patch),
        )
        return self._enqueue_configuration_job(
            job_kind="session_voice_binding_patch",
            message="已创建会话级 voice/model 绑定更新作业。",
            before_snapshot=before_snapshot,
            after_snapshot=after_snapshot,
            change_reason="session_voice_binding_patch",
        )

    def create_patch_group_voice_binding_job(
        self,
        group_id: str,
        patch: VoiceBindingPatchRequest,
    ) -> RenderJobAcceptedResponse:
        before_snapshot = self._session_service.get_head_snapshot()
        base_binding = self._get_voice_binding(
            before_snapshot,
            self._resolve_group_assigned_voice_binding_id(before_snapshot, group_id),
        )
        after_snapshot = self._segment_group_service.update_group_voice_binding(
            group_id,
            patch,
            snapshot=before_snapshot,
            projected_voice=self._resolve_projected_voice_for_binding_patch(base_binding=base_binding, patch=patch),
        ).snapshot
        return self._enqueue_configuration_job(
            job_kind="group_voice_binding_patch",
            message=f"已创建分组 voice/model 绑定更新作业，目标分组 {group_id}。",
            before_snapshot=before_snapshot,
            after_snapshot=after_snapshot,
            change_reason="group_voice_binding_patch",
        )

    def create_patch_segment_voice_binding_job(
        self,
        segment_id: str,
        patch: VoiceBindingPatchRequest,
    ) -> RenderJobAcceptedResponse:
        before_snapshot = self._session_service.get_head_snapshot()
        base_binding = self._get_voice_binding(
            before_snapshot,
            self._resolve_segment_assigned_voice_binding_id(before_snapshot, segment_id),
        )
        working_snapshot, binding = self._segment_group_service.create_voice_binding(
            snapshot=before_snapshot,
            scope="segment",
            patch=patch,
            base_binding_id=self._resolve_segment_assigned_voice_binding_id(before_snapshot, segment_id),
            projected_voice=self._resolve_projected_voice_for_binding_patch(base_binding=base_binding, patch=patch),
        )
        after_snapshot = self._segment_service.update_segment_voice_binding(
            segment_id,
            binding.voice_binding_id,
            snapshot=working_snapshot,
        ).snapshot
        return self._enqueue_configuration_job(
            job_kind="segment_voice_binding_patch",
            message=f"已创建段级 voice/model 绑定更新作业，目标段 {segment_id}。",
            before_snapshot=before_snapshot,
            after_snapshot=after_snapshot,
            change_reason="segment_voice_binding_patch",
        )

    def create_patch_segments_render_profile_batch_job(
        self,
        body: SegmentBatchRenderProfilePatchRequest,
    ) -> RenderJobAcceptedResponse:
        before_snapshot = self._session_service.get_head_snapshot()
        prepared_patch = self._prepare_render_profile_patch(body.patch)
        working_snapshot, profile = self._segment_group_service.create_render_profile(
            snapshot=before_snapshot,
            scope="segment",
            patch=prepared_patch,
            base_profile_id=before_snapshot.default_render_profile_id,
        )
        after_snapshot = self._segment_service.update_segments_render_profile(
            body.segment_ids,
            profile.render_profile_id,
            snapshot=working_snapshot,
        ).snapshot
        return self._enqueue_configuration_job(
            job_kind="segment_render_profile_batch_patch",
            message=f"已创建段级批量渲染参数更新作业，目标段 {len(body.segment_ids)} 个。",
            before_snapshot=before_snapshot,
            after_snapshot=after_snapshot,
            change_reason="segment_render_profile_batch_patch",
        )

    def create_patch_segments_voice_binding_batch_job(
        self,
        body: SegmentBatchVoiceBindingPatchRequest,
    ) -> RenderJobAcceptedResponse:
        before_snapshot = self._session_service.get_head_snapshot()
        base_binding = self._get_voice_binding(before_snapshot, before_snapshot.default_voice_binding_id)
        working_snapshot, binding = self._segment_group_service.create_voice_binding(
            snapshot=before_snapshot,
            scope="segment",
            patch=body.patch,
            base_binding_id=before_snapshot.default_voice_binding_id,
            projected_voice=self._resolve_projected_voice_for_binding_patch(
                base_binding=base_binding,
                patch=body.patch,
            ),
        )
        after_snapshot = self._segment_service.update_segments_voice_binding(
            body.segment_ids,
            binding.voice_binding_id,
            snapshot=working_snapshot,
        ).snapshot
        return self._enqueue_configuration_job(
            job_kind="segment_voice_binding_batch_patch",
            message=f"已创建段级批量 voice/model 绑定更新作业，目标段 {len(body.segment_ids)} 个。",
            before_snapshot=before_snapshot,
            after_snapshot=after_snapshot,
            change_reason="segment_voice_binding_batch_patch",
        )

    def create_restore_baseline_job(self) -> RenderJobAcceptedResponse:
        try:
            self._runtime.assert_can_start()
        except RuntimeError as exc:
            raise ActiveRenderJobConflictError(str(exc)) from exc

        active_session = self._session_service.require_active_session()
        if active_session.baseline_snapshot_id is None:
            raise EditSessionNotFoundError("Baseline snapshot not found.")
        baseline_snapshot = self._repository.get_snapshot(active_session.baseline_snapshot_id)
        if baseline_snapshot is None:
            raise EditSessionNotFoundError("Baseline snapshot not found.")
        current_snapshot = self._session_service.get_head_snapshot()
        restored_snapshot = baseline_snapshot.model_copy(
            deep=True,
            update={
                "snapshot_kind": "head",
                "document_version": current_snapshot.document_version + 1,
            },
        )
        return self._enqueue_edit_job(
            job_kind="restore_baseline",
            message="已创建恢复基线作业。",
            snapshot=restored_snapshot,
            impact=TargetedRenderPlan(),
            skip_render=True,
            skip_compose=True,
        )

    def commit_update_edge(self, edge_id: str, patch: UpdateEdgeRequest) -> ConfigurationCommitResponse:
        self._assert_can_commit_configuration()
        before_snapshot = self._session_service.get_head_snapshot()
        after_snapshot = self._edge_service.update_edge(edge_id, patch, snapshot=before_snapshot).snapshot
        return self._session_service.commit_configuration_snapshot(
            before_snapshot=before_snapshot,
            after_snapshot=after_snapshot,
        )

    def commit_patch_session_render_profile(self, patch: RenderProfilePatchRequest) -> ConfigurationCommitResponse:
        self._assert_can_commit_configuration()
        before_snapshot = self._session_service.get_head_snapshot()
        patch = self._prepare_render_profile_patch(patch)
        after_snapshot = self._segment_group_service.update_session_render_profile(patch, snapshot=before_snapshot)
        changed_segment_ids = self._collect_changed_segment_ids(
            before_snapshot=before_snapshot,
            after_snapshot=after_snapshot,
        )
        return self._session_service.commit_configuration_snapshot(
            before_snapshot=before_snapshot,
            after_snapshot=after_snapshot,
            pending_segment_ids=changed_segment_ids,
        )

    def commit_patch_session_voice_binding(self, patch: VoiceBindingPatchRequest) -> ConfigurationCommitResponse:
        self._assert_can_commit_configuration()
        before_snapshot = self._session_service.get_head_snapshot()
        base_binding = self._get_voice_binding(before_snapshot, before_snapshot.default_voice_binding_id)
        after_snapshot = self._segment_group_service.update_session_voice_binding(
            patch,
            snapshot=before_snapshot,
            projected_voice=self._resolve_projected_voice_for_binding_patch(base_binding=base_binding, patch=patch),
        )
        changed_segment_ids = self._collect_changed_segment_ids(
            before_snapshot=before_snapshot,
            after_snapshot=after_snapshot,
        )
        return self._session_service.commit_configuration_snapshot(
            before_snapshot=before_snapshot,
            after_snapshot=after_snapshot,
            pending_segment_ids=changed_segment_ids,
        )

    def commit_patch_segment_render_profile(
        self,
        segment_id: str,
        patch: RenderProfilePatchRequest,
    ) -> ConfigurationCommitResponse:
        self._assert_can_commit_configuration()
        before_snapshot = self._session_service.get_head_snapshot()
        patch = self._prepare_render_profile_patch(patch)
        working_snapshot, profile = self._segment_group_service.create_render_profile(
            snapshot=before_snapshot,
            scope="segment",
            patch=patch,
            base_profile_id=self._resolve_segment_assigned_render_profile_id(before_snapshot, segment_id),
        )
        after_snapshot = self._segment_service.update_segment_render_profile(
            segment_id,
            profile.render_profile_id,
            snapshot=working_snapshot,
        ).snapshot
        changed_segment_ids = self._collect_changed_segment_ids(
            before_snapshot=before_snapshot,
            after_snapshot=after_snapshot,
        )
        return self._session_service.commit_configuration_snapshot(
            before_snapshot=before_snapshot,
            after_snapshot=after_snapshot,
            pending_segment_ids=changed_segment_ids,
        )

    def commit_patch_segment_voice_binding(
        self,
        segment_id: str,
        patch: VoiceBindingPatchRequest,
    ) -> ConfigurationCommitResponse:
        self._assert_can_commit_configuration()
        before_snapshot = self._session_service.get_head_snapshot()
        base_binding = self._get_voice_binding(
            before_snapshot,
            self._resolve_segment_assigned_voice_binding_id(before_snapshot, segment_id),
        )
        working_snapshot, binding = self._segment_group_service.create_voice_binding(
            snapshot=before_snapshot,
            scope="segment",
            patch=patch,
            base_binding_id=self._resolve_segment_assigned_voice_binding_id(before_snapshot, segment_id),
            projected_voice=self._resolve_projected_voice_for_binding_patch(base_binding=base_binding, patch=patch),
        )
        after_snapshot = self._segment_service.update_segment_voice_binding(
            segment_id,
            binding.voice_binding_id,
            snapshot=working_snapshot,
        ).snapshot
        changed_segment_ids = self._collect_changed_segment_ids(
            before_snapshot=before_snapshot,
            after_snapshot=after_snapshot,
        )
        return self._session_service.commit_configuration_snapshot(
            before_snapshot=before_snapshot,
            after_snapshot=after_snapshot,
            pending_segment_ids=changed_segment_ids,
        )

    def commit_patch_segments_render_profile_batch(
        self,
        body: SegmentBatchRenderProfilePatchRequest,
    ) -> ConfigurationCommitResponse:
        self._assert_can_commit_configuration()
        before_snapshot = self._session_service.get_head_snapshot()
        prepared_patch = self._prepare_render_profile_patch(body.patch)
        working_snapshot, profile = self._segment_group_service.create_render_profile(
            snapshot=before_snapshot,
            scope="segment",
            patch=prepared_patch,
            base_profile_id=before_snapshot.default_render_profile_id,
        )
        after_snapshot = self._segment_service.update_segments_render_profile(
            body.segment_ids,
            profile.render_profile_id,
            snapshot=working_snapshot,
        ).snapshot
        changed_segment_ids = self._collect_changed_segment_ids(
            before_snapshot=before_snapshot,
            after_snapshot=after_snapshot,
        )
        return self._session_service.commit_configuration_snapshot(
            before_snapshot=before_snapshot,
            after_snapshot=after_snapshot,
            pending_segment_ids=changed_segment_ids,
        )

    def commit_patch_segments_voice_binding_batch(
        self,
        body: SegmentBatchVoiceBindingPatchRequest,
    ) -> ConfigurationCommitResponse:
        self._assert_can_commit_configuration()
        before_snapshot = self._session_service.get_head_snapshot()
        base_binding = self._get_voice_binding(before_snapshot, before_snapshot.default_voice_binding_id)
        working_snapshot, binding = self._segment_group_service.create_voice_binding(
            snapshot=before_snapshot,
            scope="segment",
            patch=body.patch,
            base_binding_id=before_snapshot.default_voice_binding_id,
            projected_voice=self._resolve_projected_voice_for_binding_patch(
                base_binding=base_binding,
                patch=body.patch,
            ),
        )
        after_snapshot = self._segment_service.update_segments_voice_binding(
            body.segment_ids,
            binding.voice_binding_id,
            snapshot=working_snapshot,
        ).snapshot
        changed_segment_ids = self._collect_changed_segment_ids(
            before_snapshot=before_snapshot,
            after_snapshot=after_snapshot,
        )
        return self._session_service.commit_configuration_snapshot(
            before_snapshot=before_snapshot,
            after_snapshot=after_snapshot,
            pending_segment_ids=changed_segment_ids,
        )

    def create_rerender_segment_job(self, segment_id: str) -> RenderJobAcceptedResponse:
        before_snapshot = self._session_service.get_head_snapshot()
        target_segment = next(
            (segment for segment in before_snapshot.segments if segment.segment_id == segment_id),
            None,
        )
        if target_segment is None:
            raise EditSessionNotFoundError(f"Segment '{segment_id}' not found.")
        after_snapshot = self._mark_segments_for_rerender(
            snapshot=before_snapshot,
            segment_ids={segment_id},
        ).model_copy(
            deep=True,
            update={"document_version": before_snapshot.document_version + 1},
        )
        impact = self._render_planner.for_snapshot_change(
            before_snapshot=before_snapshot,
            after_snapshot=after_snapshot,
            changed_segment_ids={segment_id},
            change_reason="segment_rerender",
        )
        return self._enqueue_edit_job(
            job_kind="segment_rerender",
            message=f"已创建段重推理作业，目标段 {segment_id}。",
            snapshot=after_snapshot,
            impact=impact,
        )

    def run_initialize_job(self, job_id: str) -> None:
        queued = self._queued_requests.get(job_id)
        job = self.get_job(job_id)
        if queued is None or job is None:
            raise EditSessionNotFoundError(f"Render job '{job_id}' not found.")

        plan = RenderPlan(
            job_id=job_id,
            job_kind="initialize",
            document_id=job.document_id,
            request=queued.request,
            execution_mode=queued.execution_mode,
        )
        try:
            self._run_transaction(plan)
            completed_job = self._runtime.get_job(job_id)
            if completed_job is not None and completed_job.status != "completed":
                self._runtime.update_job(
                    job_id,
                    status="completed",
                    progress=1.0,
                    message="初始化渲染完成。",
                    result_document_version=1,
                    current_segment_index=len(plan.segments),
                    total_segment_count=len(plan.segments),
                    current_block_index=len(plan.blocks),
                    total_block_count=len(plan.blocks),
                )
                self._persist_runtime_job(job_id)
        except _PartialRenderCommitted:
            self._persist_runtime_job(job_id)
        except BlockAdapterError as exc:
            self._log_background_job_failure(
                job_kind=plan.job_kind,
                job_id=job_id,
                document_id=job.document_id,
                phase="run_initialize_job",
                exc=exc,
            )
            self._rollback_uncommitted_assets(job_id)
            self._mark_terminal(job_id, status="failed", message=exc.message, adapter_error=exc.to_payload())
            self._mark_session_failed(job.document_id)
        except _CancelledJobError:
            try:
                self._commit_partial_after_segment(plan, status="cancelled_partial")
            except _PartialRenderCommitted:
                self._persist_runtime_job(job_id)
            except Exception as exc:
                self._log_background_job_failure(
                    job_kind=plan.job_kind,
                    job_id=job_id,
                    document_id=job.document_id,
                    phase="run_initialize_job",
                    exc=exc,
                )
                self._rollback_uncommitted_assets(job_id)
                self._mark_terminal(job_id, status="failed", message=str(exc))
                self._mark_session_failed(job.document_id)
        except Exception as exc:
            self._log_background_job_failure(
                job_kind=plan.job_kind,
                job_id=job_id,
                document_id=job.document_id,
                phase="run_initialize_job",
                exc=exc,
            )
            self._rollback_uncommitted_assets(job_id)
            self._mark_terminal(job_id, status="failed", message=str(exc))
            self._mark_session_failed(job.document_id)
        finally:
            self._queued_requests.pop(job_id, None)

    def run_edit_job(self, job_id: str) -> None:
        queued_job = self._queued_edit_jobs.get(job_id)
        job = self.get_job(job_id)
        if queued_job is None or job is None:
            raise EditSessionNotFoundError(f"Render job '{job_id}' not found.")

        plan = RenderPlan(
            job_id=job_id,
            job_kind=queued_job.job_kind,
            document_id=queued_job.snapshot.document_id,
            request=queued_job.request,
            document_version=queued_job.snapshot.document_version,
            segments=[segment.model_copy(deep=True) for segment in queued_job.snapshot.segments],
            edges=[edge.model_copy(deep=True) for edge in queued_job.snapshot.edges],
            groups=[group.model_copy(deep=True) for group in queued_job.snapshot.groups],
            render_profiles=[profile.model_copy(deep=True) for profile in queued_job.snapshot.render_profiles],
            voice_bindings=[binding.model_copy(deep=True) for binding in queued_job.snapshot.voice_bindings],
            default_render_profile_id=queued_job.snapshot.default_render_profile_id,
            default_voice_binding_id=queued_job.snapshot.default_voice_binding_id,
            target_segment_ids=set(queued_job.target_segment_ids),
            target_edge_ids=set(queued_job.target_edge_ids),
            target_block_ids=set(queued_job.target_block_ids),
            compose_only=queued_job.compose_only,
            earliest_changed_order_key=queued_job.earliest_changed_order_key,
            timeline_reflow_required=queued_job.timeline_reflow_required,
            change_reason=queued_job.change_reason,
            skip_render=queued_job.skip_render,
            skip_compose=queued_job.skip_compose,
            execution_mode=queued_job.execution_mode,
        )
        try:
            self._run_transaction(plan)
            completed_job = self._runtime.get_job(job_id)
            if completed_job is not None and completed_job.status != "completed":
                self._runtime.update_job(
                    job_id,
                    status="completed",
                    progress=1.0,
                    message="编辑作业已完成。",
                    result_document_version=plan.document_version,
                    current_segment_index=len(plan.target_segment_ids) or len(plan.segments),
                    total_segment_count=len(plan.target_segment_ids) or len(plan.segments),
                    current_block_index=len(plan.blocks),
                    total_block_count=len(plan.blocks),
                )
                self._persist_runtime_job(job_id)
        except _PartialRenderCommitted:
            self._persist_runtime_job(job_id)
        except BlockAdapterError as exc:
            self._log_background_job_failure(
                job_kind=plan.job_kind,
                job_id=job_id,
                document_id=job.document_id,
                phase="run_edit_job",
                exc=exc,
            )
            self._rollback_uncommitted_assets(job_id)
            self._mark_terminal(job_id, status="failed", message=exc.message, adapter_error=exc.to_payload())
        except _CancelledJobError:
            try:
                self._commit_partial_after_segment(plan, status="cancelled_partial")
            except _PartialRenderCommitted:
                self._persist_runtime_job(job_id)
            except Exception as exc:
                self._log_background_job_failure(
                    job_kind=plan.job_kind,
                    job_id=job_id,
                    document_id=job.document_id,
                    phase="run_edit_job",
                    exc=exc,
                )
                self._rollback_uncommitted_assets(job_id)
                self._mark_terminal(job_id, status="failed", message=str(exc))
        except Exception as exc:
            self._log_background_job_failure(
                job_kind=plan.job_kind,
                job_id=job_id,
                document_id=job.document_id,
                phase="run_edit_job",
                exc=exc,
            )
            self._rollback_uncommitted_assets(job_id)
            self._mark_terminal(job_id, status="failed", message=str(exc))
        finally:
            self._queued_edit_jobs.pop(job_id, None)

    def cancel_job(self, job_id: str) -> bool:
        accepted = self._runtime.request_cancel(job_id)
        if accepted:
            self._persist_runtime_job(job_id)
        return accepted

    def pause_job(self, job_id: str) -> bool:
        accepted = self._runtime.request_pause(job_id)
        if accepted:
            self._persist_runtime_job(job_id)
        return accepted

    def create_resume_job(self, job_id: str) -> RenderJobAcceptedResponse:
        job = self.get_job(job_id)
        if job is None:
            raise EditSessionNotFoundError(f"Render job '{job_id}' not found.")
        active_session = self._session_service.require_active_session()
        checkpoint = self._checkpoint_service.get_current_checkpoint(active_session.document_id)
        if checkpoint is None or checkpoint.job_id != job_id or checkpoint.status not in {"paused", "resumable"}:
            raise EditSessionNotFoundError(f"Resumable checkpoint for job '{job_id}' not found.")
        working_snapshot = self._repository.get_snapshot(checkpoint.working_snapshot_id)
        if working_snapshot is None:
            raise EditSessionNotFoundError(f"Checkpoint working snapshot for job '{job_id}' not found.")
        resumed_snapshot = working_snapshot.model_copy(
            deep=True,
            update={"document_version": checkpoint.document_version + 1},
        )
        remaining_segment_ids = set(checkpoint.remaining_segment_ids)
        first_remaining_order_key = next(
            (
                segment.order_key
                for segment in sorted(resumed_snapshot.segments, key=lambda item: item.order_key)
                if segment.segment_id in remaining_segment_ids
            ),
            None,
        )
        impact = TargetedRenderPlan(
            target_segment_ids=remaining_segment_ids,
            target_edge_ids={
                edge.edge_id
                for edge in resumed_snapshot.edges
                if edge.left_segment_id in remaining_segment_ids or edge.right_segment_id in remaining_segment_ids
            },
            target_block_ids=set(),
            compose_only=False,
            earliest_changed_order_key=first_remaining_order_key,
            timeline_reflow_required=True,
            change_reason="resume",
        )
        accepted = self._enqueue_edit_job(
            job_kind="resume",
            message=f"已创建恢复作业，继续渲染 {len(remaining_segment_ids)} 个剩余段。",
            snapshot=resumed_snapshot,
            impact=impact,
        )
        resumed_job = self.get_job(accepted.job.job_id)
        if resumed_job is not None:
            self._runtime.emit_event(
                resumed_job.job_id,
                "job_resumed",
                {
                    "source_job_id": job_id,
                    "checkpoint_id": checkpoint.checkpoint_id,
                    "remaining_segment_ids": checkpoint.remaining_segment_ids,
                },
            )
        return accepted

    def get_job(self, job_id: str) -> RenderJobResponse | None:
        runtime_job = self._runtime.get_job(job_id)
        if runtime_job is not None:
            return runtime_job
        record = self._repository.get_render_job(job_id)
        if record is None:
            return None
        return RenderJobResponse.model_validate(record.model_dump())

    def get_snapshot(self):
        return self._session_service.get_snapshot()

    def get_head_snapshot(self) -> DocumentSnapshot:
        return self._session_service.get_head_snapshot()

    def list_segments(self, *, limit: int, cursor: int | None):
        return self._segment_service.list_segments(limit=limit, cursor=cursor)

    def list_edges(self, *, limit: int, cursor: int | None):
        return self._edge_service.list_edges(limit=limit, cursor=cursor)

    def list_groups(self) -> GroupListResponse:
        return self._session_service.get_groups()

    def list_render_profiles(self) -> RenderProfileListResponse:
        return self._session_service.get_render_profiles()

    def list_voice_bindings(self) -> VoiceBindingListResponse:
        return self._session_service.get_voice_bindings()

    def get_composition_response(self) -> CompositionResponse:
        snapshot = self._session_service.get_head_snapshot()
        export_job = self._repository.get_latest_completed_export_job(
            document_id=snapshot.document_id,
            document_version=snapshot.document_version,
            export_kind="composition",
        )
        if export_job is None or export_job.output_manifest is None or export_job.output_manifest.composition_manifest_id is None:
            raise EditSessionNotFoundError("Composition export not found for current document version.")
        asset_id = export_job.output_manifest.composition_manifest_id
        sample_rate = self._load_sample_rate(self._asset_store.composition_asset_path(asset_id), asset_id=asset_id)
        return CompositionResponse(
            composition_manifest_id=asset_id,
            document_id=snapshot.document_id,
            document_version=snapshot.document_version,
            materialized_audio_available=True,
            audio_delivery=self._audio_delivery_service.build_descriptor(
                asset_id=asset_id,
                audio_url=f"/v1/edit-session/assets/compositions/{asset_id}/audio",
                asset_path=self._asset_store.composition_asset_path(asset_id),
                sample_rate=sample_rate,
            ),
        )

    def get_playback_map_response(self) -> PlaybackMapResponse:
        snapshot = self._session_service.get_head_snapshot()
        composition_manifest_id = self._get_available_composition_manifest_id(snapshot)
        if snapshot.timeline_manifest_id is not None:
            timeline = self._asset_store.load_timeline_manifest(snapshot.timeline_manifest_id)
            return self._playback_map_service.rebuild(manifest=timeline).model_copy(
                update={"composition_manifest_id": composition_manifest_id}
            )
        playable_sample_span = (
            (0, max(segment.assembled_audio_span[1] for segment in snapshot.segments if segment.assembled_audio_span is not None))
            if any(segment.assembled_audio_span is not None for segment in snapshot.segments)
            else None
        )
        return PlaybackMapResponse(
            document_id=snapshot.document_id,
            document_version=snapshot.document_version,
            composition_manifest_id=composition_manifest_id,
            playable_sample_span=playable_sample_span,
            entries=[
                {
                    "segment_id": segment.segment_id,
                    "order_key": segment.order_key,
                    "audio_sample_span": segment.assembled_audio_span,
                }
                for segment in sorted(snapshot.segments, key=lambda item: item.order_key)
                if segment.assembled_audio_span is not None
            ],
        )

    def build_preview(self, request: PreviewRequest) -> PreviewPayload:
        snapshot = self._session_service.get_head_snapshot()
        if request.segment_id is not None:
            segment = next((item for item in snapshot.segments if item.segment_id == request.segment_id), None)
            if segment is None or segment.render_asset_id is None:
                raise EditSessionNotFoundError(f"Segment '{request.segment_id}' preview target not found.")
            sample_rate, audio = self._asset_store.load_wav_asset(
                self._asset_store.segment_asset_path(segment.render_asset_id)
            )
            return PreviewPayload(
                preview_asset_id=f"preview-segment-{segment.render_asset_id}",
                preview_kind="segment",
                sample_rate=sample_rate,
                audio=audio,
            )

        if request.edge_id is not None:
            edge = next((item for item in snapshot.edges if item.edge_id == request.edge_id), None)
            if edge is None:
                raise EditSessionNotFoundError(f"Edge '{request.edge_id}' preview target not found.")
            segments_by_id = {segment.segment_id: segment for segment in snapshot.segments}
            left_segment = segments_by_id.get(edge.left_segment_id)
            right_segment = segments_by_id.get(edge.right_segment_id)
            if left_segment is None or right_segment is None:
                raise EditSessionNotFoundError(f"Edge '{request.edge_id}' preview target not found.")
            boundary_asset_id = build_boundary_asset_id(
                left_segment_id=edge.left_segment_id,
                left_render_version=left_segment.render_version,
                right_segment_id=edge.right_segment_id,
                right_render_version=right_segment.render_version,
                edge_version=edge.edge_version,
                boundary_strategy=edge.boundary_strategy,
            )
            try:
                sample_rate, audio = self._asset_store.load_wav_asset(
                    self._asset_store.boundary_asset_path(boundary_asset_id)
                )
            except FileNotFoundError:
                sample_rate, audio = self._build_edge_preview_from_timeline(
                    snapshot=snapshot,
                    edge_id=edge.edge_id,
                )
            return PreviewPayload(
                preview_asset_id=f"preview-edge-{boundary_asset_id}",
                preview_kind="edge",
                sample_rate=sample_rate,
                audio=audio,
            )

        assert request.block_id is not None
        if request.block_id not in snapshot.block_ids:
            raise EditSessionNotFoundError(f"Block '{request.block_id}' preview target not found.")
        sample_rate, audio = self._asset_store.load_wav_asset(self._asset_store.block_asset_path(request.block_id))
        return PreviewPayload(
            preview_asset_id=f"preview-block-{request.block_id}",
            preview_kind="block",
            sample_rate=sample_rate,
            audio=audio,
        )

    def _build_edge_preview_from_timeline(
        self,
        *,
        snapshot: DocumentSnapshot,
        edge_id: str,
    ) -> tuple[int, np.ndarray]:
        if snapshot.timeline_manifest_id is None:
            raise EditSessionNotFoundError(f"Edge '{edge_id}' preview target not found.")
        timeline = self._asset_store.load_timeline_manifest(snapshot.timeline_manifest_id)
        timeline_edge = next((entry for entry in timeline.edge_entries if entry.edge_id == edge_id), None)
        if timeline_edge is None:
            raise EditSessionNotFoundError(f"Edge '{edge_id}' preview target not found.")
        preview_start = timeline_edge.boundary_start_sample
        preview_end = timeline_edge.boundary_end_sample
        if preview_end <= preview_start:
            preview_start = timeline_edge.pause_start_sample
            preview_end = timeline_edge.pause_end_sample
        if preview_end <= preview_start:
            raise EditSessionNotFoundError(f"Edge '{edge_id}' preview target not found.")
        block_entry = next(
            (
                entry
                for entry in timeline.block_entries
                if entry.start_sample <= preview_start and preview_end <= entry.end_sample
            ),
            None,
        )
        if block_entry is None:
            raise EditSessionNotFoundError(f"Edge '{edge_id}' preview target not found.")
        block_asset = self._asset_store.load_block_asset(block_entry.block_asset_id)
        local_start = preview_start - block_entry.start_sample
        local_end = preview_end - block_entry.start_sample
        return block_asset.sample_rate, block_asset.audio[local_start:local_end].astype(np.float32, copy=False)

    def get_preview_response(self, request: PreviewRequest) -> PreviewResponse:
        payload = self.build_preview(request)
        wav_bytes = build_wav_bytes(
            payload.sample_rate,
            float_audio_chunk_to_pcm16_bytes(payload.audio.astype(np.float32, copy=False)),
        )
        preview_record = self._asset_store.create_preview_asset(
            job_id=payload.preview_asset_id,
            preview_asset_id=payload.preview_asset_id,
            preview_kind=payload.preview_kind,
            payload=wav_bytes,
            ttl_seconds=self._preview_ttl_seconds,
        )
        return PreviewResponse(
            preview_asset_id=payload.preview_asset_id,
            preview_kind=payload.preview_kind,
            audio_delivery=self._audio_delivery_service.build_descriptor(
                asset_id=payload.preview_asset_id,
                audio_url=f"/v1/edit-session/assets/previews/{payload.preview_asset_id}/audio",
                asset_path=preview_record.asset_path,
                sample_rate=payload.sample_rate,
                expires_at=preview_record.expires_at,
            ),
        )

    def get_standardization_preview_response(
        self,
        request: StandardizationPreviewRequest,
    ) -> StandardizationPreviewResponse:
        preview = build_standardization_preview(
            raw_text=request.raw_text,
            text_language=request.text_language,
            segment_limit=request.segment_limit,
            cursor=request.cursor,
            include_language_analysis=request.include_language_analysis,
        )
        return StandardizationPreviewResponse(
            analysis_stage=preview.analysis_stage,
            document_char_count=preview.document_char_count,
            total_segments=preview.total_segments,
            next_cursor=preview.next_cursor,
            resolved_document_language=preview.resolved_document_language,
            language_detection_source=preview.language_detection_source,
            warnings=preview.warnings,
            segments=[
                StandardizationPreviewSegment(
                    order_key=segment.order_key,
                    stem=segment.stem,
                    display_text=segment.display_text,
                    terminal_raw=segment.terminal_raw,
                    terminal_closer_suffix=segment.terminal_closer_suffix,
                    terminal_source=segment.terminal_source,
                    detected_language=segment.detected_language,
                    inference_exclusion_reason=segment.inference_exclusion_reason,
                    warnings=segment.warnings,
                )
                for segment in preview.segments
            ],
        )

    def get_segment_asset_response(self, render_asset_id: str) -> SegmentAssetResponse:
        asset = self._load_segment_asset_or_404(render_asset_id)
        sample_rate = self._load_sample_rate(self._asset_store.segment_asset_path(render_asset_id), asset_id=render_asset_id)
        return SegmentAssetResponse(
            render_asset_id=asset.render_asset_id,
            segment_id=asset.segment_id,
            render_version=asset.render_version,
            audio_delivery=self._audio_delivery_service.build_descriptor(
                asset_id=asset.render_asset_id,
                audio_url=f"/v1/edit-session/assets/segments/{asset.render_asset_id}/audio",
                asset_path=self._asset_store.segment_asset_path(render_asset_id),
                sample_rate=sample_rate,
            ),
        )

    def get_boundary_asset_response(self, boundary_asset_id: str) -> BoundaryAssetResponse:
        asset = self._load_boundary_asset_or_404(boundary_asset_id)
        sample_rate = self._load_sample_rate(
            self._asset_store.boundary_asset_path(boundary_asset_id),
            asset_id=boundary_asset_id,
        )
        return BoundaryAssetResponse(
            boundary_asset_id=asset.boundary_asset_id,
            left_segment_id=asset.left_segment_id,
            right_segment_id=asset.right_segment_id,
            edge_version=asset.edge_version,
            audio_delivery=self._audio_delivery_service.build_descriptor(
                asset_id=asset.boundary_asset_id,
                audio_url=f"/v1/edit-session/assets/boundaries/{asset.boundary_asset_id}/audio",
                asset_path=self._asset_store.boundary_asset_path(boundary_asset_id),
                sample_rate=sample_rate,
            ),
        )

    def _run_transaction(self, plan: RenderPlan) -> None:
        if getattr(plan, "job_kind", "initialize") == "initialize":
            self._run_initialize_block_first(plan)
            return
        self._run_edit_block_first(plan)

    def _run_initialize_block_first(self, plan: RenderPlan) -> None:
        if (
            self._block_render_request_builder is None
            or self._block_render_asset_persister is None
            or self._block_adapter_selector is None
        ):
            raise RuntimeError("Block-first initialize pipeline dependencies are not configured.")
        self._prepare(plan)
        self._render_block_first(plan)
        self._commit(plan)

    def _run_edit_block_first(self, plan: RenderPlan) -> None:
        if (
            self._block_render_request_builder is None
            or self._block_render_asset_persister is None
            or self._block_adapter_selector is None
        ):
            raise RuntimeError("Block-first edit pipeline dependencies are not configured.")
        self._prepare_edit(plan)
        self._render_block_first(plan)
        self._commit_edit(plan)

    def _render_block_first(self, plan: RenderPlan) -> None:
        self._runtime.update_job(
            plan.job_id,
            status="rendering",
            progress=PREPARE_END_PROGRESS,
            message="正在按 block 渲染资产。",
        )
        temporary_snapshot = self._build_temporary_snapshot(plan)
        resolved_segments = {
            segment.segment_id: self._render_config_resolver.resolve_segment(
                snapshot=temporary_snapshot,
                segment_id=segment.segment_id,
            )
            for segment in plan.segments
        }
        resolved_edges = {
            edge.edge_id: self._render_config_resolver.resolve_edge(
                snapshot=temporary_snapshot,
                edge_id=edge.edge_id,
            )
            for edge in plan.edges
        }
        previous_timeline = self._load_previous_timeline(plan)
        planned_blocks = self._block_planner.build_blocks(plan.segments)
        force_single_request_block_ids = self._collect_force_single_request_block_ids(
            plan=plan,
            blocks=planned_blocks,
            resolved_segments=resolved_segments,
        )
        execution_plan = self._block_render_request_builder.build_execution_plan(
            snapshot=temporary_snapshot,
            blocks=planned_blocks,
            resolved_segments=resolved_segments,
            resolved_edges=resolved_edges,
            target_segment_ids=plan.target_segment_ids,
            target_edge_ids=plan.target_edge_ids,
            previous_timeline=previous_timeline,
            reuse_policy="force_full_render" if plan.job_kind == "initialize" else "prefer_reuse",
            render_scope="block" if plan.job_kind == "initialize" else "segment",
            force_single_request_block_ids=force_single_request_block_ids,
        )
        plan.blocks = [formal_block_plan.formal_block for formal_block_plan in execution_plan.formal_blocks]
        plan.block_assets = []
        plan.changed_block_asset_ids.clear()
        self._seed_existing_segment_assets_for_block_render(plan)
        self._runtime.update_job(plan.job_id, total_block_count=len(plan.blocks))

        for index, formal_block_plan in enumerate(execution_plan.formal_blocks, start=1):
            block = formal_block_plan.formal_block
            control_action = self._get_control_action(plan.job_id)
            if control_action is not None and plan.changed_block_asset_ids:
                self._commit_partial_after_segment(plan, status=control_action)
            if self._should_compose_block_without_inference(plan=plan, block=block):
                block_asset = self._compose_block_without_inference(
                    plan=plan,
                    block=block,
                    snapshot=temporary_snapshot,
                    previous_timeline=previous_timeline,
                )
                plan.changed_block_asset_ids.add(block_asset.block_asset_id)
                plan.block_assets.append(block_asset)
                self._sync_segments_from_block_asset(plan=plan, block_asset=block_asset)
            elif self._can_reuse_existing_block(plan=plan, block=block, previous_timeline=previous_timeline):
                previous_entry = next(
                    entry for entry in previous_timeline.block_entries if entry.segment_ids == list(block.segment_ids)
                )
                block_asset = self._asset_store.load_block_asset(previous_entry.block_asset_id)
                plan.block_assets.append(block_asset)
                self._sync_segments_from_block_asset(plan=plan, block_asset=block_asset)
            else:
                escalated_to_block_scope = False
                executed_block_assets: list[BlockCompositionAssetPayload] = []
                for execution_unit in formal_block_plan.execution_units:
                    request = execution_unit.request
                    request_state = {"completed_target_segment_ids": set()}
                    adapter = self._select_block_adapter(
                        request.model_binding.adapter_id,
                        cancellation_checker=lambda: self._should_interrupt_block_render(
                            plan=plan,
                            request_state=request_state,
                        ),
                        segment_asset_callback=self._build_block_segment_asset_callback(
                            plan=plan,
                            request_state=request_state,
                        ),
                    )
                    try:
                        result = adapter.render_block(request)
                    except SegmentScopeUnsupported as exc:
                        if request.render_scope != "segment":
                            raise
                        render_job_logger.warning(
                            "segment-scope render unsupported; escalating to block scope job_id={} block_id={} reason_code={} details={}",
                            plan.job_id,
                            block.block_id,
                            exc.reason_code,
                            exc.details,
                        )
                        escalated_execution_plan = self._block_render_request_builder.build_execution_plan(
                            snapshot=temporary_snapshot,
                            blocks=[block],
                            resolved_segments=resolved_segments,
                            resolved_edges=resolved_edges,
                            target_segment_ids=plan.target_segment_ids,
                            target_edge_ids=plan.target_edge_ids,
                            previous_timeline=previous_timeline,
                            reuse_policy="force_full_render" if plan.job_kind == "initialize" else "prefer_reuse",
                            render_scope="block",
                        )
                        for escalated_unit in escalated_execution_plan.formal_blocks[0].execution_units:
                            escalated_request = escalated_unit.request
                            escalated_request.escalated_from_scope = "segment"
                            escalated_adapter = self._select_block_adapter(
                                escalated_request.model_binding.adapter_id,
                                cancellation_checker=lambda: self._should_interrupt_block_render(
                                    plan=plan,
                                    request_state=request_state,
                                ),
                                segment_asset_callback=self._build_block_segment_asset_callback(
                                    plan=plan,
                                    request_state=request_state,
                                ),
                            )
                            escalated_result = escalated_adapter.render_block(escalated_request)
                            persisted = self._block_render_asset_persister.persist(
                                job_id=plan.job_id,
                                request=escalated_request,
                                result=escalated_result,
                                block_render_cache_key=escalated_request.request_id,
                                base_render_asset_ids=request_state.get("base_render_asset_ids"),
                                base_render_assets=request_state.get("base_render_assets"),
                            )
                            if persisted is None:
                                continue
                            block_asset = self._asset_store.load_block_asset(persisted.block_asset.block_asset_id)
                            executed_block_assets.append(block_asset)
                            self._sync_segments_from_block_asset(plan=plan, block_asset=block_asset)
                            self._emit_exact_segment_events(plan=plan, block_asset=block_asset)
                            control_action = self._get_control_action(plan.job_id)
                            if control_action is not None and self._should_commit_partial_after_block_request(
                                plan=plan,
                                request_state=request_state,
                            ):
                                self._commit_partial_after_segment(plan, status=control_action)
                        escalated_to_block_scope = True
                        break
                    except RuntimeError as exc:
                        control_action = self._get_control_action(plan.job_id)
                        if (
                            str(exc) == "Block rendering cancelled."
                            and control_action is not None
                            and self._should_commit_partial_after_block_request(
                                plan=plan,
                                request_state=request_state,
                            )
                        ):
                            self._commit_partial_after_segment(plan, status=control_action)
                        raise
                    persisted = self._block_render_asset_persister.persist(
                        job_id=plan.job_id,
                        request=request,
                        result=result,
                        block_render_cache_key=request.request_id,
                        base_render_asset_ids=request_state.get("base_render_asset_ids"),
                        base_render_assets=request_state.get("base_render_assets"),
                    )
                    if persisted is None:
                        continue
                    block_asset = self._asset_store.load_block_asset(persisted.block_asset.block_asset_id)
                    executed_block_assets.append(block_asset)
                    self._sync_segments_from_block_asset(plan=plan, block_asset=block_asset)
                    self._emit_exact_segment_events(plan=plan, block_asset=block_asset)
                    control_action = self._get_control_action(plan.job_id)
                    if control_action is not None and self._should_commit_partial_after_block_request(
                        plan=plan,
                        request_state=request_state,
                    ):
                        self._commit_partial_after_segment(plan, status=control_action)
                if len(executed_block_assets) == 1 and executed_block_assets[0].segment_ids == list(block.segment_ids):
                    final_block_asset = executed_block_assets[0]
                else:
                    final_block_asset = self._compose_block_without_inference(
                        plan=plan,
                        block=block,
                        snapshot=temporary_snapshot,
                        previous_timeline=previous_timeline,
                    )
                plan.changed_block_asset_ids.add(final_block_asset.block_asset_id)
                plan.block_assets.append(final_block_asset)
                self._runtime.emit_event(
                    plan.job_id,
                    "block_completed",
                    {
                        "block_asset_id": final_block_asset.block_asset_id,
                        "segment_ids": list(final_block_asset.segment_ids),
                        "audio_sample_count": final_block_asset.audio_sample_count,
                    },
                )
                if escalated_to_block_scope:
                    self._runtime.update_job(
                        plan.job_id,
                        message=f"已升级为 block 级重渲染并完成第 {index}/{len(planned_blocks)} 个 block。",
                    )
            self._runtime.update_job(
                plan.job_id,
                current_block_index=index,
                total_block_count=len(plan.blocks),
                progress=PREPARE_END_PROGRESS + (0.75 - PREPARE_END_PROGRESS) * (index / max(1, len(plan.blocks))),
                message=f"已完成第 {index}/{len(plan.blocks)} 个 block 渲染。",
            )

        final_snapshot = self._build_temporary_snapshot(plan)
        plan.timeline_manifest, playback_map = self._timeline_manifest_service.build(
            snapshot=final_snapshot,
            blocks=plan.block_assets,
            sample_rate=plan.block_assets[0].sample_rate if plan.block_assets else self._composition_builder._sample_rate,
            previous_timeline=previous_timeline,
            reflow_from_order_key=plan.earliest_changed_order_key if plan.timeline_reflow_required else None,
        )
        span_by_segment_id = {entry.segment_id: entry.audio_sample_span for entry in playback_map.entries}
        for segment in plan.segments:
            span = span_by_segment_id.get(segment.segment_id)
            segment.assembled_audio_span = span
            segment.effective_duration_samples = None if span is None else max(0, span[1] - span[0])
        self._persist_runtime_job(plan.job_id)

    @staticmethod
    def _should_compose_block_without_inference(plan: RenderPlan, block: RenderBlock) -> bool:
        return (
            plan.compose_only
            and not plan.target_segment_ids
            and not plan.target_edge_ids
            and block.block_id in plan.target_block_ids
        )

    def _can_reuse_existing_block(
        self,
        *,
        plan: RenderPlan,
        block: RenderBlock,
        previous_timeline: TimelineManifest | None,
    ) -> bool:
        if previous_timeline is None or plan.job_kind == "initialize":
            return False
        if block.block_id in plan.target_block_ids:
            return False
        if plan.target_segment_ids.intersection(block.segment_ids):
            return False
        block_edge_ids = {
            edge.edge_id
            for edge in plan.edges
            if edge.left_segment_id in block.segment_ids and edge.right_segment_id in block.segment_ids
        }
        if block_edge_ids.intersection(plan.target_edge_ids):
            return False
        return any(entry.segment_ids == list(block.segment_ids) for entry in previous_timeline.block_entries)

    def _compose_block_without_inference(
        self,
        *,
        plan: RenderPlan,
        block: RenderBlock,
        snapshot: DocumentSnapshot,
        previous_timeline: TimelineManifest | None,
    ) -> BlockCompositionAssetPayload:
        assembler = FormalBlockAssembler(
            composition_builder=self._composition_builder,
            render_config_resolver=self._render_config_resolver,
            resolve_boundary_strategy_for_assets=self._resolve_boundary_strategy_for_assets,
            load_previous_block_asset_for_recompose=self._load_previous_block_asset_for_recompose,
            build_boundary_asset_from_previous_block_asset=self._build_boundary_asset_from_previous_block_asset,
            load_or_rebuild_boundary_asset=lambda **kwargs: self._load_or_rebuild_boundary_asset(plan=plan, **kwargs),
            write_block_asset=self._write_block_asset,
        )
        return assembler.assemble(
            job_id=plan.job_id,
            segments=plan.segments,
            edges=plan.edges,
            segment_assets=plan.segment_assets,
            boundary_assets=plan.boundary_assets,
            block=block,
            snapshot=snapshot,
            previous_timeline=previous_timeline,
        )

    def _collect_force_single_request_block_ids(
        self,
        *,
        plan: RenderPlan,
        blocks: list[RenderBlock],
        resolved_segments: dict[str, object],
    ) -> set[str]:
        if plan.job_kind != "initialize":
            return set()

        forced_block_ids: set[str] = set()
        for block in blocks:
            adapter_ids = {
                resolved_segments[segment_id].resolved_model_binding.adapter_id
                for segment_id in block.segment_ids
                if resolved_segments[segment_id].resolved_model_binding is not None
            }
            if len(adapter_ids) != 1:
                continue
            adapter_id = next(iter(adapter_ids))
            adapter_definition = self._adapter_registry.require(adapter_id)
            if (
                not adapter_definition.capabilities.exact_segment_output
                or not self._adapter_supports_readonly_formal_block_recompose(adapter_id)
            ):
                forced_block_ids.add(block.block_id)
        return forced_block_ids

    @staticmethod
    def _adapter_supports_readonly_formal_block_recompose(adapter_id: str | None) -> bool:
        return adapter_id in {None, "gpt_sovits_local"}

    def _load_previous_block_asset_for_recompose(
        self,
        *,
        previous_timeline: TimelineManifest | None,
        block: RenderBlock,
    ) -> BlockCompositionAssetPayload | None:
        if previous_timeline is None:
            return None
        previous_entry = self._find_previous_block_entry_for_recompose(
            previous_timeline=previous_timeline,
            segment_ids=list(block.segment_ids),
        )
        if previous_entry is None:
            return None
        try:
            return self._asset_store.load_block_asset(previous_entry.block_asset_id)
        except (FileNotFoundError, ValueError):
            return None

    @staticmethod
    def _find_previous_block_entry_for_recompose(
        *,
        previous_timeline: TimelineManifest,
        segment_ids: list[str],
    ) -> TimelineBlockEntry | None:
        exact_match = next(
            (
                entry
                for entry in previous_timeline.block_entries
                if entry.segment_ids == segment_ids
            ),
            None,
        )
        if exact_match is not None:
            return exact_match
        return next(
            (
                entry
                for entry in previous_timeline.block_entries
                if RenderJobService._is_contiguous_subsequence(segment_ids, entry.segment_ids)
            ),
            None,
        )

    @staticmethod
    def _is_contiguous_subsequence(segment_ids: list[str], candidate_ids: list[str]) -> bool:
        if not segment_ids or len(segment_ids) > len(candidate_ids):
            return False
        window_size = len(segment_ids)
        for index in range(0, len(candidate_ids) - window_size + 1):
            if candidate_ids[index : index + window_size] == segment_ids:
                return True
        return False

    @staticmethod
    def _build_boundary_asset_from_previous_block_asset(
        *,
        previous_block_asset: BlockCompositionAssetPayload | None,
        edge: EditableEdge,
        left_asset: SegmentRenderAssetPayload,
        right_asset: SegmentRenderAssetPayload,
        effective_boundary_strategy: str,
    ) -> BoundaryAssetPayload | None:
        if previous_block_asset is None:
            return None
        previous_edge_entry = next(
            (
                entry
                for entry in previous_block_asset.edge_entries
                if entry.edge_id == edge.edge_id
            ),
            None,
        )
        if previous_edge_entry is None:
            return None
        previous_boundary_start, previous_boundary_end = previous_edge_entry.boundary_sample_span
        if (
            previous_edge_entry.effective_boundary_strategy != effective_boundary_strategy
            and previous_boundary_end > previous_boundary_start
        ):
            return None
        boundary_start, boundary_end = previous_boundary_start, previous_boundary_end
        boundary_audio = previous_block_asset.audio[boundary_start:boundary_end].astype(np.float32, copy=False)
        return BoundaryAssetPayload(
            boundary_asset_id=build_boundary_asset_id(
                left_segment_id=edge.left_segment_id,
                left_render_version=left_asset.render_version,
                right_segment_id=edge.right_segment_id,
                right_render_version=right_asset.render_version,
                edge_version=edge.edge_version,
                boundary_strategy=effective_boundary_strategy,
            ),
            left_segment_id=edge.left_segment_id,
            left_render_version=left_asset.render_version,
            right_segment_id=edge.right_segment_id,
            right_render_version=right_asset.render_version,
            edge_version=edge.edge_version,
            sample_rate=previous_block_asset.sample_rate,
            boundary_strategy=effective_boundary_strategy,
            boundary_sample_count=int(boundary_audio.size),
            boundary_audio=boundary_audio,
            trace={
                "derived_from_block_asset": previous_block_asset.block_asset_id,
                "edge_id": edge.edge_id,
            },
        )

    def _sync_segments_from_block_asset(self, *, plan: RenderPlan, block_asset: BlockCompositionAssetPayload) -> None:
        segment_by_id = {segment.segment_id: segment for segment in plan.segments}
        for entry in block_asset.segment_entries:
            segment = segment_by_id.get(entry.segment_id)
            if segment is None:
                continue
            segment.render_asset_id = entry.render_asset_id
            segment.base_render_asset_id = entry.base_render_asset_id or segment.base_render_asset_id or entry.render_asset_id
            segment.render_status = "ready"
            segment.assembled_audio_span = entry.audio_sample_span
            segment.effective_duration_samples = max(0, entry.audio_sample_span[1] - entry.audio_sample_span[0])
            resolved_asset = self._load_segment_asset_for_boundary_reuse(
                base_render_asset_id=segment.base_render_asset_id,
                fallback_render_asset_id=entry.render_asset_id,
                existing_asset=plan.segment_assets.get(entry.segment_id),
            )
            if resolved_asset is not None:
                plan.segment_assets[entry.segment_id] = resolved_asset

    def _emit_exact_segment_events(self, *, plan: RenderPlan, block_asset: BlockCompositionAssetPayload) -> None:
        for entry in block_asset.segment_entries:
            if entry.render_asset_id is None:
                continue
            if entry.segment_id in plan.emitted_segment_ids:
                continue
            self._runtime.emit_event(
                plan.job_id,
                "segment_completed",
                {
                    "segment_id": entry.segment_id,
                    "order_key": entry.order_key,
                    "render_asset_id": entry.render_asset_id,
                    "render_status": "ready",
                    "effective_duration_samples": max(0, entry.audio_sample_span[1] - entry.audio_sample_span[0]),
                },
            )
            plan.emitted_segment_ids.add(entry.segment_id)

    def _seed_existing_segment_assets_for_block_render(self, plan: RenderPlan) -> None:
        for segment in plan.segments:
            if segment.segment_id in plan.segment_assets:
                continue
            asset = self._load_segment_asset_for_boundary_reuse(
                base_render_asset_id=segment.base_render_asset_id,
                fallback_render_asset_id=segment.render_asset_id,
                existing_asset=None,
            )
            if asset is not None:
                plan.segment_assets[segment.segment_id] = asset

    def _build_block_segment_asset_callback(
        self,
        *,
        plan: RenderPlan,
        request_state: dict[str, object],
    ) -> Callable[[SegmentRenderAssetPayload, object, bool], None]:
        segment_by_id = {segment.segment_id: segment for segment in plan.segments}
        total_targets = len(plan.segments) if plan.job_kind == "initialize" else max(1, len(plan.target_segment_ids))

        def _callback(asset: SegmentRenderAssetPayload, request_segment: object, reused: bool) -> None:
            segment_id = getattr(request_segment, "segment_id", None)
            if not isinstance(segment_id, str):
                return
            segment = segment_by_id.get(segment_id)
            if segment is None:
                return

            should_track = plan.job_kind == "initialize" or segment_id in plan.target_segment_ids
            if should_track:
                completed_target_segment_ids = request_state.setdefault("completed_target_segment_ids", set())
                if isinstance(completed_target_segment_ids, set):
                    completed_target_segment_ids.add(segment_id)
            base_render_asset_ids = request_state.setdefault("base_render_asset_ids", {})
            if isinstance(base_render_asset_ids, dict):
                base_render_asset_ids[segment_id] = asset.render_asset_id
            base_render_assets = request_state.setdefault("base_render_assets", {})
            if isinstance(base_render_assets, dict):
                base_render_assets[segment_id] = asset
            plan.segment_assets[segment_id] = asset
            segment.base_render_asset_id = asset.render_asset_id
            segment.render_asset_id = asset.render_asset_id
            segment.render_status = "ready"
            segment.assembled_audio_span = (0, asset.audio_sample_count)
            segment.effective_duration_samples = asset.audio_sample_count
            control_action = self._get_control_action(plan.job_id)
            if control_action is None:
                return
            if not should_track or segment_id in plan.emitted_segment_ids:
                return

            completed_count = sum(
                1
                for current_segment in plan.segments
                if current_segment.render_status == "ready"
                and (plan.job_kind == "initialize" or current_segment.segment_id in plan.target_segment_ids)
            )
            self._runtime.update_job(
                plan.job_id,
                current_segment_index=completed_count,
                total_segment_count=total_targets,
                progress=build_render_segment_progress(
                    completed_segments=completed_count,
                    total_segments=total_targets,
                    start_progress=PREPARE_END_PROGRESS,
                    end_progress=0.6,
                ),
                message=f"已完成第 {completed_count}/{total_targets} 段渲染。",
            )
            self._runtime.emit_event(
                plan.job_id,
                "segment_completed",
                {
                    "segment_id": segment.segment_id,
                    "order_key": segment.order_key,
                    "render_asset_id": asset.render_asset_id,
                    "render_status": segment.render_status,
                    "effective_duration_samples": segment.effective_duration_samples,
                },
            )
            plan.emitted_segment_ids.add(segment_id)

        return _callback

    @staticmethod
    def _request_state_has_completed_target_segments(request_state: dict[str, object]) -> bool:
        completed_target_segment_ids = request_state.get("completed_target_segment_ids")
        return isinstance(completed_target_segment_ids, set) and bool(completed_target_segment_ids)

    def _should_commit_partial_after_block_request(
        self,
        *,
        plan: RenderPlan,
        request_state: dict[str, object],
    ) -> bool:
        if not plan.target_segment_ids:
            return True
        return self._request_state_has_completed_target_segments(request_state)

    def _should_interrupt_block_render(self, *, plan: RenderPlan, request_state: dict[str, object]) -> bool:
        control_action = self._get_control_action(plan.job_id)
        if control_action is None:
            return False
        return self._request_state_has_completed_target_segments(request_state)

    def _select_block_adapter(self, adapter_id: str, **kwargs):
        if self._block_adapter_selector is None:
            raise RuntimeError("Block adapter selector is not configured.")
        return self._block_adapter_selector(
            adapter_id,
            gateway=self._gateway,
            asset_store=self._asset_store,
            composition_builder=self._composition_builder,
            secret_store=self._secret_store,
            cancellation_checker=kwargs.get("cancellation_checker"),
            segment_asset_callback=kwargs.get("segment_asset_callback"),
        )

    def _prepare(self, plan: RenderPlan) -> None:
        self._ensure_not_cancelled(plan.job_id)
        self._runtime.update_job(
            plan.job_id,
            status="preparing",
            progress=PREPARE_START_PROGRESS,
            message="正在准备参考上下文。",
        )
        projected_binding = self._resolve_projected_binding_for_initialize_request(plan.request)
        resolved_context = self._build_resolved_context_from_request(
            plan.request,
            projected_voice=projected_binding,
        )
        render_job_logger.info(
            "initialize context resolved voice_id={} model_key={} reference_audio_path={} reference_language={} speed={} top_k={} top_p={} temperature={} noise_scale={}",
            resolved_context.voice_id,
            resolved_context.model_key,
            resolved_context.reference_audio_path,
            resolved_context.reference_language,
            resolved_context.speed,
            resolved_context.top_k,
            resolved_context.top_p,
            resolved_context.temperature,
            resolved_context.noise_scale,
        )
        if self._can_build_local_reference_context(projected_binding):
            context_started = time.perf_counter()
            plan.context = self._gateway.build_reference_context(
                resolved_context,
                progress_callback=self._build_prepare_progress_callback(
                    job_id=plan.job_id,
                    default_message="正在准备参考上下文。",
                ),
            )
            render_job_logger.info(
                "initialize reference context built voice_id={} reference_context_id={} elapsed_ms={:.2f}",
                resolved_context.voice_id,
                plan.context.reference_context_id,
                (time.perf_counter() - context_started) * 1000,
            )
        default_render_profile, default_voice_binding = self._build_default_configuration(
            plan.request,
            projected_voice=projected_binding,
        )
        plan.render_profiles = [default_render_profile]
        plan.voice_bindings = [default_voice_binding]
        plan.default_render_profile_id = default_render_profile.render_profile_id
        plan.default_voice_binding_id = default_voice_binding.voice_binding_id
        split_started = time.perf_counter()
        render_job_logger.info(
            "initialize segment split start job_id={} segment_boundary_mode={} raw_text_length={}",
            plan.job_id,
            plan.request.segment_boundary_mode,
            len(plan.request.raw_text),
        )
        segments = self._split_raw_segments(
            plan.request.raw_text,
            segment_boundary_mode=plan.request.segment_boundary_mode,
        )
        render_job_logger.info(
            "initialize segment split completed job_id={} segment_count={} elapsed_ms={:.2f}",
            plan.job_id,
            len(segments),
            (time.perf_counter() - split_started) * 1000,
        )
        if not segments:
            raise ValueError("请输入有效文本")
        build_segments_started = time.perf_counter()
        render_job_logger.info(
            "initialize build segments start job_id={} segment_count={} text_language={}",
            plan.job_id,
            len(segments),
            plan.request.text_language,
        )
        plan.segments = self._build_segments(plan.document_id, segments, plan.request.text_language)
        detected_language_summary: dict[str, int] = {}
        exclusion_reason_summary: dict[str, int] = {}
        for segment in plan.segments:
            detected_language_summary[segment.detected_language] = (
                detected_language_summary.get(segment.detected_language, 0) + 1
            )
            exclusion_reason_summary[segment.inference_exclusion_reason] = (
                exclusion_reason_summary.get(segment.inference_exclusion_reason, 0) + 1
            )
        render_job_logger.info(
            "initialize build segments completed job_id={} segment_count={} elapsed_ms={:.2f} detected_language_summary={} exclusion_reason_summary={}",
            plan.job_id,
            len(plan.segments),
            (time.perf_counter() - build_segments_started) * 1000,
            detected_language_summary,
            exclusion_reason_summary,
        )
        build_edges_started = time.perf_counter()
        plan.edges = self._build_edges(plan.document_id, plan.segments, plan.request.pause_duration_seconds)
        render_job_logger.info(
            "initialize build edges completed job_id={} edge_count={} elapsed_ms={:.2f}",
            plan.job_id,
            len(plan.edges),
            (time.perf_counter() - build_edges_started) * 1000,
        )
        render_job_logger.info(
            "initialize runtime sync start job_id={} total_segments={}",
            plan.job_id,
            len(plan.segments),
        )
        self._runtime.update_job(
            plan.job_id,
            total_segment_count=len(plan.segments),
            message=f"文本切分完成，共 {len(plan.segments)} 段。",
        )
        self._runtime.emit_event(
            plan.job_id,
            "segments_initialized",
            {
                "document_id": plan.document_id,
                "document_version": plan.document_version,
                "segments": [
                    {
                        "segment_id": segment.segment_id,
                        "order_key": segment.order_key,
                        "stem": segment.stem,
                        "display_text": segment.display_text,
                        "text_language": segment.text_language,
                        "terminal_raw": segment.terminal_raw,
                        "terminal_closer_suffix": segment.terminal_closer_suffix,
                        "terminal_source": segment.terminal_source,
                        "detected_language": segment.detected_language,
                        "inference_exclusion_reason": segment.inference_exclusion_reason,
                        "render_status": segment.render_status,
                    }
                    for segment in plan.segments
                ],
            },
        )
        render_job_logger.info("initialize runtime sync completed job_id={}", plan.job_id)
        persist_started = time.perf_counter()
        self._persist_runtime_job(plan.job_id)
        render_job_logger.info(
            "initialize prepare persisted job_id={} elapsed_ms={:.2f}",
            plan.job_id,
            (time.perf_counter() - persist_started) * 1000,
        )

    def _prepare_edit(self, plan: RenderPlan) -> None:
        self._ensure_not_cancelled(plan.job_id)
        self._runtime.update_job(
            plan.job_id,
            status="preparing",
            progress=PREPARE_START_PROGRESS,
            message="正在准备编辑作业。",
        )
        projected_binding = self._resolve_projected_binding_for_initialize_request(plan.request)
        if self._should_prepare_edit_reference_context(plan) and self._can_build_local_reference_context(projected_binding):
            plan.context = self._gateway.build_reference_context(
                self._build_resolved_context_from_request(
                    plan.request,
                    projected_voice=projected_binding,
                ),
                progress_callback=self._build_prepare_progress_callback(
                    job_id=plan.job_id,
                    default_message="正在准备编辑作业。",
                ),
            )
        else:
            self._runtime.update_job(
                plan.job_id,
                progress=build_prepare_progress(completed_stages=1, total_stages=1),
            )
        self._runtime.update_job(
            plan.job_id,
            total_segment_count=len(plan.target_segment_ids) or len(plan.segments),
            message=f"编辑快照准备完成，版本将更新为 {plan.document_version}。",
        )
        self._persist_runtime_job(plan.job_id)

    def _build_prepare_progress_callback(
        self,
        *,
        job_id: str,
        default_message: str,
    ) -> Callable[[dict], None]:
        def _progress_callback(event: dict) -> None:
            raw_progress = event.get("progress")
            update_payload: dict[str, object] = {
                "status": "preparing",
            }
            if isinstance(raw_progress, (int, float)):
                update_payload["progress"] = build_prepare_progress_from_local(local_progress=float(raw_progress))

            raw_message = event.get("message")
            update_payload["message"] = raw_message if isinstance(raw_message, str) else default_message
            self._runtime.update_job(job_id, **update_payload)

        return _progress_callback

    @staticmethod
    def _should_prepare_edit_reference_context(plan: RenderPlan) -> bool:
        if getattr(plan, "job_kind", None) in {"segment_swap", "segment_reorder"}:
            return False
        if plan.compose_only and not plan.target_segment_ids and not plan.target_edge_ids:
            return False
        return True

    @staticmethod
    def _split_raw_segments(raw_text: str, *, segment_boundary_mode: str) -> list[str]:
        if segment_boundary_mode == "raw_strong_punctuation":
            return split_text_segments_with_terminal_capsules(raw_text)
        if segment_boundary_mode == "zh_period":
            return split_text_segments_zh_period(raw_text)
        raise ValueError(f"Unsupported segment_boundary_mode '{segment_boundary_mode}'.")

    def _cancel_inference_tracking(self, plan: RenderPlan, message: str) -> None:
        if self._inference_runtime is None or plan.inference_task_id is None:
            return
        self._inference_runtime.mark_cancelled(task_id=plan.inference_task_id, message=message)
        plan.inference_task_id = None

    def _load_or_rebuild_boundary_asset(
        self,
        *,
        plan: RenderPlan,
        snapshot: DocumentSnapshot,
        edge: EditableEdge,
        left_asset: SegmentRenderAssetPayload,
        right_asset: SegmentRenderAssetPayload,
        effective_boundary_strategy: str,
    ) -> tuple[BoundaryAssetPayload, str]:
        effective_boundary_strategy = self._resolve_boundary_strategy_for_assets(
            edge=edge,
            left_asset=left_asset,
            right_asset=right_asset,
            effective_boundary_strategy=effective_boundary_strategy,
        )
        boundary_asset_id = build_boundary_asset_id(
            left_segment_id=edge.left_segment_id,
            left_render_version=left_asset.render_version,
            right_segment_id=edge.right_segment_id,
            right_render_version=right_asset.render_version,
            edge_version=edge.edge_version,
            boundary_strategy=effective_boundary_strategy,
        )
        try:
            return self._asset_store.load_boundary_asset(boundary_asset_id), effective_boundary_strategy
        except FileNotFoundError:
            render_job_logger.warning(
                "boundary asset missing; rebuilding boundary_asset_id={} edge_id={} left_render_version={} right_render_version={} edge_version={} strategy={}",
                boundary_asset_id,
                edge.edge_id,
                left_asset.render_version,
                right_asset.render_version,
                edge.edge_version,
                effective_boundary_strategy,
            )

        if effective_boundary_strategy == "crossfade_only":
            crossfade_boundary_asset_id = build_boundary_asset_id(
                left_segment_id=edge.left_segment_id,
                left_render_version=left_asset.render_version,
                right_segment_id=edge.right_segment_id,
                right_render_version=right_asset.render_version,
                edge_version=edge.edge_version,
                boundary_strategy="crossfade_only",
            )
            if crossfade_boundary_asset_id != boundary_asset_id:
                try:
                    return self._asset_store.load_boundary_asset(crossfade_boundary_asset_id), effective_boundary_strategy
                except FileNotFoundError:
                    pass

        boundary_context = self._get_segment_context(
            plan=plan,
            snapshot=snapshot,
            segment=next(item for item in plan.segments if item.segment_id == edge.left_segment_id),
        )
        boundary_asset = self._gateway.render_boundary_asset(
            left_asset,
            right_asset,
            edge.model_copy(
                update={
                    "boundary_strategy": effective_boundary_strategy,
                    "effective_boundary_strategy": effective_boundary_strategy,
                }
            ),
            boundary_context,
        )
        self._write_boundary_asset(plan.job_id, boundary_asset)
        return boundary_asset, effective_boundary_strategy

    @staticmethod
    def _boundary_strategy_requires_enhanced_assets(boundary_strategy: str) -> bool:
        return boundary_strategy in {"enhanced", "latent_overlap_then_equal_power_crossfade"}

    @classmethod
    def _collect_boundary_asset_gaps(
        cls,
        *,
        asset: SegmentRenderAssetPayload,
        side: str,
        require_right_margin_frames: bool,
    ) -> list[str]:
        reasons: list[str] = []
        if asset.decoder_frame_count <= 0:
            reasons.append(f"{side}_decoder_frames_missing")
        if not asset.semantic_tokens:
            reasons.append(f"{side}_semantic_tokens_missing")
        if not asset.phone_ids:
            reasons.append(f"{side}_phone_ids_missing")
        if require_right_margin_frames and (
            asset.trace is None or not isinstance(asset.trace, dict) or "right_margin_frames" not in asset.trace
        ):
            reasons.append(f"{side}_right_margin_frames_missing")
        return reasons

    def _resolve_boundary_strategy_for_assets(
        self,
        *,
        edge: EditableEdge,
        left_asset: SegmentRenderAssetPayload,
        right_asset: SegmentRenderAssetPayload,
        effective_boundary_strategy: str,
    ) -> str:
        if not self._boundary_strategy_requires_enhanced_assets(effective_boundary_strategy):
            return effective_boundary_strategy
        downgrade_reasons = [
            *self._collect_boundary_asset_gaps(
                asset=left_asset,
                side="left",
                require_right_margin_frames=True,
            ),
            *self._collect_boundary_asset_gaps(
                asset=right_asset,
                side="right",
                require_right_margin_frames=False,
            ),
        ]
        if not downgrade_reasons:
            return effective_boundary_strategy
        render_job_logger.warning(
            "boundary strategy downgraded due to asset capability mismatch edge_id={} left_asset_id={} right_asset_id={} requested_strategy={} applied_strategy={} reasons={}",
            edge.edge_id,
            left_asset.render_asset_id,
            right_asset.render_asset_id,
            effective_boundary_strategy,
            "crossfade_only",
            downgrade_reasons,
        )
        return "crossfade_only"

    def _load_segment_asset_for_boundary_reuse(
        self,
        *,
        base_render_asset_id: str | None,
        fallback_render_asset_id: str | None,
        existing_asset: SegmentRenderAssetPayload | None,
    ) -> SegmentRenderAssetPayload | None:
        preferred_asset_id = base_render_asset_id or fallback_render_asset_id
        if preferred_asset_id is None:
            return None
        if existing_asset is not None and existing_asset.render_asset_id == preferred_asset_id:
            return existing_asset
        try:
            return self._asset_store.load_segment_asset(preferred_asset_id)
        except FileNotFoundError:
            if fallback_render_asset_id is None or fallback_render_asset_id == preferred_asset_id:
                return None
            return self._asset_store.load_segment_asset(fallback_render_asset_id)

    def _commit(self, plan: RenderPlan) -> None:
        assert plan.timeline_manifest is not None
        self._ensure_not_cancelled(plan.job_id)
        self._runtime.update_job(plan.job_id, status="committing", progress=0.9, message="正在提交快照与资产。")
        staging_root = self._asset_store._staging_root / plan.job_id  # noqa: SLF001
        if staging_root.exists():
            self._asset_store.promote_staging_tree(plan.job_id, "formal")
        self._write_timeline_manifest(plan.timeline_manifest)

        snapshot_payload = {
            "document_id": plan.document_id,
            "document_version": plan.document_version,
            "segment_ids": [segment.segment_id for segment in plan.segments],
            "edge_ids": [edge.edge_id for edge in plan.edges],
            "block_ids": [entry.block_asset_id for entry in plan.timeline_manifest.block_entries],
            "groups": [group.model_copy(deep=True) for group in plan.groups],
            "render_profiles": [profile.model_copy(deep=True) for profile in plan.render_profiles],
            "voice_bindings": [binding.model_copy(deep=True) for binding in plan.voice_bindings],
            "default_render_profile_id": plan.default_render_profile_id,
            "default_voice_binding_id": plan.default_voice_binding_id,
            "composition_manifest_id": None,
            "playback_map_version": plan.document_version,
            "timeline_manifest_id": plan.timeline_manifest.timeline_manifest_id,
            "segments": plan.segments,
            "edges": plan.edges,
        }
        baseline_snapshot = DocumentSnapshot(
            snapshot_id=f"baseline-{uuid4().hex}",
            snapshot_kind="baseline",
            **snapshot_payload,
        )
        head_snapshot = DocumentSnapshot(
            snapshot_id=f"head-{uuid4().hex}",
            snapshot_kind="head",
            **snapshot_payload,
        )
        self._repository.save_snapshot(baseline_snapshot)
        self._repository.save_snapshot(head_snapshot)
        self._checkpoint_service.clear_document_checkpoint(plan.document_id)
        active_session = ActiveDocumentState(
            document_id=plan.document_id,
            session_status="ready",
            baseline_snapshot_id=baseline_snapshot.snapshot_id,
            head_snapshot_id=head_snapshot.snapshot_id,
            active_job_id=None,
            editable_mode="segment",
            initialize_request=plan.request,
            updated_at=datetime.now(timezone.utc),
        )
        self._repository.upsert_active_session(active_session)
        committed_block_asset_ids = self._update_job_committed_state(
            job_id=plan.job_id,
            document_version=plan.document_version,
            timeline=plan.timeline_manifest,
            changed_block_asset_ids=plan.changed_block_asset_ids,
        )
        self._runtime.emit_event(
            plan.job_id,
            "timeline_committed",
            {
                "document_version": plan.document_version,
                "timeline_version": plan.timeline_manifest.timeline_version,
                "timeline_manifest_id": plan.timeline_manifest.timeline_manifest_id,
                "playable_sample_span": list(plan.timeline_manifest.playable_sample_span),
                "changed_block_asset_ids": committed_block_asset_ids,
            },
        )
        self._runtime.update_job(
            plan.job_id,
            status="completed",
            progress=1.0,
            message="初始化渲染完成。",
            result_document_version=plan.document_version,
            current_segment_index=len(plan.segments),
            total_segment_count=len(plan.segments),
            current_block_index=len(plan.blocks),
            total_block_count=len(plan.blocks),
        )
        self._persist_runtime_job(plan.job_id)

    def _commit_edit(self, plan: RenderPlan) -> None:
        active_session = self._session_service.require_active_session()
        self._ensure_not_cancelled(plan.job_id)
        self._runtime.update_job(plan.job_id, status="committing", progress=0.9, message="正在提交编辑版本。")
        staging_root = self._asset_store._staging_root / plan.job_id  # noqa: SLF001
        if staging_root.exists():
            self._asset_store.promote_staging_tree(plan.job_id, "formal")

        if plan.skip_compose:
            baseline_snapshot = self._repository.get_snapshot(active_session.baseline_snapshot_id) if active_session.baseline_snapshot_id else None
            block_ids = baseline_snapshot.block_ids if baseline_snapshot is not None else []
            playback_map_version = baseline_snapshot.playback_map_version if baseline_snapshot is not None else None
            timeline_manifest_id = baseline_snapshot.timeline_manifest_id if baseline_snapshot is not None else None
        else:
            assert plan.timeline_manifest is not None
            self._write_timeline_manifest(plan.timeline_manifest)
            block_ids = [entry.block_asset_id for entry in plan.timeline_manifest.block_entries]
            playback_map_version = plan.document_version
            timeline_manifest_id = plan.timeline_manifest.timeline_manifest_id

        head_snapshot = DocumentSnapshot(
            snapshot_id=f"head-{uuid4().hex}",
            document_id=plan.document_id,
            snapshot_kind="head",
            document_version=plan.document_version,
            segment_ids=[segment.segment_id for segment in plan.segments],
            edge_ids=[edge.edge_id for edge in plan.edges],
            block_ids=block_ids,
            groups=[group.model_copy(deep=True) for group in plan.groups],
            render_profiles=[profile.model_copy(deep=True) for profile in plan.render_profiles],
            voice_bindings=[binding.model_copy(deep=True) for binding in plan.voice_bindings],
            default_render_profile_id=plan.default_render_profile_id,
            default_voice_binding_id=plan.default_voice_binding_id,
            composition_manifest_id=None,
            playback_map_version=playback_map_version,
            timeline_manifest_id=timeline_manifest_id,
            segments=plan.segments,
            edges=plan.edges,
        )
        self._repository.save_snapshot(head_snapshot)
        self._checkpoint_service.clear_document_checkpoint(plan.document_id)
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
        if plan.timeline_manifest is not None:
            committed_block_asset_ids = self._update_job_committed_state(
                job_id=plan.job_id,
                document_version=plan.document_version,
                timeline=plan.timeline_manifest,
                changed_block_asset_ids=plan.changed_block_asset_ids,
            )
            self._runtime.emit_event(
                plan.job_id,
                "timeline_committed",
                {
                    "document_version": plan.document_version,
                    "timeline_version": plan.timeline_manifest.timeline_version,
                    "timeline_manifest_id": plan.timeline_manifest.timeline_manifest_id,
                    "playable_sample_span": list(plan.timeline_manifest.playable_sample_span),
                    "changed_block_asset_ids": committed_block_asset_ids,
                },
            )
        self._persist_runtime_job(plan.job_id)

    def _build_temporary_snapshot(self, plan: RenderPlan) -> DocumentSnapshot:
        return DocumentSnapshot(
            snapshot_id=f"staging-{plan.job_id}",
            document_id=plan.document_id,
            snapshot_kind="staging",
            document_version=plan.document_version,
            segment_ids=[segment.segment_id for segment in plan.segments],
            edge_ids=[edge.edge_id for edge in plan.edges],
            groups=[group.model_copy(deep=True) for group in plan.groups],
            render_profiles=[profile.model_copy(deep=True) for profile in plan.render_profiles],
            voice_bindings=[binding.model_copy(deep=True) for binding in plan.voice_bindings],
            default_render_profile_id=plan.default_render_profile_id,
            default_voice_binding_id=plan.default_voice_binding_id,
            segments=[segment.model_copy(deep=True) for segment in plan.segments],
            edges=[edge.model_copy(deep=True) for edge in plan.edges],
        )

    def _load_previous_timeline(self, plan: RenderPlan) -> TimelineManifest | None:
        if plan.job_kind == "initialize":
            return None
        current_snapshot = self._session_service.get_head_snapshot()
        if current_snapshot.timeline_manifest_id is None:
            return None
        return self._asset_store.load_timeline_manifest(current_snapshot.timeline_manifest_id)

    @staticmethod
    def _collect_changed_block_asset_ids(
        *,
        timeline: TimelineManifest,
        changed_block_asset_ids: set[str],
    ) -> list[str]:
        ordered_block_asset_ids = [entry.block_asset_id for entry in timeline.block_entries]
        if not changed_block_asset_ids:
            return ordered_block_asset_ids
        return [block_asset_id for block_asset_id in ordered_block_asset_ids if block_asset_id in changed_block_asset_ids]

    def _update_job_committed_state(
        self,
        *,
        job_id: str,
        document_version: int,
        timeline: TimelineManifest,
        changed_block_asset_ids: set[str],
    ) -> list[str]:
        committed_block_asset_ids = self._collect_changed_block_asset_ids(
            timeline=timeline,
            changed_block_asset_ids=changed_block_asset_ids,
        )
        self._runtime.update_job(
            job_id,
            committed_document_version=document_version,
            committed_timeline_manifest_id=timeline.timeline_manifest_id,
            committed_playable_sample_span=timeline.playable_sample_span,
            changed_block_asset_ids=committed_block_asset_ids,
        )
        return committed_block_asset_ids

    def _build_segments(
        self,
        document_id: str,
        raw_segments: list[str],
        text_language: str,
    ) -> list[EditableSegment]:
        segments: list[EditableSegment] = []
        normalized_text_language = text_language.lower()
        if normalized_text_language == "auto":
            batch_started = time.perf_counter()
            render_job_logger.info(
                "initialize build segments auto standardization start segment_count={} text_language={}",
                len(raw_segments),
                text_language,
            )
            standardized_segments = standardize_segment_texts(raw_segments, text_language).segments
            render_job_logger.info(
                "initialize build segments auto standardization completed segment_count={} elapsed_ms={:.2f}",
                len(standardized_segments),
                (time.perf_counter() - batch_started) * 1000,
            )
        else:
            standardized_segments = []
            for index, raw_text in enumerate(raw_segments, start=1):
                item_started = time.perf_counter()
                render_job_logger.info(
                    "initialize build segment item start index={}/{} text_language={} raw_preview={}",
                    index,
                    len(raw_segments),
                    text_language,
                    raw_text[:80].replace("\r", "\\r").replace("\n", "\\n"),
                )
                standardized = standardize_segment_text(raw_text, text_language)
                render_job_logger.info(
                    "initialize build segment item completed index={}/{} elapsed_ms={:.2f} detected_language={} inference_exclusion_reason={} normalized_length={}",
                    index,
                    len(raw_segments),
                    (time.perf_counter() - item_started) * 1000,
                    standardized.detected_language,
                    standardized.inference_exclusion_reason,
                    len(standardized.normalized_text),
                )
                standardized_segments.append(standardized)
        for index, standardized in enumerate(standardized_segments, start=1):
            previous_segment_id = segments[-1].segment_id if segments else None
            segment_id = f"segment-{uuid4().hex}"
            segment = EditableSegment(
                segment_id=segment_id,
                document_id=document_id,
                order_key=index,
                previous_segment_id=previous_segment_id,
                stem=standardized.stem,
                text_language=text_language,
                terminal_raw=standardized.terminal_raw,
                terminal_closer_suffix=standardized.terminal_closer_suffix,
                terminal_source=standardized.terminal_source,
                detected_language=standardized.detected_language,
                inference_exclusion_reason=standardized.inference_exclusion_reason,
                render_version=1,
                risk_flags=standardized.risk_flags,
                render_status="pending",
            )
            if segments:
                segments[-1].next_segment_id = segment_id
            segments.append(segment)
        return segments

    @staticmethod
    def _build_edges(
        document_id: str,
        segments: list[EditableSegment],
        pause_duration_seconds: float,
    ) -> list[EditableEdge]:
        edges: list[EditableEdge] = []
        for left, right in zip(segments, segments[1:]):
            edges.append(
                EditableEdge(
                    edge_id=f"edge-{left.segment_id}-{right.segment_id}",
                    document_id=document_id,
                    left_segment_id=left.segment_id,
                    right_segment_id=right.segment_id,
                    pause_duration_seconds=pause_duration_seconds,
                )
            )
        return edges

    def _write_segment_asset(self, job_id: str, asset: SegmentRenderAssetPayload) -> None:
        del job_id
        audio = np.concatenate([asset.left_margin_audio, asset.core_audio, asset.right_margin_audio]).astype(
            np.float32,
            copy=False,
        )
        wav_bytes = build_wav_bytes(asset.sample_rate, float_audio_chunk_to_pcm16_bytes(audio))
        self._asset_store.write_formal_bytes_atomic(f"segments/{asset.render_asset_id}/audio.wav", wav_bytes)
        render_job_logger.info(
            "segment asset persisted render_asset_id={} segment_id={} render_version={} sample_rate={} audio_sample_count={} core_sample_count={} left_margin_sample_count={} right_margin_sample_count={}",
            asset.render_asset_id,
            asset.segment_id,
            asset.render_version,
            asset.sample_rate,
            asset.audio_sample_count,
            asset.core_sample_count,
            asset.left_margin_sample_count,
            asset.right_margin_sample_count,
        )
        metadata = {
            "render_asset_id": asset.render_asset_id,
            "segment_id": asset.segment_id,
            "render_version": asset.render_version,
            "sample_rate": asset.sample_rate,
            "semantic_tokens": asset.semantic_tokens,
            "phone_ids": asset.phone_ids,
            "decoder_frame_count": asset.decoder_frame_count,
            "audio_sample_count": asset.audio_sample_count,
            "left_margin_sample_count": asset.left_margin_sample_count,
            "core_sample_count": asset.core_sample_count,
            "right_margin_sample_count": asset.right_margin_sample_count,
            "trace": asset.trace,
        }
        self._asset_store.write_formal_json_atomic(f"segments/{asset.render_asset_id}/metadata.json", metadata)

    def _write_boundary_asset(self, job_id: str, asset: BoundaryAssetPayload) -> None:
        del job_id
        wav_bytes = build_wav_bytes(
            asset.sample_rate,
            float_audio_chunk_to_pcm16_bytes(asset.boundary_audio.astype(np.float32, copy=False)),
        )
        self._asset_store.write_formal_bytes_atomic(f"boundaries/{asset.boundary_asset_id}/audio.wav", wav_bytes)
        metadata = {
            "boundary_asset_id": asset.boundary_asset_id,
            "left_segment_id": asset.left_segment_id,
            "left_render_version": asset.left_render_version,
            "right_segment_id": asset.right_segment_id,
            "right_render_version": asset.right_render_version,
            "edge_version": asset.edge_version,
            "sample_rate": asset.sample_rate,
            "boundary_strategy": asset.boundary_strategy,
            "boundary_sample_count": asset.boundary_sample_count,
            "trace": asset.trace,
        }
        self._asset_store.write_formal_json_atomic(f"boundaries/{asset.boundary_asset_id}/metadata.json", metadata)

    def _write_block_asset(self, job_id: str, asset: BlockCompositionAssetPayload) -> None:
        del job_id
        wav_bytes = build_wav_bytes(
            asset.sample_rate,
            float_audio_chunk_to_pcm16_bytes(asset.audio.astype(np.float32, copy=False)),
        )
        self._asset_store.write_formal_bytes_atomic(f"blocks/{asset.block_asset_id}/audio.wav", wav_bytes)
        render_job_logger.info(
            "block asset persisted block_asset_id={} block_id={} sample_rate={} audio_sample_count={} segment_ids={} edge_count={}",
            asset.block_asset_id,
            asset.block_id,
            asset.sample_rate,
            asset.audio_sample_count,
            list(asset.segment_ids),
            len(asset.edge_entries),
        )
        metadata = {
            "block_id": asset.block_id,
            "block_asset_id": asset.block_asset_id,
            "segment_ids": asset.segment_ids,
            "audio_sample_count": asset.audio_sample_count,
            "segment_entries": [
                {
                    "segment_id": entry.segment_id,
                    "audio_sample_span": list(entry.audio_sample_span),
                    "order_key": entry.order_key,
                    "render_asset_id": entry.render_asset_id,
                    "base_render_asset_id": entry.base_render_asset_id,
                }
                for entry in asset.segment_entries
            ],
            "edge_entries": [
                {
                    "edge_id": entry.edge_id,
                    "left_segment_id": entry.left_segment_id,
                    "right_segment_id": entry.right_segment_id,
                    "boundary_strategy": entry.boundary_strategy,
                    "effective_boundary_strategy": entry.effective_boundary_strategy,
                    "pause_duration_seconds": entry.pause_duration_seconds,
                    "boundary_sample_span": list(entry.boundary_sample_span),
                    "pause_sample_span": list(entry.pause_sample_span),
                }
                for entry in asset.edge_entries
            ],
            "marker_entries": [
                {
                    "marker_type": entry.marker_type,
                    "sample": entry.sample,
                    "related_id": entry.related_id,
                }
                for entry in asset.marker_entries
            ],
        }
        self._asset_store.write_formal_json_atomic(f"blocks/{asset.block_asset_id}/metadata.json", metadata)

    def _write_composition_asset(self, job_id: str, manifest: DocumentCompositionManifestPayload) -> None:
        audio = manifest.audio if manifest.audio is not None else np.zeros(0, dtype=np.float32)
        wav_bytes = build_wav_bytes(
            manifest.sample_rate,
            float_audio_chunk_to_pcm16_bytes(audio.astype(np.float32, copy=False)),
        )
        self._asset_store.write_staging_bytes(
            job_id,
            f"compositions/{manifest.composition_manifest_id}/audio.wav",
            wav_bytes,
        )

    def _write_timeline_manifest(self, manifest: TimelineManifest) -> None:
        self._asset_store.write_formal_json_atomic(
            f"timelines/{manifest.timeline_manifest_id}/manifest.json",
            manifest.model_dump(mode="json"),
        )

    def _get_control_action(self, job_id: str) -> str | None:
        job = self._runtime.get_job(job_id)
        if job is None:
            return None
        if job.cancel_requested:
            return "cancelled_partial"
        if job.pause_requested:
            return "paused"
        return None

    def _commit_partial_after_segment(self, plan: RenderPlan, *, status: str) -> None:
        assert plan.context is not None
        active_session = self._repository.get_active_session()
        if active_session is None:
            raise EditSessionNotFoundError("Active edit session not found.")
        self._persist_completed_prefix_segment_assets(plan)
        self._emit_missing_segment_events_for_completed_prefix(plan)
        working_snapshot = self._build_temporary_snapshot(plan)
        segments_by_id = {segment.segment_id: segment for segment in working_snapshot.segments}
        checkpoint, partial_snapshot = self._checkpoint_service.save_partial_head(
            document_id=plan.document_id,
            job_id=plan.job_id,
            active_session=active_session,
            full_snapshot=working_snapshot,
            resolve_boundary_context=lambda edge: self._get_segment_context(
                plan=plan,
                snapshot=working_snapshot,
                segment=segments_by_id[edge.left_segment_id],
            ),
            segment_assets=plan.segment_assets,
            boundary_assets=plan.boundary_assets,
            status=status,
        )
        self._repository.upsert_active_session(
            active_session.model_copy(
                update={
                    "session_status": "ready",
                    "baseline_snapshot_id": active_session.baseline_snapshot_id or partial_snapshot.snapshot_id,
                    "head_snapshot_id": partial_snapshot.snapshot_id,
                    "active_job_id": None,
                    "updated_at": datetime.now(timezone.utc),
                }
            )
        )
        self._runtime.emit_event(
            plan.job_id,
            "checkpoint_saved",
            checkpoint.model_dump(mode="json"),
        )
        timeline = self._asset_store.load_timeline_manifest(checkpoint.timeline_manifest_id)
        for entry in timeline.block_entries:
            if entry.block_asset_id in plan.emitted_block_ids:
                continue
            self._runtime.emit_event(
                plan.job_id,
                "block_completed",
                {
                    "block_asset_id": entry.block_asset_id,
                    "segment_ids": list(entry.segment_ids),
                    "audio_sample_count": entry.audio_sample_count,
                },
            )
            plan.emitted_block_ids.add(entry.block_asset_id)
        committed_block_asset_ids = self._update_job_committed_state(
            job_id=plan.job_id,
            document_version=checkpoint.document_version,
            timeline=timeline,
            changed_block_asset_ids=plan.changed_block_asset_ids,
        )
        self._runtime.emit_event(
            plan.job_id,
            "timeline_committed",
            {
                "document_version": checkpoint.document_version,
                "timeline_version": timeline.timeline_version,
                "timeline_manifest_id": timeline.timeline_manifest_id,
                "playable_sample_span": list(timeline.playable_sample_span),
                "changed_block_asset_ids": committed_block_asset_ids,
            },
        )
        terminal_event = "job_paused" if status == "paused" else "job_cancelled_partial"
        terminal_message = "当前段已完成，作业已暂停并提交 partial head。" if status == "paused" else "当前段已完成，作业已取消并保留 partial head。"
        self._cancel_inference_tracking(plan, terminal_message)
        self._runtime.update_job(
            plan.job_id,
            status=status,
            message=terminal_message,
            result_document_version=checkpoint.document_version,
            checkpoint_id=checkpoint.checkpoint_id,
            resume_token=checkpoint.resume_token,
        )
        self._runtime.emit_event(
            plan.job_id,
            terminal_event,
            {
                "job_id": plan.job_id,
                "checkpoint_id": checkpoint.checkpoint_id,
                "document_version": checkpoint.document_version,
                "resume_token": checkpoint.resume_token,
            },
        )
        raise _PartialRenderCommitted(
            checkpoint=checkpoint,
            status=status,
            message=terminal_message,
        )

    def _persist_completed_prefix_segment_assets(self, plan: RenderPlan) -> None:
        for segment in sorted(plan.segments, key=lambda item: item.order_key):
            if segment.render_asset_id is None or segment.render_status != "ready":
                break
            asset = plan.segment_assets.get(segment.segment_id)
            if asset is None:
                continue
            segment_asset_path = self._asset_store.segment_asset_path(segment.render_asset_id)
            metadata_path = segment_asset_path / "metadata.json"
            audio_path = segment_asset_path / "audio.wav"
            if metadata_path.exists() and audio_path.exists():
                continue
            self._write_segment_asset(plan.job_id, asset)

    def _emit_missing_segment_events_for_completed_prefix(self, plan: RenderPlan) -> None:
        for segment in sorted(plan.segments, key=lambda item: item.order_key):
            if segment.render_asset_id is None or segment.render_status != "ready":
                break
            if segment.segment_id in plan.emitted_segment_ids:
                continue
            self._runtime.emit_event(
                plan.job_id,
                "segment_completed",
                {
                    "segment_id": segment.segment_id,
                    "order_key": segment.order_key,
                    "render_asset_id": segment.render_asset_id,
                    "render_status": segment.render_status,
                    "effective_duration_samples": segment.effective_duration_samples,
                },
            )
            plan.emitted_segment_ids.add(segment.segment_id)

    def _ensure_not_cancelled(self, job_id: str) -> None:
        job = self._runtime.get_job(job_id)
        if job is not None and job.cancel_requested:
            raise _CancelledJobError("Render job cancelled.")

    def _persist_runtime_job(self, job_id: str) -> None:
        job = self._runtime.get_job(job_id)
        if job is None:
            return
        existing = self._repository.get_render_job(job_id)
        record = RenderJobRecord(
            job_id=job.job_id,
            document_id=job.document_id,
            job_kind=existing.job_kind if existing is not None else "initialize",
            snapshot_id=existing.snapshot_id if existing is not None else None,
            target_segment_ids=existing.target_segment_ids if existing is not None else [],
            target_edge_ids=existing.target_edge_ids if existing is not None else [],
            target_block_ids=existing.target_block_ids if existing is not None else [],
            status=job.status,
            progress=job.progress,
            message=job.message,
            cancel_requested=job.cancel_requested,
            pause_requested=job.pause_requested,
            current_segment_index=job.current_segment_index,
            total_segment_count=job.total_segment_count,
            current_block_index=job.current_block_index,
            total_block_count=job.total_block_count,
            result_document_version=job.result_document_version,
            committed_document_version=job.committed_document_version,
            committed_timeline_manifest_id=job.committed_timeline_manifest_id,
            committed_playable_sample_span=job.committed_playable_sample_span,
            changed_block_asset_ids=list(job.changed_block_asset_ids),
            adapter_error=job.adapter_error,
            checkpoint_id=job.checkpoint_id,
            resume_token=job.resume_token,
            updated_at=job.updated_at,
        )
        self._repository.save_render_job(record)

    def _mark_terminal(self, job_id: str, *, status: str, message: str, adapter_error=None) -> None:
        self._runtime.update_job(
            job_id,
            status=status,
            progress=1.0 if status == "completed" else 0.0,
            message=message,
            adapter_error=adapter_error,
        )
        self._persist_runtime_job(job_id)

    @staticmethod
    def _log_background_job_failure(
        *,
        job_kind: str,
        job_id: str,
        document_id: str,
        phase: str,
        exc: Exception,
    ) -> None:
        render_job_logger.exception(
            "后台渲染作业失败 job_kind={} job_id={} document_id={} phase={} reason={}",
            job_kind,
            job_id,
            document_id,
            phase,
            str(exc),
        )

    def _mark_session_failed(self, document_id: str) -> None:
        session = self._repository.get_active_session()
        if session is None or session.document_id != document_id:
            return
        failed_session = session.model_copy(
            update={
                "session_status": "failed",
                "active_job_id": None,
                "updated_at": datetime.now(timezone.utc),
            }
        )
        self._repository.upsert_active_session(failed_session)

    def _get_available_composition_manifest_id(self, snapshot: DocumentSnapshot) -> str | None:
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

    def _rollback_uncommitted_assets(self, job_id: str) -> None:
        self._asset_store.cleanup_staging_job(job_id)

    def _enqueue_edit_job(
        self,
        *,
        job_kind: str,
        message: str,
        snapshot: DocumentSnapshot,
        impact: TargetedRenderPlan,
        skip_render: bool = False,
        skip_compose: bool = False,
    ) -> RenderJobAcceptedResponse:
        try:
            self._runtime.assert_can_start()
        except RuntimeError as exc:
            raise ActiveRenderJobConflictError(str(exc)) from exc

        active_session = self._session_service.require_active_session()
        request = self._require_initialize_request(active_session)
        now = datetime.now(timezone.utc)
        job = RenderJobResponse(
            job_id=uuid4().hex,
            document_id=snapshot.document_id,
            status="queued",
            progress=0.0,
            message=message,
            cancel_requested=False,
            pause_requested=False,
            updated_at=now,
        )
        self._queued_edit_jobs[job.job_id] = QueuedEditJob(
            job_kind=job_kind,
            request=request,
            snapshot=snapshot,
            target_segment_ids=set(impact.target_segment_ids),
            target_edge_ids=set(impact.target_edge_ids),
            target_block_ids=set(impact.target_block_ids),
            compose_only=impact.compose_only,
            earliest_changed_order_key=impact.earliest_changed_order_key,
            timeline_reflow_required=impact.timeline_reflow_required,
            change_reason=impact.change_reason,
            skip_render=skip_render,
            skip_compose=skip_compose,
            execution_mode="block_first",
        )
        self._repository.upsert_active_session(
            active_session.model_copy(
                update={
                    "active_job_id": job.job_id,
                    "updated_at": now,
                }
            )
        )
        self._repository.save_render_job(
            RenderJobRecord(
                job_id=job.job_id,
                document_id=job.document_id,
                job_kind=job_kind,
                snapshot_id=None,
                target_segment_ids=sorted(impact.target_segment_ids),
                target_edge_ids=sorted(impact.target_edge_ids),
                target_block_ids=sorted(impact.target_block_ids),
                status=job.status,
                progress=job.progress,
                message=job.message,
                cancel_requested=job.cancel_requested,
                pause_requested=job.pause_requested,
                result_document_version=None,
                updated_at=job.updated_at,
            )
        )
        self._runtime.start_job(job)
        self._persist_runtime_job(job.job_id)
        if self._run_jobs_in_background:
            worker = threading.Thread(target=self.run_edit_job, args=(job.job_id,), daemon=True)
            worker.start()
        return RenderJobAcceptedResponse(job=self.get_job(job.job_id) or job)

    def _enqueue_configuration_job(
        self,
        *,
        job_kind: str,
        message: str,
        before_snapshot: DocumentSnapshot,
        after_snapshot: DocumentSnapshot,
        change_reason: str,
    ) -> RenderJobAcceptedResponse:
        if after_snapshot.document_version <= before_snapshot.document_version:
            after_snapshot = after_snapshot.model_copy(
                deep=True,
                update={"document_version": before_snapshot.document_version + 1},
            )
        changed_segment_ids = self._collect_changed_segment_ids(
            before_snapshot=before_snapshot,
            after_snapshot=after_snapshot,
        )
        marked_snapshot = self._mark_segments_for_rerender(
            snapshot=after_snapshot,
            segment_ids=changed_segment_ids,
        )
        impact = self._render_planner.for_snapshot_change(
            before_snapshot=before_snapshot,
            after_snapshot=marked_snapshot,
            changed_segment_ids=changed_segment_ids,
            change_reason=change_reason,
        )
        return self._enqueue_edit_job(
            job_kind=job_kind,
            message=message,
            snapshot=marked_snapshot,
            impact=impact,
        )

    def _collect_changed_segment_ids(
        self,
        *,
        before_snapshot: DocumentSnapshot,
        after_snapshot: DocumentSnapshot,
    ) -> set[str]:
        before_segments = {segment.segment_id for segment in before_snapshot.segments}
        changed_segment_ids: set[str] = set()
        for segment in after_snapshot.segments:
            if segment.segment_id not in before_segments:
                changed_segment_ids.add(segment.segment_id)
                continue
            before_resolved = self._render_config_resolver.resolve_segment(
                snapshot=before_snapshot,
                segment_id=segment.segment_id,
            )
            after_resolved = self._render_config_resolver.resolve_segment(
                snapshot=after_snapshot,
                segment_id=segment.segment_id,
            )
            if before_resolved.render_context_fingerprint != after_resolved.render_context_fingerprint:
                changed_segment_ids.add(segment.segment_id)
                continue
            if before_resolved.model_cache_key != after_resolved.model_cache_key:
                changed_segment_ids.add(segment.segment_id)
        return changed_segment_ids

    @staticmethod
    def _mark_segments_for_rerender(*, snapshot: DocumentSnapshot, segment_ids: set[str]) -> DocumentSnapshot:
        if not segment_ids:
            return snapshot
        next_segments: list[EditableSegment] = []
        for segment in snapshot.segments:
            if segment.segment_id not in segment_ids:
                next_segments.append(segment.model_copy(deep=True))
                continue
            next_segments.append(
                segment.model_copy(
                    deep=True,
                    update={
                        "render_version": segment.render_version + 1,
                        "render_asset_id": None,
                        "assembled_audio_span": None,
                        "effective_duration_samples": None,
                        "render_status": "pending",
                    },
                )
            )
        return snapshot.model_copy(deep=True, update={"segments": next_segments})

    def _resolve_segment_assigned_render_profile_id(self, snapshot: DocumentSnapshot, segment_id: str) -> str | None:
        return self._render_config_resolver.resolve_segment(
            snapshot=snapshot,
            segment_id=segment_id,
        ).render_profile.render_profile_id

    def _prepare_render_profile_patch(self, patch: RenderProfilePatchRequest) -> RenderProfilePatchRequest:
        reference_override = patch.reference_override
        if (
            reference_override is None
            or reference_override.operation != "upsert"
            or not reference_override.session_reference_asset_id
        ):
            return patch
        asset = self._session_service.update_session_reference_asset(
            reference_asset_id=reference_override.session_reference_asset_id,
            binding_key=reference_override.binding_key,
            reference_text=reference_override.reference_text,
            reference_language=reference_override.reference_language,
        )
        return patch.model_copy(
            update={
                "reference_override": reference_override.model_copy(
                    update={
                        "reference_identity": f"{asset.session_id}:{asset.reference_asset_id}",
                        "reference_audio_fingerprint": asset.audio_fingerprint,
                        "reference_audio_path": asset.audio_path,
                        "reference_text_fingerprint": asset.reference_text_fingerprint,
                    }
                )
            }
        )

    def _resolve_segment_assigned_voice_binding_id(self, snapshot: DocumentSnapshot, segment_id: str) -> str | None:
        return self._render_config_resolver.resolve_segment(
            snapshot=snapshot,
            segment_id=segment_id,
        ).voice_binding.voice_binding_id

    @staticmethod
    def _get_voice_binding(snapshot: DocumentSnapshot, voice_binding_id: str | None) -> VoiceBinding:
        if voice_binding_id is None:
            raise EditSessionNotFoundError("Voice binding not found.")
        binding = next((item for item in snapshot.voice_bindings if item.voice_binding_id == voice_binding_id), None)
        if binding is None:
            raise EditSessionNotFoundError(f"Voice binding '{voice_binding_id}' not found.")
        return binding

    @staticmethod
    def _resolve_group_assigned_voice_binding_id(snapshot: DocumentSnapshot, group_id: str) -> str | None:
        group = next((item for item in snapshot.groups if item.group_id == group_id), None)
        if group is None:
            raise EditSessionNotFoundError(f"Segment group '{group_id}' not found.")
        return group.voice_binding_id or snapshot.default_voice_binding_id

    @staticmethod
    def _resolve_group_assigned_render_profile_id(snapshot: DocumentSnapshot, group_id: str) -> str | None:
        group = next((item for item in snapshot.groups if item.group_id == group_id), None)
        if group is None:
            raise EditSessionNotFoundError(f"Segment group '{group_id}' not found.")
        return group.render_profile_id or snapshot.default_render_profile_id

    def _resolve_projected_voice_for_binding_patch(
        self,
        *,
        base_binding: VoiceBinding,
        patch: VoiceBindingPatchRequest,
    ):
        refresh_projected_fields = (
            (patch.voice_id is not None and patch.voice_id != base_binding.voice_id)
            or (patch.model_key is not None and patch.model_key != base_binding.model_key)
        )
        if not refresh_projected_fields:
            return None
        effective_binding_ref = patch.binding_ref or base_binding.binding_ref
        if effective_binding_ref is not None:
            return self._resolve_projected_binding_for_binding_ref(effective_binding_ref)
        return None

    @staticmethod
    def _build_default_configuration(
        request: InitializeEditSessionRequest,
        projected_voice=None,
    ) -> tuple[RenderProfile, VoiceBinding]:
        voice_binding = VoiceBinding(
            voice_binding_id=f"binding-session-{uuid4().hex}",
            scope="session",
            binding_ref=request.binding_ref,
            voice_id=request.voice_id,
            model_key=request.model_id,
            model_instance_id=getattr(projected_voice, "model_instance_id", None),
            preset_id=getattr(projected_voice, "preset_id", None),
            gpt_path=getattr(projected_voice, "gpt_path", None),
            sovits_path=getattr(projected_voice, "sovits_path", None),
        )
        reference_overrides_by_binding: dict[str, ReferenceBindingOverride] = {}
        if request.reference_source == "custom":
            reference_overrides_by_binding[
                build_binding_key(
                    binding_ref=voice_binding.binding_ref,
                    voice_id=voice_binding.voice_id,
                    model_key=voice_binding.model_key,
                )
            ] = ReferenceBindingOverride(
                session_reference_asset_id=None,
                reference_audio_path=request.reference_audio_path,
                reference_text=request.reference_text,
                reference_language=request.reference_language,
            )
        render_profile = RenderProfile(
            render_profile_id=f"profile-session-{uuid4().hex}",
            scope="session",
            name="session-default",
            speed=request.speed,
            top_k=request.top_k,
            top_p=request.top_p,
            temperature=request.temperature,
            noise_scale=request.noise_scale,
            reference_overrides_by_binding=reference_overrides_by_binding,
        )
        return render_profile, voice_binding

    def _get_segment_context(
        self,
        *,
        plan: RenderPlan,
        snapshot: DocumentSnapshot,
        segment: EditableSegment,
    ) -> ReferenceContext:
        resolved = self._render_config_resolver.resolve_segment(snapshot=snapshot, segment_id=segment.segment_id)
        cache_key = f"{resolved.model_cache_key}:{resolved.render_context_fingerprint}"
        context = plan.context_cache.get(cache_key)
        if context is not None:
            return context
        resolved_reference = resolved.resolved_reference
        resolved_context = ResolvedRenderContext(
            voice_id=resolved.voice_binding.voice_id,
            model_key=resolved.voice_binding.model_key,
            reference_audio_path=(
                resolved_reference.reference_audio_path
                if resolved_reference is not None
                else (resolved.render_profile.reference_audio_path or "")
            ),
            reference_text=(
                resolved_reference.reference_text
                if resolved_reference is not None
                else (resolved.render_profile.reference_text or "")
            ),
            reference_language=(
                resolved_reference.reference_language
                if resolved_reference is not None
                else (resolved.render_profile.reference_language or "")
            ),
            reference_scope=(
                resolved_reference.reference_scope
                if resolved_reference is not None
                else "voice_preset"
            ),
            reference_identity=(
                resolved_reference.reference_identity
                if resolved_reference is not None
                else f"{resolved.voice_binding.voice_id}:preset"
            ),
            reference_audio_fingerprint=(
                resolved_reference.reference_audio_fingerprint
                if resolved_reference is not None
                else ""
            ),
            reference_text_fingerprint=(
                resolved_reference.reference_text_fingerprint
                if resolved_reference is not None
                else ""
            ),
            speed=resolved.render_profile.speed,
            top_k=resolved.render_profile.top_k,
            top_p=resolved.render_profile.top_p,
            temperature=resolved.render_profile.temperature,
            noise_scale=resolved.render_profile.noise_scale,
            resolved_voice_binding=ResolvedVoiceBinding(
                voice_binding_id=resolved.voice_binding.voice_binding_id,
                voice_id=resolved.voice_binding.voice_id,
                model_key=resolved.voice_binding.model_key,
                adapter_id=(
                    resolved.resolved_model_binding.adapter_id
                    if resolved.resolved_model_binding is not None
                    else None
                ),
                model_instance_id=(
                    resolved.resolved_model_binding.model_instance_id
                    if resolved.resolved_model_binding is not None
                    else resolved.voice_binding.model_instance_id
                ),
                preset_id=(
                    resolved.resolved_model_binding.preset_id
                    if resolved.resolved_model_binding is not None
                    else resolved.voice_binding.preset_id
                ),
                binding_fingerprint=(
                    resolved.resolved_model_binding.binding_fingerprint
                    if resolved.resolved_model_binding is not None
                    else resolved.model_cache_key
                ),
                gpt_path=resolved.voice_binding.gpt_path,
                sovits_path=resolved.voice_binding.sovits_path,
                speaker_meta=dict(resolved.voice_binding.speaker_meta),
            ),
            render_profile_id=resolved.render_profile.render_profile_id,
            render_profile_fingerprint=resolved.render_context_fingerprint,
        )
        render_job_logger.info(
            "resolved segment context segment_id={} voice_id={} model_key={} reference_audio_path={} reference_language={} speed={} top_k={} top_p={} temperature={} noise_scale={} render_profile_id={} voice_binding_id={}",
            segment.segment_id,
            resolved_context.voice_id,
            resolved_context.model_key,
            resolved_context.reference_audio_path,
            resolved_context.reference_language,
            resolved_context.speed,
            resolved_context.top_k,
            resolved_context.top_p,
            resolved_context.temperature,
            resolved_context.noise_scale,
            resolved_context.render_profile_id,
            resolved_context.resolved_voice_binding.voice_binding_id,
        )
        context = self._gateway.build_reference_context(resolved_context)
        plan.context_cache[cache_key] = context
        return context

    @staticmethod
    def _build_resolved_context_from_request(
        request: InitializeEditSessionRequest,
        projected_voice=None,
    ) -> ResolvedRenderContext:
        return ResolvedRenderContext(
            voice_id=request.voice_id,
            model_key=request.model_id,
            reference_audio_path=request.reference_audio_path or "",
            reference_text=request.reference_text or "",
            reference_language=request.reference_language or "",
            reference_scope="session_override" if request.reference_source == "custom" else "voice_preset",
            reference_identity=(
                build_binding_key(
                    binding_ref=request.binding_ref,
                    voice_id=request.voice_id,
                    model_key=request.model_id,
                )
                if request.reference_source == "custom"
                else f"{build_binding_key(binding_ref=request.binding_ref, voice_id=request.voice_id, model_key=request.model_id)}:preset"
            ),
            speed=request.speed,
            top_k=request.top_k,
            top_p=request.top_p,
            temperature=request.temperature,
            noise_scale=request.noise_scale,
            resolved_voice_binding=ResolvedVoiceBinding(
                voice_binding_id="binding-session-default",
                voice_id=request.voice_id,
                model_key=request.model_id,
                model_instance_id=getattr(projected_voice, "model_instance_id", None),
                preset_id=getattr(projected_voice, "preset_id", None),
                gpt_path=getattr(projected_voice, "gpt_path", None),
                sovits_path=getattr(projected_voice, "sovits_path", None),
            ),
            render_profile_id="profile-session-default",
        )

    def _resolve_projected_binding_for_initialize_request(self, request: InitializeEditSessionRequest):
        return self._resolve_projected_binding_for_binding_ref(request.binding_ref)

    def _resolve_projected_binding_for_binding_ref(self, binding_ref):
        try:
            resolved_binding = self._session_service.resolve_binding_reference(binding_ref)
        except Exception:
            return None
        return SimpleNamespace(
            model_instance_id=resolved_binding.get("model_instance_id"),
            preset_id=binding_ref.preset_id,
            gpt_path=resolved_binding.get("gpt_path"),
            sovits_path=resolved_binding.get("sovits_path"),
            voice_id=resolved_binding.get("voice_id"),
            model_key=resolved_binding.get("model_key"),
        )

    @staticmethod
    def _can_build_local_reference_context(projected_voice) -> bool:
        return bool(
            projected_voice is not None
            and getattr(projected_voice, "gpt_path", None)
            and getattr(projected_voice, "sovits_path", None)
        )

    @staticmethod
    def _require_initialize_request(active_session: ActiveDocumentState) -> InitializeEditSessionRequest:
        if active_session.initialize_request is None:
            raise SnapshotStateError("Active session initialize request is missing.")
        return active_session.initialize_request

    @staticmethod
    def _assert_document_version_matches(*, expected_version: int, actual_version: int) -> None:
        if expected_version != actual_version:
            raise SnapshotStateError(
                f"Base document version {expected_version} does not match current head document version {actual_version}."
            )

    def _load_sample_rate(self, asset_path, *, asset_id: str) -> int:
        try:
            sample_rate, _ = self._asset_store.load_wav_asset(asset_path)
        except FileNotFoundError as exc:
            raise AssetNotFoundError(f"Audio asset '{asset_id}' not found.") from exc
        return sample_rate

    def _load_segment_asset_or_404(self, render_asset_id: str) -> SegmentRenderAssetPayload:
        try:
            return self._asset_store.load_segment_asset(render_asset_id)
        except FileNotFoundError as exc:
            raise AssetNotFoundError(f"Segment asset '{render_asset_id}' not found.") from exc

    def _load_boundary_asset_or_404(self, boundary_asset_id: str) -> BoundaryAssetPayload:
        try:
            return self._asset_store.load_boundary_asset(boundary_asset_id)
        except FileNotFoundError as exc:
            raise AssetNotFoundError(f"Boundary asset '{boundary_asset_id}' not found.") from exc
