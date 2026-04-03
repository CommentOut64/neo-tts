from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import threading
from uuid import uuid4

import numpy as np

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
    SegmentRenderAssetPayload,
    build_boundary_asset_id,
)
from backend.app.inference.text_processing import (
    normalize_whitespace,
    split_text_segments_raw_strong_punctuation,
    split_text_segments_zh_period,
)
from backend.app.repositories.edit_session_repository import EditSessionRepository
from backend.app.schemas.edit_session import (
    ActiveDocumentState,
    CompositionResponse,
    CreateSegmentRequest,
    DocumentSnapshot,
    EditableEdge,
    EditableSegment,
    InitializeEditSessionRequest,
    PlaybackMapResponse,
    PreviewRequest,
    PreviewResponse,
    SegmentAssetResponse,
    BoundaryAssetResponse,
    RenderJobAcceptedResponse,
    RenderJobRecord,
    RenderJobResponse,
    SwapSegmentsRequest,
    UpdateEdgeRequest,
    UpdateSegmentRequest,
)
from backend.app.services.block_planner import BlockPlanner
from backend.app.services.composition_builder import CompositionBuilder
from backend.app.services.edge_service import EdgeService
from backend.app.services.edit_asset_store import EditAssetStore
from backend.app.services.audio_delivery_service import AudioDeliveryService
from backend.app.services.edit_session_runtime import EditSessionRuntime
from backend.app.services.edit_session_service import EditSessionService
from backend.app.services.playback_map_service import PlaybackMapService
from backend.app.services.render_planner import RenderPlanner, TargetedRenderPlan
from backend.app.services.segment_service import SegmentService


class _CancelledJobError(RuntimeError):
    pass


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
    segment_assets: dict[str, SegmentRenderAssetPayload] = field(default_factory=dict)
    boundary_assets: dict[str, BoundaryAssetPayload] = field(default_factory=dict)
    blocks: list[RenderBlock] = field(default_factory=list)
    block_assets: list[BlockCompositionAssetPayload] = field(default_factory=list)
    composition_manifest: DocumentCompositionManifestPayload | None = None
    target_segment_ids: set[str] = field(default_factory=set)
    target_edge_ids: set[str] = field(default_factory=set)
    target_block_ids: set[str] = field(default_factory=set)
    compose_only: bool = False
    skip_render: bool = False
    skip_compose: bool = False


@dataclass(frozen=True)
class QueuedEditJob:
    job_kind: str
    request: InitializeEditSessionRequest
    snapshot: DocumentSnapshot
    target_segment_ids: set[str]
    target_edge_ids: set[str]
    target_block_ids: set[str]
    compose_only: bool = False
    skip_render: bool = False
    skip_compose: bool = False


class RenderJobService:
    def __init__(
        self,
        *,
        repository: EditSessionRepository,
        asset_store: EditAssetStore,
        runtime: EditSessionRuntime,
        session_service: EditSessionService,
        gateway: EditableInferenceGateway,
        block_planner: BlockPlanner | None = None,
        composition_builder: CompositionBuilder | None = None,
        playback_map_service: PlaybackMapService | None = None,
        segment_service: SegmentService | None = None,
        edge_service: EdgeService | None = None,
        render_planner: RenderPlanner | None = None,
        audio_delivery_service: AudioDeliveryService | None = None,
        run_jobs_in_background: bool = True,
        preview_ttl_seconds: int = 600,
    ) -> None:
        self._repository = repository
        self._asset_store = asset_store
        self._runtime = runtime
        self._session_service = session_service
        self._gateway = gateway
        self._block_planner = block_planner or BlockPlanner()
        self._composition_builder = composition_builder or CompositionBuilder()
        self._playback_map_service = playback_map_service or PlaybackMapService()
        self._edge_service = edge_service or EdgeService(repository=repository)
        self._segment_service = segment_service or SegmentService(
            repository=repository,
            edge_service=self._edge_service,
        )
        self._render_planner = render_planner or RenderPlanner(block_planner=self._block_planner)
        self._audio_delivery_service = audio_delivery_service or AudioDeliveryService()
        self._run_jobs_in_background = run_jobs_in_background
        self._preview_ttl_seconds = preview_ttl_seconds
        self._queued_requests: dict[str, InitializeEditSessionRequest] = {}
        self._queued_edit_jobs: dict[str, QueuedEditJob] = {}

    def create_initialize_job(self, request: InitializeEditSessionRequest) -> RenderJobAcceptedResponse:
        try:
            self._runtime.assert_can_start()
        except RuntimeError as exc:
            raise ActiveRenderJobConflictError(str(exc)) from exc

        prepared_request = self._session_service.prepare_initialize_request(request)
        session, job = self._session_service.initialize_document(prepared_request)
        self._queued_requests[job.job_id] = prepared_request
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

    def run_initialize_job(self, job_id: str) -> None:
        request = self._queued_requests.get(job_id)
        job = self.get_job(job_id)
        if request is None or job is None:
            raise EditSessionNotFoundError(f"Render job '{job_id}' not found.")

        plan = RenderPlan(
            job_id=job_id,
            job_kind="initialize",
            document_id=job.document_id,
            request=request,
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
        except _CancelledJobError:
            self._rollback_uncommitted_assets(job_id)
            self._mark_terminal(job_id, status="cancelled", message="渲染任务已取消。")
            self._mark_session_failed(job.document_id)
        except Exception as exc:
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
            target_segment_ids=set(queued_job.target_segment_ids),
            target_edge_ids=set(queued_job.target_edge_ids),
            target_block_ids=set(queued_job.target_block_ids),
            compose_only=queued_job.compose_only,
            skip_render=queued_job.skip_render,
            skip_compose=queued_job.skip_compose,
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
        except _CancelledJobError:
            self._rollback_uncommitted_assets(job_id)
            self._mark_terminal(job_id, status="cancelled", message="渲染任务已取消。")
        except Exception as exc:
            self._rollback_uncommitted_assets(job_id)
            self._mark_terminal(job_id, status="failed", message=str(exc))
        finally:
            self._queued_edit_jobs.pop(job_id, None)

    def cancel_job(self, job_id: str) -> bool:
        accepted = self._runtime.request_cancel(job_id)
        if accepted:
            self._persist_runtime_job(job_id)
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

    def get_composition_response(self) -> CompositionResponse:
        snapshot = self._session_service.get_head_snapshot()
        if snapshot.composition_manifest_id is None:
            raise EditSessionNotFoundError("Composition manifest not found.")
        asset_id = snapshot.composition_manifest_id
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
        playable_sample_span = (
            (0, max(segment.assembled_audio_span[1] for segment in snapshot.segments if segment.assembled_audio_span is not None))
            if any(segment.assembled_audio_span is not None for segment in snapshot.segments)
            else None
        )
        return PlaybackMapResponse(
            document_id=snapshot.document_id,
            document_version=snapshot.document_version,
            composition_manifest_id=snapshot.composition_manifest_id,
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
            sample_rate, audio = self._asset_store.load_wav_asset(
                self._asset_store.boundary_asset_path(boundary_asset_id)
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
            self._prepare(plan)
            self._render(plan)
            self._compose(plan)
            self._commit(plan)
            return
        self._prepare_edit(plan)
        self._render_edit(plan)
        self._compose(plan)
        self._commit_edit(plan)

    def _prepare(self, plan: RenderPlan) -> None:
        self._ensure_not_cancelled(plan.job_id)
        self._runtime.update_job(plan.job_id, status="preparing", progress=0.05, message="正在准备参考上下文。")
        plan.context = self._gateway.build_reference_context(plan.request)
        segments = self._split_raw_segments(
            plan.request.raw_text,
            segment_boundary_mode=plan.request.segment_boundary_mode,
        )
        if not segments:
            raise ValueError("请输入有效文本")
        normalized_text = normalize_whitespace(plan.request.raw_text)
        plan.segments = self._build_segments(plan.document_id, segments, plan.request.text_language)
        plan.edges = self._build_edges(plan.document_id, plan.segments, plan.request.pause_duration_seconds)
        self._runtime.update_job(
            plan.job_id,
            total_segment_count=len(plan.segments),
            message=f"文本切分完成，共 {len(plan.segments)} 段。",
        )
        self._persist_runtime_job(plan.job_id)
        self._ = normalized_text

    def _prepare_edit(self, plan: RenderPlan) -> None:
        self._ensure_not_cancelled(plan.job_id)
        self._runtime.update_job(plan.job_id, status="preparing", progress=0.05, message="正在准备编辑作业。")
        requires_reference_context = bool(plan.target_segment_ids) or (
            bool(plan.target_edge_ids) and plan.job_kind != "segment_swap"
        )
        if not plan.skip_render and not plan.compose_only and requires_reference_context:
            plan.context = self._gateway.build_reference_context(plan.request)
        self._runtime.update_job(
            plan.job_id,
            total_segment_count=len(plan.target_segment_ids) or len(plan.segments),
            message=f"编辑快照准备完成，版本将更新为 {plan.document_version}。",
        )
        self._persist_runtime_job(plan.job_id)

    @staticmethod
    def _split_raw_segments(raw_text: str, *, segment_boundary_mode: str) -> list[str]:
        if segment_boundary_mode == "raw_strong_punctuation":
            return split_text_segments_raw_strong_punctuation(raw_text)
        if segment_boundary_mode == "zh_period":
            return split_text_segments_zh_period(raw_text)
        raise ValueError(f"Unsupported segment_boundary_mode '{segment_boundary_mode}'.")

    def _render(self, plan: RenderPlan) -> None:
        assert plan.context is not None
        self._runtime.update_job(plan.job_id, status="rendering", progress=0.2, message="正在渲染段级资产。")
        total_segments = len(plan.segments)
        for index, segment in enumerate(plan.segments, start=1):
            self._ensure_not_cancelled(plan.job_id)
            asset = self._gateway.render_segment_base(segment, plan.context)
            plan.segment_assets[segment.segment_id] = asset
            segment.render_asset_id = asset.render_asset_id
            segment.assembled_audio_span = (0, asset.audio_sample_count)
            self._write_segment_asset(plan.job_id, asset)
            self._runtime.update_job(
                plan.job_id,
                current_segment_index=index,
                total_segment_count=total_segments,
                progress=0.2 + 0.4 * (index / total_segments),
                message=f"已完成第 {index}/{total_segments} 段渲染。",
            )

        for edge in plan.edges:
            self._ensure_not_cancelled(plan.job_id)
            left_asset = plan.segment_assets[edge.left_segment_id]
            right_asset = plan.segment_assets[edge.right_segment_id]
            boundary_asset = self._gateway.render_boundary_asset(left_asset, right_asset, edge, plan.context)
            plan.boundary_assets[edge.edge_id] = boundary_asset
            self._write_boundary_asset(plan.job_id, boundary_asset)
        self._persist_runtime_job(plan.job_id)

    def _render_edit(self, plan: RenderPlan) -> None:
        if plan.skip_render:
            return

        if not plan.compose_only:
            self._runtime.update_job(plan.job_id, status="rendering", progress=0.2, message="正在重渲染受影响资产。")

        target_total = max(1, len(plan.target_segment_ids))
        completed_targets = 0
        for segment in plan.segments:
            self._ensure_not_cancelled(plan.job_id)
            if segment.segment_id in plan.target_segment_ids:
                if plan.context is None:
                    raise SnapshotStateError("Reference context is required for segment re-render.")
                asset = self._gateway.render_segment_base(segment, plan.context)
                segment.render_asset_id = asset.render_asset_id
                segment.assembled_audio_span = (0, asset.audio_sample_count)
                self._write_segment_asset(plan.job_id, asset)
                completed_targets += 1
                self._runtime.update_job(
                    plan.job_id,
                    current_segment_index=completed_targets,
                    total_segment_count=len(plan.target_segment_ids),
                    progress=0.2 + 0.25 * (completed_targets / target_total),
                    message=f"已重渲染 {completed_targets}/{len(plan.target_segment_ids)} 个目标段。",
                )
            else:
                if segment.render_asset_id is None:
                    raise EditSessionNotFoundError(f"Segment '{segment.segment_id}' asset is missing.")
                asset = self._asset_store.load_segment_asset(segment.render_asset_id)
            plan.segment_assets[segment.segment_id] = asset
            segment.assembled_audio_span = (0, asset.audio_sample_count)

        for edge in plan.edges:
            self._ensure_not_cancelled(plan.job_id)
            left_asset = plan.segment_assets[edge.left_segment_id]
            right_asset = plan.segment_assets[edge.right_segment_id]
            if edge.edge_id in plan.target_edge_ids:
                if plan.job_kind == "segment_swap":
                    boundary_asset = self._build_fallback_boundary_asset(left_asset, right_asset, edge)
                else:
                    if plan.context is None:
                        raise SnapshotStateError("Reference context is required for boundary re-render.")
                    boundary_asset = self._gateway.render_boundary_asset(left_asset, right_asset, edge, plan.context)
                self._write_boundary_asset(plan.job_id, boundary_asset)
            else:
                boundary_asset = self._asset_store.load_boundary_asset(
                    build_boundary_asset_id(
                        left_segment_id=edge.left_segment_id,
                        left_render_version=left_asset.render_version,
                        right_segment_id=edge.right_segment_id,
                        right_render_version=right_asset.render_version,
                        edge_version=edge.edge_version,
                        boundary_strategy=edge.boundary_strategy,
                    )
                )
            plan.boundary_assets[edge.edge_id] = boundary_asset
        self._persist_runtime_job(plan.job_id)

    def _build_fallback_boundary_asset(
        self,
        left_asset: SegmentRenderAssetPayload,
        right_asset: SegmentRenderAssetPayload,
        edge: EditableEdge,
    ) -> BoundaryAssetPayload:
        left_margin = left_asset.right_margin_audio.astype(np.float32, copy=False)
        right_margin = right_asset.left_margin_audio.astype(np.float32, copy=False)
        if left_margin.size == 0:
            boundary_audio = right_margin.copy()
        elif right_margin.size == 0:
            boundary_audio = left_margin.copy()
        else:
            overlap = min(int(left_margin.size), int(right_margin.size))
            prefix = left_margin[:-overlap]
            suffix = right_margin[overlap:]
            theta = np.linspace(0.0, np.pi / 2.0, overlap, endpoint=True, dtype=np.float32)
            crossfaded = (np.cos(theta) * left_margin[-overlap:] + np.sin(theta) * right_margin[:overlap]).astype(
                np.float32,
                copy=False,
            )
            boundary_audio = np.concatenate([prefix, crossfaded, suffix]).astype(np.float32, copy=False)
        return BoundaryAssetPayload(
            boundary_asset_id=build_boundary_asset_id(
                left_segment_id=edge.left_segment_id,
                left_render_version=left_asset.render_version,
                right_segment_id=edge.right_segment_id,
                right_render_version=right_asset.render_version,
                edge_version=edge.edge_version,
                boundary_strategy=edge.boundary_strategy,
            ),
            left_segment_id=edge.left_segment_id,
            left_render_version=left_asset.render_version,
            right_segment_id=edge.right_segment_id,
            right_render_version=right_asset.render_version,
            edge_version=edge.edge_version,
            boundary_strategy=edge.boundary_strategy,
            boundary_sample_count=int(boundary_audio.size),
            boundary_audio=boundary_audio,
            trace={"boundary_kind": "fallback_equal_power_crossfade"},
        )

    def _compose(self, plan: RenderPlan) -> None:
        if plan.skip_compose:
            return
        self._ensure_not_cancelled(plan.job_id)
        self._runtime.update_job(plan.job_id, status="composing", progress=0.7, message="正在装配 block 与文档音频。")
        plan.blocks = self._block_planner.build_blocks(plan.segments)
        self._runtime.update_job(plan.job_id, total_block_count=len(plan.blocks))
        previous_block_ids: set[str] = set()
        if plan.job_kind != "initialize":
            previous_block_ids = set(self._session_service.get_head_snapshot().block_ids)

        for index, block in enumerate(plan.blocks, start=1):
            block_segments = [plan.segment_assets[segment_id] for segment_id in block.segment_ids]
            block_edges = [edge for edge in plan.edges if edge.left_segment_id in block.segment_ids and edge.right_segment_id in block.segment_ids]
            block_boundaries = [
                plan.boundary_assets[edge.edge_id]
                for edge in block_edges
                if edge.edge_id in plan.boundary_assets
            ]
            should_compose_block = (
                plan.job_kind == "initialize"
                or block.block_id in plan.target_block_ids
                or bool(plan.target_segment_ids.intersection(block.segment_ids))
                or any(edge.edge_id in plan.target_edge_ids for edge in block_edges)
                or block.block_id not in previous_block_ids
            )
            if should_compose_block:
                block_asset = self._composition_builder.compose_block(
                    segments=block_segments,
                    boundaries=block_boundaries,
                    edges=block_edges,
                    block_id=block.block_id,
                )
                self._write_block_asset(plan.job_id, block_asset)
            else:
                try:
                    block_asset = self._asset_store.load_block_asset(block.block_id)
                except (FileNotFoundError, ValueError):
                    block_asset = self._composition_builder.compose_block(
                        segments=block_segments,
                        boundaries=block_boundaries,
                        edges=block_edges,
                        block_id=block.block_id,
                    )
                    self._write_block_asset(plan.job_id, block_asset)
            plan.block_assets.append(block_asset)
            self._runtime.update_job(
                plan.job_id,
                current_block_index=index,
                total_block_count=len(plan.blocks),
                progress=0.7 + 0.15 * (index / max(1, len(plan.blocks))),
                message=f"已完成第 {index}/{len(plan.blocks)} 个 block 装配。",
            )

        plan.composition_manifest = self._composition_builder.compose_document(
            document_id=plan.document_id,
            document_version=plan.document_version,
            blocks=plan.block_assets,
        )
        self._write_composition_asset(plan.job_id, plan.composition_manifest)
        playback_map = self._playback_map_service.rebuild(manifest=plan.composition_manifest, segments=plan.segments)
        span_by_segment_id = {entry.segment_id: entry.audio_sample_span for entry in playback_map.entries}
        for segment in plan.segments:
            segment.assembled_audio_span = span_by_segment_id.get(segment.segment_id)
        self._persist_runtime_job(plan.job_id)

    def _commit(self, plan: RenderPlan) -> None:
        assert plan.composition_manifest is not None
        self._ensure_not_cancelled(plan.job_id)
        self._runtime.update_job(plan.job_id, status="committing", progress=0.9, message="正在提交快照与资产。")
        self._asset_store.promote_staging_tree(plan.job_id, "formal")

        snapshot_payload = {
            "document_id": plan.document_id,
            "document_version": 1,
            "raw_text": plan.request.raw_text,
            "normalized_text": normalize_whitespace(plan.request.raw_text),
            "segment_ids": [segment.segment_id for segment in plan.segments],
            "edge_ids": [edge.edge_id for edge in plan.edges],
            "block_ids": plan.composition_manifest.block_ids,
            "composition_manifest_id": plan.composition_manifest.composition_manifest_id,
            "playback_map_version": 1,
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
        self._runtime.update_job(
            plan.job_id,
            status="completed",
            progress=1.0,
            message="初始化渲染完成。",
            result_document_version=1,
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
            composition_manifest_id = self._repository.get_snapshot(active_session.baseline_snapshot_id).composition_manifest_id if active_session.baseline_snapshot_id else None
            block_ids = self._repository.get_snapshot(active_session.baseline_snapshot_id).block_ids if active_session.baseline_snapshot_id else []
            playback_map_version = self._repository.get_snapshot(active_session.baseline_snapshot_id).playback_map_version if active_session.baseline_snapshot_id else None
        else:
            assert plan.composition_manifest is not None
            composition_manifest_id = plan.composition_manifest.composition_manifest_id
            block_ids = plan.composition_manifest.block_ids
            playback_map_version = plan.document_version

        head_snapshot = DocumentSnapshot(
            snapshot_id=f"head-{uuid4().hex}",
            document_id=plan.document_id,
            snapshot_kind="head",
            document_version=plan.document_version,
            raw_text="".join(segment.raw_text for segment in plan.segments),
            normalized_text="".join(segment.normalized_text for segment in plan.segments),
            segment_ids=[segment.segment_id for segment in plan.segments],
            edge_ids=[edge.edge_id for edge in plan.edges],
            block_ids=block_ids,
            composition_manifest_id=composition_manifest_id,
            playback_map_version=playback_map_version,
            segments=plan.segments,
            edges=plan.edges,
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
        self._persist_runtime_job(plan.job_id)

    def _build_segments(
        self,
        document_id: str,
        raw_segments: list[str],
        text_language: str,
    ) -> list[EditableSegment]:
        segments: list[EditableSegment] = []
        for index, raw_text in enumerate(raw_segments, start=1):
            previous_segment_id = segments[-1].segment_id if segments else None
            segment_id = f"segment-{uuid4().hex}"
            normalized_text, risk_flags = self._segment_service.describe_segment_text(raw_text)
            segment = EditableSegment(
                segment_id=segment_id,
                document_id=document_id,
                order_key=index,
                previous_segment_id=previous_segment_id,
                raw_text=normalized_text,
                normalized_text=normalized_text,
                text_language=text_language,
                render_version=1,
                risk_flags=risk_flags,
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
        audio = np.concatenate([asset.left_margin_audio, asset.core_audio, asset.right_margin_audio]).astype(
            np.float32,
            copy=False,
        )
        wav_bytes = build_wav_bytes(self._composition_builder._sample_rate, float_audio_chunk_to_pcm16_bytes(audio))
        self._asset_store.write_staging_bytes(job_id, f"segments/{asset.render_asset_id}/audio.wav", wav_bytes)
        metadata = {
            "render_asset_id": asset.render_asset_id,
            "segment_id": asset.segment_id,
            "render_version": asset.render_version,
            "semantic_tokens": asset.semantic_tokens,
            "phone_ids": asset.phone_ids,
            "decoder_frame_count": asset.decoder_frame_count,
            "audio_sample_count": asset.audio_sample_count,
            "left_margin_sample_count": asset.left_margin_sample_count,
            "core_sample_count": asset.core_sample_count,
            "right_margin_sample_count": asset.right_margin_sample_count,
            "trace": asset.trace,
        }
        self._asset_store.write_staging_bytes(
            job_id,
            f"segments/{asset.render_asset_id}/metadata.json",
            json.dumps(metadata, ensure_ascii=False, indent=2).encode("utf-8"),
        )

    def _write_boundary_asset(self, job_id: str, asset: BoundaryAssetPayload) -> None:
        wav_bytes = build_wav_bytes(
            self._composition_builder._sample_rate,
            float_audio_chunk_to_pcm16_bytes(asset.boundary_audio.astype(np.float32, copy=False)),
        )
        self._asset_store.write_staging_bytes(job_id, f"boundaries/{asset.boundary_asset_id}/audio.wav", wav_bytes)
        metadata = {
            "boundary_asset_id": asset.boundary_asset_id,
            "left_segment_id": asset.left_segment_id,
            "left_render_version": asset.left_render_version,
            "right_segment_id": asset.right_segment_id,
            "right_render_version": asset.right_render_version,
            "edge_version": asset.edge_version,
            "boundary_strategy": asset.boundary_strategy,
            "boundary_sample_count": asset.boundary_sample_count,
            "trace": asset.trace,
        }
        self._asset_store.write_staging_bytes(
            job_id,
            f"boundaries/{asset.boundary_asset_id}/metadata.json",
            json.dumps(metadata, ensure_ascii=False, indent=2).encode("utf-8"),
        )

    def _write_block_asset(self, job_id: str, asset: BlockCompositionAssetPayload) -> None:
        wav_bytes = build_wav_bytes(
            asset.sample_rate,
            float_audio_chunk_to_pcm16_bytes(asset.audio.astype(np.float32, copy=False)),
        )
        self._asset_store.write_staging_bytes(job_id, f"blocks/{asset.block_id}/audio.wav", wav_bytes)
        metadata = {
            "block_id": asset.block_id,
            "segment_ids": asset.segment_ids,
            "audio_sample_count": asset.audio_sample_count,
            "segment_entries": [
                {
                    "segment_id": entry.segment_id,
                    "audio_sample_span": list(entry.audio_sample_span),
                    "order_key": entry.order_key,
                }
                for entry in asset.segment_entries
            ],
        }
        self._asset_store.write_staging_bytes(
            job_id,
            f"blocks/{asset.block_id}/metadata.json",
            json.dumps(metadata, ensure_ascii=False, indent=2).encode("utf-8"),
        )

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
            current_segment_index=job.current_segment_index,
            total_segment_count=job.total_segment_count,
            current_block_index=job.current_block_index,
            total_block_count=job.total_block_count,
            result_document_version=job.result_document_version,
            updated_at=job.updated_at,
        )
        self._repository.save_render_job(record)

    def _mark_terminal(self, job_id: str, *, status: str, message: str) -> None:
        self._runtime.update_job(job_id, status=status, progress=1.0 if status == "completed" else 0.0, message=message)
        self._persist_runtime_job(job_id)

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
            skip_render=skip_render,
            skip_compose=skip_compose,
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

    @staticmethod
    def _require_initialize_request(active_session: ActiveDocumentState) -> InitializeEditSessionRequest:
        if active_session.initialize_request is None:
            raise SnapshotStateError("Active session initialize request is missing.")
        return active_session.initialize_request

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
