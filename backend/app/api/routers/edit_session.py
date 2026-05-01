from __future__ import annotations

import json
from pathlib import Path
import queue

from fastapi import APIRouter, File, Query, Request, UploadFile
from fastapi.responses import Response, StreamingResponse

from backend.app.api.reference_audio_upload import (
    validate_reference_audio_filename,
)
from backend.app.core.path_resolution import resolve_runtime_path
from backend.app.core.exceptions import AssetNotFoundError, EditSessionNotFoundError
from backend.app.inference.editable_gateway import (
    CacheBackedEditableInferenceBackend,
    EditableInferenceGateway,
    LazyEditableInferenceGateway,
    RoutingEditableInferenceGateway,
)
from backend.app.inference.adapters import GPTSoVITSLocalAdapter
from backend.app.inference.block_adapter_registry import AdapterRegistry
from backend.app.repositories.voice_repository import VoiceRepository
from backend.app.schemas.edit_session import (
    AppendSegmentsRequest,
    BaselineSnapshotResponse,
    BoundaryAssetResponse,
    CompositionExportRequest,
    CompositionResponse,
    ConfigurationCommitResponse,
    CreateSegmentRequest,
    CurrentCheckpointResponse,
    EdgeListResponse,
    EditSessionSnapshotResponse,
    ExportRequest,
    ExportJobAcceptedResponse,
    ExportJobResponse,
    GroupListResponse,
    InitializeEditSessionRequest,
    MergeSegmentsRequest,
    MoveSegmentRangeRequest,
    PlaybackMapResponse,
    PreviewRequest,
    PreviewResponse,
    ReorderSegmentsRequest,
    ReferenceAudioUploadResponse,
    RenderProfilePatchRequest,
    RenderProfileListResponse,
    RenderJobAcceptedResponse,
    RenderJobResponse,
    SegmentExportRequest,
    SegmentAssetResponse,
    SegmentBatchRenderProfilePatchRequest,
    SegmentBatchVoiceBindingPatchRequest,
    SegmentListResponse,
    SplitSegmentRequest,
    StandardizationPreviewRequest,
    StandardizationPreviewResponse,
    SwapSegmentsRequest,
    TimelineManifest,
    UpdateEdgeRequest,
    UpdateSegmentRequest,
    VoiceBindingListResponse,
    VoiceBindingPatchRequest,
)
from backend.app.services.audio_delivery_service import AudioDeliveryService
from backend.app.services.edit_session_service import EditSessionService
from backend.app.services.export_service import ExportService
from backend.app.services.render_job_service import RenderJobService
from backend.app.services.voice_service import VoiceService
from backend.app.tts_registry.adapter_definition_store import build_default_adapter_definition_store
from backend.app.tts_registry.model_registry import ModelRegistry
from backend.app.tts_registry.secret_store import SecretStore


router = APIRouter(prefix="/v1/edit-session", tags=["edit-session"])

BAD_REQUEST_RESPONSE = {
    400: {
        "description": "请求参数不合法，或不满足当前 edit-session 的业务约束。",
    }
}
NOT_FOUND_RESPONSE = {
    404: {
        "description": "目标会话、作业、导出记录或音频资产不存在。",
    }
}
CONFLICT_RESPONSE = {
    409: {
        "description": "当前已有活动作业，无法启动新的异步编辑作业。",
    }
}
GONE_RESPONSE = {
    410: {
        "description": "临时预览资源已过期，需要重新请求 preview。",
    }
}


class _UnavailableEditableBackend:
    def build_reference_context(self, request):
        raise RuntimeError("Editable inference backend is unavailable for read-only operations.")

    def render_segment_base(self, segment, context, *, progress_callback=None):
        raise RuntimeError("Editable inference backend is unavailable for read-only operations.")

    def render_boundary_asset(self, left_asset, right_asset, edge, context):
        raise RuntimeError("Editable inference backend is unavailable for read-only operations.")


def _build_voice_service(request: Request) -> VoiceService:
    model_registry = _build_model_registry(request)
    settings = request.app.state.settings
    repository = VoiceRepository(config_path=settings.voices_config_path, settings=settings)
    return VoiceService(repository, model_registry)


def _build_model_registry(request: Request) -> ModelRegistry:
    shared = getattr(request.app.state, "model_registry", None)
    if shared is not None:
        return shared
    settings = request.app.state.settings
    registry_root = settings.tts_registry_root or (settings.user_data_root / "tts-registry")
    return ModelRegistry(registry_root)


def _build_secret_store(request: Request) -> SecretStore:
    shared = getattr(request.app.state, "secret_store", None)
    if shared is not None:
        return shared
    settings = request.app.state.settings
    registry_root = settings.tts_registry_root or (settings.user_data_root / "tts-registry")
    return SecretStore(registry_root)


def _build_adapter_registry(request: Request) -> AdapterRegistry:
    shared = getattr(request.app.state, "adapter_registry", None)
    if shared is not None:
        return shared
    store = build_default_adapter_definition_store(
        enable_gpt_sovits_local=getattr(request.app.state.settings, "gpt_sovits_adapter_installed", True),
    )
    registry = AdapterRegistry()
    for definition in store.list_definitions():
        registry.register(definition)
    return registry


def _build_block_adapter_selector(request: Request):
    shared = getattr(request.app.state, "block_adapter_selector", None)
    if shared is not None:
        return shared

    def _select_adapter(adapter_id: str, **kwargs):
        if adapter_id == "gpt_sovits_local":
            return GPTSoVITSLocalAdapter(
                editable_gateway=kwargs["gateway"],
                composition_builder=kwargs.get("composition_builder"),
                reusable_asset_accessor=kwargs.get("asset_store"),
                cancellation_checker=kwargs.get("cancellation_checker"),
                segment_asset_callback=kwargs.get("segment_asset_callback"),
            )
        raise AdapterRegistry.build_model_required_error(adapter_id=adapter_id)

    return _select_adapter


def _resolve_runtime_model_path(request: Request, raw_path: str) -> str:
    settings = request.app.state.settings
    return str(
        resolve_runtime_path(
            raw_path,
            project_root=settings.project_root,
            user_data_root=settings.user_data_root,
            resources_root=settings.resources_root,
            managed_voices_dir=settings.managed_voices_dir,
        )
    )


def _build_editable_gateway(
    request: Request,
    *,
    voice_id: str,
) -> EditableInferenceGateway | LazyEditableInferenceGateway | RoutingEditableInferenceGateway:
    existing = getattr(request.app.state, "editable_inference_gateway", None)
    if existing is not None:
        return existing

    settings = request.app.state.settings
    model_cache = getattr(request.app.state, "model_cache", None)
    if model_cache is None:
        from backend.app.inference.model_cache import PyTorchModelCache, build_model_cache_from_settings

        model_cache = build_model_cache_from_settings(
            settings=settings,
            model_cache_cls=PyTorchModelCache,
        )
        request.app.state.model_cache = model_cache
    voice_service = _build_voice_service(request)
    voice = voice_service.get_voice(voice_id)
    cache: dict[tuple[str, str], EditableInferenceGateway | LazyEditableInferenceGateway] = getattr(
        request.app.state,
        "editable_inference_gateway_cache",
        {},
    )
    default_cache_key = (voice.gpt_path, voice.sovits_path)

    def _build_cached_gateway(gpt_path: str, sovits_path: str) -> LazyEditableInferenceGateway:
        resolved_gpt_path = _resolve_runtime_model_path(request, gpt_path)
        resolved_sovits_path = _resolve_runtime_model_path(request, sovits_path)

        def _build_backend():
            return CacheBackedEditableInferenceBackend(
                model_cache=model_cache,
                gpt_path=resolved_gpt_path,
                sovits_path=resolved_sovits_path,
            )

        return LazyEditableInferenceGateway(backend_factory=_build_backend)

    if default_cache_key not in cache:
        cache[default_cache_key] = _build_cached_gateway(*default_cache_key)
        request.app.state.editable_inference_gateway_cache = cache
    return RoutingEditableInferenceGateway(
        default_gateway=cache[default_cache_key],
        gateway_cache=cache,
        gateway_factory=_build_cached_gateway,
    )


def _build_edit_session_service(request: Request) -> EditSessionService:
    return EditSessionService(
        repository=request.app.state.edit_session_repository,
        asset_store=request.app.state.edit_asset_store,
        runtime=request.app.state.edit_session_runtime,
        voice_service=_build_voice_service(request),
    )


def _build_render_job_service(request: Request, *, voice_id: str | None = None) -> RenderJobService:
    if voice_id is None:
        active_session = request.app.state.edit_session_repository.get_active_session()
        if active_session is None or active_session.initialize_request is None:
            raise EditSessionNotFoundError("Active edit session not found.")
        voice_id = active_session.initialize_request.voice_id
    return RenderJobService(
        repository=request.app.state.edit_session_repository,
        asset_store=request.app.state.edit_asset_store,
        runtime=request.app.state.edit_session_runtime,
        inference_runtime=request.app.state.inference_runtime,
        session_service=_build_edit_session_service(request),
        gateway=_build_editable_gateway(request, voice_id=voice_id),
        audio_delivery_service=AudioDeliveryService(),
        model_registry=_build_model_registry(request),
        adapter_registry=_build_adapter_registry(request),
        secret_store=_build_secret_store(request),
        block_render_request_builder=getattr(request.app.state, "block_render_request_builder", None),
        block_render_asset_persister=getattr(request.app.state, "block_render_asset_persister", None),
        block_adapter_selector=_build_block_adapter_selector(request),
        block_first_enabled=getattr(request.app.state.settings, "edit_session_block_first_enabled", True),
    )


def _build_readonly_render_job_service(request: Request) -> RenderJobService:
    gateway = getattr(request.app.state, "editable_inference_gateway", None)
    if gateway is None:
        gateway = EditableInferenceGateway(_UnavailableEditableBackend())
    return RenderJobService(
        repository=request.app.state.edit_session_repository,
        asset_store=request.app.state.edit_asset_store,
        runtime=request.app.state.edit_session_runtime,
        inference_runtime=request.app.state.inference_runtime,
        session_service=_build_edit_session_service(request),
        gateway=gateway,
        audio_delivery_service=AudioDeliveryService(),
        model_registry=_build_model_registry(request),
        adapter_registry=_build_adapter_registry(request),
        secret_store=_build_secret_store(request),
        block_render_request_builder=getattr(request.app.state, "block_render_request_builder", None),
        block_render_asset_persister=getattr(request.app.state, "block_render_asset_persister", None),
        block_adapter_selector=_build_block_adapter_selector(request),
        block_first_enabled=getattr(request.app.state.settings, "edit_session_block_first_enabled", True),
        run_jobs_in_background=False,
    )


def _build_export_service(request: Request) -> ExportService:
    return request.app.state.edit_session_export_service


def _build_audio_delivery_service() -> AudioDeliveryService:
    return AudioDeliveryService()


def _stream_audio_asset(
    request: Request,
    *,
    asset_path: Path,
    etag: str,
    expires_at=None,
    download: bool = False,
) -> Response:
    return _build_audio_delivery_service().build_streaming_response(
        request=request,
        asset_path=asset_path,
        content_type="audio/wav",
        etag=etag,
        expires_at=expires_at,
        download=download,
    )


def _build_formal_audio_descriptor(request: Request, *, asset_id: str, asset_path: Path):
    audio_service = _build_audio_delivery_service()
    try:
        sample_rate, _ = request.app.state.edit_asset_store.load_wav_asset(asset_path)
    except FileNotFoundError as exc:
        raise AssetNotFoundError(f"Audio asset '{asset_id}' not found.") from exc
    return audio_service.build_descriptor(
        asset_id=asset_id,
        audio_url=str(request.url.path),
        asset_path=asset_path,
        sample_rate=sample_rate,
    )


def _encode_sse_event(event: str, payload: dict) -> str:
    encoded_payload = json.dumps(payload, ensure_ascii=False)
    return f"event: {event}\ndata: {encoded_payload}\n\n"


def _is_terminal_job_payload(payload: dict) -> bool:
    return payload.get("status") in {"paused", "cancelled_partial", "completed", "failed"}


def _should_close_live_event_stream(event_type: str, payload: dict) -> bool:
    if event_type in {"job_paused", "job_cancelled_partial"}:
        return True
    if event_type != "job_state_changed":
        return False
    return payload.get("status") in {"completed", "failed"}


def _should_close_export_event_stream(event_type: str, payload: dict) -> bool:
    if event_type == "export_completed":
        return True
    if event_type != "job_state_changed":
        return False
    return payload.get("status") in {"completed", "failed"}


@router.post(
    "/reference-audio",
    response_model=ReferenceAudioUploadResponse,
    summary="上传临时参考音频",
    description="上传参考音频文件并返回可用于 edit-session 的临时路径。",
    responses=BAD_REQUEST_RESPONSE,
)
async def upload_reference_audio(
    request: Request,
    ref_audio_file: UploadFile = File(..., description="参考音频文件，支持 `.wav`、`.mp3`、`.flac`。"),
) -> ReferenceAudioUploadResponse:
    filename = validate_reference_audio_filename(ref_audio_file.filename)
    payload = await ref_audio_file.read()
    asset = _build_edit_session_service(request).create_session_reference_asset(
        filename=filename,
        payload=payload,
    )
    return ReferenceAudioUploadResponse(
        reference_asset_id=asset.reference_asset_id,
        reference_scope="session_override",
        reference_identity=f"{asset.session_id}:{asset.reference_asset_id}",
        reference_audio_fingerprint=asset.audio_fingerprint,
        reference_text_fingerprint=asset.reference_text_fingerprint,
        reference_audio_path=asset.audio_path,
        filename=filename,
    )


@router.post(
    "/initialize",
    response_model=RenderJobAcceptedResponse,
    status_code=202,
    summary="初始化编辑会话",
    description=(
        "创建一个新的 edit-session 初始化作业。"
        "该接口会切分文本、触发首轮渲染、生成 timeline，并在作业完成后提交 document_version=1。"
    ),
    responses={**BAD_REQUEST_RESPONSE, **CONFLICT_RESPONSE},
)
def initialize_edit_session(request: Request, body: InitializeEditSessionRequest) -> RenderJobAcceptedResponse:
    service = _build_render_job_service(request, voice_id=body.voice_id)
    return service.create_initialize_job(body)


@router.post(
    "/render-jobs",
    response_model=RenderJobAcceptedResponse,
    status_code=202,
    summary="兼容：创建初始化作业",
    description="兼容旧调用方式，语义与 `POST /v1/edit-session/initialize` 相同。",
    responses={**BAD_REQUEST_RESPONSE, **CONFLICT_RESPONSE},
)
def create_render_job(request: Request, body: InitializeEditSessionRequest) -> RenderJobAcceptedResponse:
    service = _build_render_job_service(request, voice_id=body.voice_id)
    return service.create_initialize_job(body)


@router.get(
    "/snapshot",
    response_model=EditSessionSnapshotResponse,
    summary="读取当前会话快照摘要",
    description=(
        "返回当前活动 edit-session 的摘要视图，包括 document_version、timeline、兼容 composition 字段、活动作业和可选的内联段/边列表。"
    ),
)
def get_snapshot(request: Request) -> EditSessionSnapshotResponse:
    return _build_edit_session_service(request).get_snapshot()


@router.get(
    "/baseline",
    response_model=BaselineSnapshotResponse,
    summary="读取基线快照",
    description="返回当前 edit-session 的 baseline 快照，用于与当前 head 对比或执行恢复基线。",
)
def get_baseline(request: Request) -> BaselineSnapshotResponse:
    return _build_edit_session_service(request).get_baseline()


@router.get(
    "/timeline",
    response_model=TimelineManifest,
    summary="读取权威时间线",
    description="返回当前 document_version 的权威播放对象。前端应优先依赖该接口，而不是 `/playback-map`。",
    responses=NOT_FOUND_RESPONSE,
)
def get_timeline(request: Request) -> TimelineManifest:
    return _build_edit_session_service(request).get_timeline()


@router.get(
    "/checkpoints/current",
    response_model=CurrentCheckpointResponse,
    summary="读取当前 checkpoint",
    description="返回当前文档最新的可恢复 checkpoint；若无可恢复状态，则返回 `checkpoint=null`。",
)
def get_current_checkpoint(request: Request) -> CurrentCheckpointResponse:
    return _build_edit_session_service(request).get_current_checkpoint()


@router.get(
    "/groups",
    response_model=GroupListResponse,
    summary="列出段分组",
    description="返回当前 head snapshot 中的全部 `SegmentGroup`，用于前端显示 append 组和批量配置组。",
    responses=NOT_FOUND_RESPONSE,
)
def get_groups(request: Request) -> GroupListResponse:
    return _build_readonly_render_job_service(request).list_groups()


@router.get(
    "/render-profiles",
    response_model=RenderProfileListResponse,
    summary="列出渲染配置",
    description="返回当前文档已存在的 session/group/segment 级 render profile。",
    responses=NOT_FOUND_RESPONSE,
)
def get_render_profiles(request: Request) -> RenderProfileListResponse:
    return _build_readonly_render_job_service(request).list_render_profiles()


@router.get(
    "/voice-bindings",
    response_model=VoiceBindingListResponse,
    summary="列出音色与模型绑定",
    description="返回当前文档已存在的 session/group/segment 级 voice/model binding。",
    responses=NOT_FOUND_RESPONSE,
)
def get_voice_bindings(request: Request) -> VoiceBindingListResponse:
    return _build_readonly_render_job_service(request).list_voice_bindings()


@router.delete(
    "",
    status_code=204,
    summary="结束当前编辑会话",
    description="安全结束当前活动 edit-session；若存在 active render job，会先请求取消并等待作业收口，再清空会话记录与本地编辑资产。",
)
def delete_session(request: Request) -> Response:
    _build_edit_session_service(request).delete_session()
    return Response(status_code=204)


@router.post(
    "/restore-baseline",
    response_model=RenderJobAcceptedResponse,
    status_code=202,
    summary="恢复到基线版本",
    description="创建一个恢复基线作业，将当前 head 回滚到 baseline 的内容并提交为新的 document_version。",
    responses={**NOT_FOUND_RESPONSE, **CONFLICT_RESPONSE},
)
def restore_baseline(request: Request) -> RenderJobAcceptedResponse:
    return _build_render_job_service(request).create_restore_baseline_job()


@router.get(
    "/segments",
    response_model=SegmentListResponse,
    summary="分页列出段",
    description="按 `order_key` 升序分页返回当前 head snapshot 中的段列表。",
    responses=NOT_FOUND_RESPONSE,
)
def list_segments(
    request: Request,
    limit: int = Query(default=1000, ge=1, le=1000, description="分页大小，最大 1000。"),
    cursor: int | None = Query(default=None, description="上一页最后一个段的 `order_key`。"),
) -> SegmentListResponse:
    service = _build_readonly_render_job_service(request)
    snapshot = service.get_head_snapshot()
    items = [item.model_dump(mode="json") for item in service.list_segments(limit=limit, cursor=cursor)]
    next_cursor = items[-1]["order_key"] if len(items) == limit else None
    return SegmentListResponse(
        document_id=snapshot.document_id,
        document_version=snapshot.document_version,
        items=items,
        next_cursor=next_cursor,
    )


@router.post(
    "/segments",
    response_model=RenderJobAcceptedResponse,
    status_code=202,
    summary="插入新段",
    description="在指定段之后插入一个新段，并创建异步渲染作业。成功后会生成新的 `document_version`。",
    responses={**BAD_REQUEST_RESPONSE, **NOT_FOUND_RESPONSE, **CONFLICT_RESPONSE},
)
def create_segment(request: Request, body: CreateSegmentRequest) -> RenderJobAcceptedResponse:
    return _build_render_job_service(request).create_insert_segment_job(body)


@router.post(
    "/append",
    response_model=RenderJobAcceptedResponse,
    status_code=202,
    summary="追加尾部文本",
    description=(
        "把新的尾部文本切成多个 segment 并追加到当前文档末尾。"
        "若同时提供 group 级 profile/binding，可自动创建或复用 group。"
    ),
    responses={**BAD_REQUEST_RESPONSE, **NOT_FOUND_RESPONSE, **CONFLICT_RESPONSE},
)
def append_segments(request: Request, body: AppendSegmentsRequest) -> RenderJobAcceptedResponse:
    return _build_render_job_service(request).create_append_job(body)


@router.post(
    "/segments/swap",
    response_model=RenderJobAcceptedResponse,
    status_code=202,
    summary="交换两个段的位置",
    description="交换两个现有段的顺序，并创建新的编辑作业。该操作可能只重排时间线而不重渲染段本身。",
    responses={**BAD_REQUEST_RESPONSE, **NOT_FOUND_RESPONSE, **CONFLICT_RESPONSE},
)
def swap_segments(request: Request, body: SwapSegmentsRequest) -> RenderJobAcceptedResponse:
    return _build_render_job_service(request).create_swap_segments_job(body)


@router.post(
    "/segments/move-range",
    response_model=RenderJobAcceptedResponse,
    status_code=202,
    summary="移动连续段区间",
    description="把一组连续段移动到指定目标段之后，并创建新的编辑作业。",
    responses={**BAD_REQUEST_RESPONSE, **NOT_FOUND_RESPONSE, **CONFLICT_RESPONSE},
)
def move_segment_range(request: Request, body: MoveSegmentRangeRequest) -> RenderJobAcceptedResponse:
    return _build_render_job_service(request).create_move_range_job(body)


@router.post(
    "/segments/reorder",
    response_model=RenderJobAcceptedResponse,
    status_code=202,
    summary="按完整顺序重排段列表",
    description="按传入的完整 segment ID 顺序重排当前文档，并创建新的编辑作业。",
    responses={**BAD_REQUEST_RESPONSE, **NOT_FOUND_RESPONSE, **CONFLICT_RESPONSE},
)
def reorder_segments(request: Request, body: ReorderSegmentsRequest) -> RenderJobAcceptedResponse:
    return _build_render_job_service(request).create_reorder_segments_job(body)


@router.post(
    "/segments/split",
    response_model=RenderJobAcceptedResponse,
    status_code=202,
    summary="拆分单个段",
    description="把一个现有段拆成左右两个新段，并提交为新的 document version。",
    responses={**BAD_REQUEST_RESPONSE, **NOT_FOUND_RESPONSE, **CONFLICT_RESPONSE},
)
def split_segment(request: Request, body: SplitSegmentRequest) -> RenderJobAcceptedResponse:
    return _build_render_job_service(request).create_split_segment_job(body)


@router.post(
    "/segments/merge",
    response_model=RenderJobAcceptedResponse,
    status_code=202,
    summary="合并相邻段",
    description="把两个目标段合并为一个新段，并创建新的异步编辑作业。",
    responses={**BAD_REQUEST_RESPONSE, **NOT_FOUND_RESPONSE, **CONFLICT_RESPONSE},
)
def merge_segments(request: Request, body: MergeSegmentsRequest) -> RenderJobAcceptedResponse:
    return _build_render_job_service(request).create_merge_segments_job(body)


@router.delete(
    "/segments/{segment_id}",
    response_model=RenderJobAcceptedResponse,
    status_code=202,
    summary="删除段",
    description="删除一个现有段并创建新的编辑作业。",
    responses={**NOT_FOUND_RESPONSE, **CONFLICT_RESPONSE},
)
def delete_segment(request: Request, segment_id: str) -> RenderJobAcceptedResponse:
    return _build_render_job_service(request).create_delete_segment_job(segment_id)


@router.get(
    "/edges",
    response_model=EdgeListResponse,
    summary="分页列出边",
    description="按左侧段顺序分页返回当前 head snapshot 中的边列表。",
    responses=NOT_FOUND_RESPONSE,
)
def list_edges(
    request: Request,
    limit: int = Query(default=1000, ge=1, le=1000, description="分页大小，最大 1000。"),
    cursor: int | None = Query(default=None, description="上一页最后一条边左侧段的 `order_key`。"),
) -> EdgeListResponse:
    service = _build_readonly_render_job_service(request)
    snapshot = service.get_head_snapshot()
    items = [item.model_dump(mode="json") for item in service.list_edges(limit=limit, cursor=cursor)]
    segment_order_by_id = {segment.segment_id: segment.order_key for segment in snapshot.segments}
    next_cursor = None
    if len(items) == limit and items:
        next_cursor = segment_order_by_id.get(items[-1]["left_segment_id"])
    return EdgeListResponse(
        document_id=snapshot.document_id,
        document_version=snapshot.document_version,
        items=items,
        next_cursor=next_cursor,
    )


@router.patch(
    "/edges/{edge_id}/config",
    response_model=ConfigurationCommitResponse,
    summary="仅提交边参数",
    description="修改段间停顿或边界策略，但不立即触发重推理。",
    responses={**BAD_REQUEST_RESPONSE, **NOT_FOUND_RESPONSE, **CONFLICT_RESPONSE},
)
def commit_edge_config(request: Request, edge_id: str, body: UpdateEdgeRequest) -> ConfigurationCommitResponse:
    return _build_render_job_service(request).commit_update_edge(edge_id, body)


@router.patch(
    "/edges/{edge_id}",
    response_model=RenderJobAcceptedResponse,
    status_code=202,
    summary="更新边参数",
    description="修改段间停顿或边界策略，并创建新的异步编辑作业。",
    responses={**BAD_REQUEST_RESPONSE, **NOT_FOUND_RESPONSE, **CONFLICT_RESPONSE},
)
def patch_edge(request: Request, edge_id: str, body: UpdateEdgeRequest) -> RenderJobAcceptedResponse:
    return _build_render_job_service(request).create_update_edge_job(edge_id, body)


@router.patch(
    "/session/render-profile/config",
    response_model=ConfigurationCommitResponse,
    summary="仅提交会话级渲染配置",
    description="创建新的 session-scope render profile 并持久化，但不立即触发重推理。",
    responses={**BAD_REQUEST_RESPONSE, **NOT_FOUND_RESPONSE, **CONFLICT_RESPONSE},
)
def commit_session_render_profile(request: Request, body: RenderProfilePatchRequest) -> ConfigurationCommitResponse:
    return _build_render_job_service(request).commit_patch_session_render_profile(body)


@router.patch(
    "/session/render-profile",
    response_model=RenderJobAcceptedResponse,
    status_code=202,
    summary="更新会话级渲染配置",
    description="创建新的 session-scope render profile，并让后续解析结果以该配置作为默认值。",
    responses={**BAD_REQUEST_RESPONSE, **NOT_FOUND_RESPONSE, **CONFLICT_RESPONSE},
)
def patch_session_render_profile(request: Request, body: RenderProfilePatchRequest) -> RenderJobAcceptedResponse:
    return _build_render_job_service(request).create_patch_session_render_profile_job(body)


@router.patch(
    "/session/voice-binding/config",
    response_model=ConfigurationCommitResponse,
    summary="仅提交会话级音色绑定",
    description="创建新的 session-scope voice/model binding 并持久化，但不立即触发重推理。",
    responses={**BAD_REQUEST_RESPONSE, **NOT_FOUND_RESPONSE, **CONFLICT_RESPONSE},
)
def commit_session_voice_binding(request: Request, body: VoiceBindingPatchRequest) -> ConfigurationCommitResponse:
    return _build_render_job_service(request).commit_patch_session_voice_binding(body)


@router.patch(
    "/session/voice-binding",
    response_model=RenderJobAcceptedResponse,
    status_code=202,
    summary="更新会话级音色绑定",
    description="创建新的 session-scope voice/model binding，并作为后续段的默认绑定。",
    responses={**BAD_REQUEST_RESPONSE, **NOT_FOUND_RESPONSE, **CONFLICT_RESPONSE},
)
def patch_session_voice_binding(request: Request, body: VoiceBindingPatchRequest) -> RenderJobAcceptedResponse:
    return _build_render_job_service(request).create_patch_session_voice_binding_job(body)


@router.patch(
    "/groups/{group_id}/render-profile",
    response_model=RenderJobAcceptedResponse,
    status_code=202,
    summary="更新组级渲染配置",
    description="为指定 group 创建新的 render profile，并让组内段继承该 profile。",
    responses={**BAD_REQUEST_RESPONSE, **NOT_FOUND_RESPONSE, **CONFLICT_RESPONSE},
)
def patch_group_render_profile(
    request: Request,
    group_id: str,
    body: RenderProfilePatchRequest,
) -> RenderJobAcceptedResponse:
    return _build_render_job_service(request).create_patch_group_render_profile_job(group_id, body)


@router.patch(
    "/groups/{group_id}/voice-binding",
    response_model=RenderJobAcceptedResponse,
    status_code=202,
    summary="更新组级音色绑定",
    description="为指定 group 创建新的 voice/model binding，并让组内段继承该绑定。",
    responses={**BAD_REQUEST_RESPONSE, **NOT_FOUND_RESPONSE, **CONFLICT_RESPONSE},
)
def patch_group_voice_binding(
    request: Request,
    group_id: str,
    body: VoiceBindingPatchRequest,
) -> RenderJobAcceptedResponse:
    return _build_render_job_service(request).create_patch_group_voice_binding_job(group_id, body)


@router.patch(
    "/segments/{segment_id}/render-profile/config",
    response_model=ConfigurationCommitResponse,
    summary="仅提交段级渲染配置",
    description="为单个段创建新的 render profile 并持久化，但不立即触发重推理。",
    responses={**BAD_REQUEST_RESPONSE, **NOT_FOUND_RESPONSE, **CONFLICT_RESPONSE},
)
def commit_segment_render_profile(
    request: Request,
    segment_id: str,
    body: RenderProfilePatchRequest,
) -> ConfigurationCommitResponse:
    return _build_render_job_service(request).commit_patch_segment_render_profile(segment_id, body)


@router.patch(
    "/segments/{segment_id}/render-profile",
    response_model=RenderJobAcceptedResponse,
    status_code=202,
    summary="更新段级渲染配置",
    description="为单个段创建新的 render profile，并触发必要的重渲染。",
    responses={**BAD_REQUEST_RESPONSE, **NOT_FOUND_RESPONSE, **CONFLICT_RESPONSE},
)
def patch_segment_render_profile(
    request: Request,
    segment_id: str,
    body: RenderProfilePatchRequest,
) -> RenderJobAcceptedResponse:
    return _build_render_job_service(request).create_patch_segment_render_profile_job(segment_id, body)


@router.patch(
    "/segments/{segment_id}/voice-binding/config",
    response_model=ConfigurationCommitResponse,
    summary="仅提交段级音色绑定",
    description="为单个段创建新的 voice/model binding 并持久化，但不立即触发重推理。",
    responses={**BAD_REQUEST_RESPONSE, **NOT_FOUND_RESPONSE, **CONFLICT_RESPONSE},
)
def commit_segment_voice_binding(
    request: Request,
    segment_id: str,
    body: VoiceBindingPatchRequest,
) -> ConfigurationCommitResponse:
    return _build_render_job_service(request).commit_patch_segment_voice_binding(segment_id, body)


@router.patch(
    "/segments/{segment_id}/voice-binding",
    response_model=RenderJobAcceptedResponse,
    status_code=202,
    summary="更新段级音色绑定",
    description="为单个段创建新的 voice/model binding，并触发必要的重渲染。",
    responses={**BAD_REQUEST_RESPONSE, **NOT_FOUND_RESPONSE, **CONFLICT_RESPONSE},
)
def patch_segment_voice_binding(
    request: Request,
    segment_id: str,
    body: VoiceBindingPatchRequest,
) -> RenderJobAcceptedResponse:
    return _build_render_job_service(request).create_patch_segment_voice_binding_job(segment_id, body)


@router.patch(
    "/segments/render-profile-batch/config",
    response_model=ConfigurationCommitResponse,
    summary="仅提交批量段级渲染配置",
    description="对目标段批量绑定新的 render profile 并持久化，但不立即触发重推理。",
    responses={**BAD_REQUEST_RESPONSE, **NOT_FOUND_RESPONSE, **CONFLICT_RESPONSE},
)
def commit_segments_render_profile_batch(
    request: Request,
    body: SegmentBatchRenderProfilePatchRequest,
) -> ConfigurationCommitResponse:
    return _build_render_job_service(request).commit_patch_segments_render_profile_batch(body)


@router.patch(
    "/segments/render-profile-batch",
    response_model=RenderJobAcceptedResponse,
    status_code=202,
    summary="批量更新段级渲染配置",
    description="对一组目标段批量创建并绑定同一个新的 render profile。",
    responses={**BAD_REQUEST_RESPONSE, **NOT_FOUND_RESPONSE, **CONFLICT_RESPONSE},
)
def patch_segments_render_profile_batch(
    request: Request,
    body: SegmentBatchRenderProfilePatchRequest,
) -> RenderJobAcceptedResponse:
    return _build_render_job_service(request).create_patch_segments_render_profile_batch_job(body)


@router.patch(
    "/segments/voice-binding-batch/config",
    response_model=ConfigurationCommitResponse,
    summary="仅提交批量段级音色绑定",
    description="对目标段批量绑定新的 voice/model binding 并持久化，但不立即触发重推理。",
    responses={**BAD_REQUEST_RESPONSE, **NOT_FOUND_RESPONSE, **CONFLICT_RESPONSE},
)
def commit_segments_voice_binding_batch(
    request: Request,
    body: SegmentBatchVoiceBindingPatchRequest,
) -> ConfigurationCommitResponse:
    return _build_render_job_service(request).commit_patch_segments_voice_binding_batch(body)


@router.patch(
    "/segments/voice-binding-batch",
    response_model=RenderJobAcceptedResponse,
    status_code=202,
    summary="批量更新段级音色绑定",
    description="对一组目标段批量创建并绑定同一个新的 voice/model binding。",
    responses={**BAD_REQUEST_RESPONSE, **NOT_FOUND_RESPONSE, **CONFLICT_RESPONSE},
)
def patch_segments_voice_binding_batch(
    request: Request,
    body: SegmentBatchVoiceBindingPatchRequest,
) -> RenderJobAcceptedResponse:
    return _build_render_job_service(request).create_patch_segments_voice_binding_batch_job(body)


@router.patch(
    "/segments/{segment_id}",
    response_model=RenderJobAcceptedResponse,
    status_code=202,
    summary="更新段文本 patch 或推理覆盖项",
    description="修改单个段的结构化文本 patch、语言或旧版 inference_override，并触发新的编辑作业。",
    responses={**BAD_REQUEST_RESPONSE, **NOT_FOUND_RESPONSE, **CONFLICT_RESPONSE},
)
def patch_segment(request: Request, segment_id: str, body: UpdateSegmentRequest) -> RenderJobAcceptedResponse:
    return _build_render_job_service(request).create_update_segment_job(segment_id, body)


@router.post(
    "/segments/{segment_id}/rerender",
    response_model=RenderJobAcceptedResponse,
    status_code=202,
    summary="重推理单个段",
    description="基于当前 head snapshot 已提交的配置，重新渲染指定段。",
    responses={**NOT_FOUND_RESPONSE, **CONFLICT_RESPONSE},
)
def rerender_segment(request: Request, segment_id: str) -> RenderJobAcceptedResponse:
    return _build_render_job_service(request).create_rerender_segment_job(segment_id)


@router.post(
    "/exports",
    response_model=ExportJobAcceptedResponse,
    status_code=202,
    summary="创建统一导出作业",
    description=(
        "统一导出指定 `document_version` 的正式音频与可选字幕。"
        "前端应优先调用该接口，而不是分别调用分段导出和整条导出接口。"
    ),
    responses={**BAD_REQUEST_RESPONSE, **NOT_FOUND_RESPONSE},
)
def create_export(request: Request, body: ExportRequest) -> ExportJobAcceptedResponse:
    return _build_export_service(request).create_export_job(body)


@router.post(
    "/exports/segments",
    response_model=ExportJobAcceptedResponse,
    status_code=202,
    summary="创建分段导出作业",
    description=(
        "导出指定 `document_version` 的分段音频。"
        "该接口与 composition 导出完全独立，不会隐式触发整条音频导出。"
    ),
    responses={**BAD_REQUEST_RESPONSE, **NOT_FOUND_RESPONSE},
)
def create_segment_export(request: Request, body: SegmentExportRequest) -> ExportJobAcceptedResponse:
    return _build_export_service(request).create_segment_export_job(body)


@router.post(
    "/exports/composition",
    response_model=ExportJobAcceptedResponse,
    status_code=202,
    summary="创建整条音频导出作业",
    description=(
        "导出指定 `document_version` 的整条拼接音频。"
        "只有在该导出成功后，兼容接口 `/composition` 才会对当前版本返回 200。"
    ),
    responses={**BAD_REQUEST_RESPONSE, **NOT_FOUND_RESPONSE},
)
def create_composition_export(request: Request, body: CompositionExportRequest) -> ExportJobAcceptedResponse:
    return _build_export_service(request).create_composition_export_job(body)


@router.get(
    "/exports/{export_job_id}",
    response_model=ExportJobResponse,
    summary="查询导出作业",
    description="读取单个 export job 的当前状态、进度、输出清单和最终目标目录。",
    responses=NOT_FOUND_RESPONSE,
)
def get_export_job(request: Request, export_job_id: str) -> ExportJobResponse:
    job = _build_export_service(request).get_job(export_job_id)
    if job is None:
        raise EditSessionNotFoundError(f"Export job '{export_job_id}' not found.")
    return job


@router.get(
    "/exports/{export_job_id}/events",
    summary="订阅导出作业事件流",
    description=(
        "以 SSE 形式输出导出作业状态变化和进度事件。"
        "终态时会发送 `export_completed` 或最后一条 `job_state_changed` 后关闭连接。"
    ),
    responses=NOT_FOUND_RESPONSE,
)
def stream_export_job_events(request: Request, export_job_id: str) -> StreamingResponse:
    export_service = _build_export_service(request)
    current_job = export_service.get_job(export_job_id)
    stored_job = request.app.state.edit_session_repository.get_export_job(export_job_id)
    if current_job is None and stored_job is None:
        raise EditSessionNotFoundError(f"Export job '{export_job_id}' not found.")

    subscriber = export_service.subscribe(export_job_id)

    def event_stream():
        try:
            if current_job is None and stored_job is not None:
                payload = stored_job.model_dump(mode="json")
                yield _encode_sse_event("job_state_changed", payload)
                if payload.get("status") in {"completed", "failed"}:
                    return
            while True:
                try:
                    envelope = subscriber.get(timeout=15)
                    event_type = envelope.get("event", "job_state_changed")
                    payload = envelope.get("data", {})
                    yield _encode_sse_event(event_type, payload)
                    if _should_close_export_event_stream(event_type, payload):
                        return
                except queue.Empty:
                    yield ": keep-alive\n\n"
        finally:
            export_service.unsubscribe(export_job_id, subscriber)

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.get(
    "/composition",
    response_model=CompositionResponse,
    summary="兼容：读取整条音频",
    description=(
        "兼容旧接口。若当前版本已有成功导出的 composition 资产则返回该音频；"
        "若尚未导出，则返回 404。新前端应优先使用 `/timeline`。"
    ),
    responses=NOT_FOUND_RESPONSE,
)
def get_composition(request: Request) -> CompositionResponse:
    return _build_readonly_render_job_service(request).get_composition_response()


@router.get(
    "/playback-map",
    response_model=PlaybackMapResponse,
    summary="兼容：读取播放映射",
    description="兼容旧接口。返回由 `TimelineManifest` 派生的 playback-map 视图，供旧测试或调试使用。",
)
def get_playback_map(request: Request) -> PlaybackMapResponse:
    return _build_readonly_render_job_service(request).get_playback_map_response()


@router.post(
    "/standardization-preview",
    response_model=StandardizationPreviewResponse,
    summary="预览文本标准化结果",
    description="按后端权威标准化器切段并返回 stem/display_text/terminal capsule/语言元数据预览，不写入正式会话。",
    responses=BAD_REQUEST_RESPONSE,
)
def get_standardization_preview(
    request: Request,
    body: StandardizationPreviewRequest,
) -> StandardizationPreviewResponse:
    return _build_readonly_render_job_service(request).get_standardization_preview_response(body)


@router.get(
    "/preview",
    response_model=PreviewResponse,
    summary="创建预览音频",
    description="为单个 segment、edge 或 block 生成一个短期可访问的预览资源，并返回带过期时间的音频地址。",
    responses={**BAD_REQUEST_RESPONSE, **NOT_FOUND_RESPONSE},
)
def get_preview(
    request: Request,
    segment_id: str | None = Query(default=None, description="要预览的段 ID。"),
    edge_id: str | None = Query(default=None, description="要预览的边 ID。"),
    block_id: str | None = Query(default=None, description="要预览的 block ID。"),
) -> PreviewResponse:
    body = PreviewRequest(segment_id=segment_id, edge_id=edge_id, block_id=block_id)
    return _build_readonly_render_job_service(request).get_preview_response(body)


@router.get(
    "/assets/compositions/{composition_manifest_id}/audio",
    summary="下载 composition 音频",
    description="读取一个正式保存的 composition wav 资产，支持 Range 请求。",
    responses=NOT_FOUND_RESPONSE,
)
def get_composition_audio(
    request: Request,
    composition_manifest_id: str,
    download: bool = Query(default=False, description="为 true 时使用附件下载响应头。"),
) -> Response:
    descriptor = _build_formal_audio_descriptor(
        request,
        asset_id=composition_manifest_id,
        asset_path=request.app.state.edit_asset_store.composition_asset_path(composition_manifest_id),
    )
    return _stream_audio_asset(
        request,
        asset_path=request.app.state.edit_asset_store.composition_asset_path(composition_manifest_id),
        etag=descriptor.etag,
        download=download,
    )


@router.get(
    "/assets/previews/{preview_asset_id}/audio",
    summary="下载 preview 音频",
    description="读取短期有效的 preview wav 资产；过期后会返回 410。",
    responses={**NOT_FOUND_RESPONSE, **GONE_RESPONSE},
)
def get_preview_audio(
    request: Request,
    preview_asset_id: str,
    download: bool = Query(default=False, description="为 true 时使用附件下载响应头。"),
) -> Response:
    try:
        record = request.app.state.edit_asset_store.get_preview_asset_record(preview_asset_id)
    except FileNotFoundError as exc:
        raise AssetNotFoundError(f"Preview asset '{preview_asset_id}' not found.") from exc
    descriptor = _build_audio_delivery_service().build_descriptor(
        asset_id=preview_asset_id,
        audio_url=str(request.url.path),
        asset_path=record.asset_path,
        sample_rate=request.app.state.edit_asset_store.load_wav_asset(record.asset_path)[0],
        expires_at=record.expires_at,
    )
    return _stream_audio_asset(
        request,
        asset_path=record.asset_path,
        etag=descriptor.etag,
        expires_at=descriptor.expires_at,
        download=download,
    )


@router.get(
    "/assets/segments/{render_asset_id}",
    response_model=SegmentAssetResponse,
    summary="读取段资产元信息",
    description="返回 segment 正式音频资产的元信息和音频地址。",
    responses=NOT_FOUND_RESPONSE,
)
def get_segment_asset(request: Request, render_asset_id: str) -> SegmentAssetResponse:
    return _build_readonly_render_job_service(request).get_segment_asset_response(render_asset_id)


@router.get(
    "/assets/segments/{render_asset_id}/audio",
    summary="下载段音频",
    description="读取一个正式保存的 segment wav 资产，支持 Range 请求。",
    responses=NOT_FOUND_RESPONSE,
)
def get_segment_audio(
    request: Request,
    render_asset_id: str,
    download: bool = Query(default=False, description="为 true 时使用附件下载响应头。"),
) -> Response:
    response = _build_readonly_render_job_service(request).get_segment_asset_response(render_asset_id)
    return _stream_audio_asset(
        request,
        asset_path=request.app.state.edit_asset_store.segment_asset_path(render_asset_id),
        etag=response.audio_delivery.etag,
        download=download,
    )


@router.get(
    "/assets/boundaries/{boundary_asset_id}",
    response_model=BoundaryAssetResponse,
    summary="读取边界资产元信息",
    description="返回 boundary 正式音频资产的元信息和音频地址。",
    responses=NOT_FOUND_RESPONSE,
)
def get_boundary_asset(request: Request, boundary_asset_id: str) -> BoundaryAssetResponse:
    return _build_readonly_render_job_service(request).get_boundary_asset_response(boundary_asset_id)


@router.get(
    "/assets/boundaries/{boundary_asset_id}/audio",
    summary="下载边界音频",
    description="读取一个正式保存的 boundary wav 资产，支持 Range 请求。",
    responses=NOT_FOUND_RESPONSE,
)
def get_boundary_audio(
    request: Request,
    boundary_asset_id: str,
    download: bool = Query(default=False, description="为 true 时使用附件下载响应头。"),
) -> Response:
    response = _build_readonly_render_job_service(request).get_boundary_asset_response(boundary_asset_id)
    return _stream_audio_asset(
        request,
        asset_path=request.app.state.edit_asset_store.boundary_asset_path(boundary_asset_id),
        etag=response.audio_delivery.etag,
        download=download,
    )


@router.get(
    "/assets/blocks/{block_asset_id}/audio",
    summary="下载 block 音频",
    description="读取一个正式保存的 block wav 资产，供前端按 timeline 分块播放。",
    responses=NOT_FOUND_RESPONSE,
)
def get_block_audio(
    request: Request,
    block_asset_id: str,
    download: bool = Query(default=False, description="为 true 时使用附件下载响应头。"),
) -> Response:
    descriptor = _build_formal_audio_descriptor(
        request,
        asset_id=block_asset_id,
        asset_path=request.app.state.edit_asset_store.block_asset_path(block_asset_id),
    )
    return _stream_audio_asset(
        request,
        asset_path=request.app.state.edit_asset_store.block_asset_path(block_asset_id),
        etag=descriptor.etag,
        download=download,
    )


@router.get(
    "/render-jobs/{job_id}",
    response_model=RenderJobResponse,
    summary="查询渲染作业",
    description="读取单个 render job 的当前状态、进度、检查点和结果版本。",
    responses=NOT_FOUND_RESPONSE,
)
def get_render_job(request: Request, job_id: str) -> RenderJobResponse:
    job = _build_readonly_render_job_service(request).get_job(job_id)
    if job is None:
        raise EditSessionNotFoundError(f"Render job '{job_id}' not found.")
    return job


@router.get(
    "/render-jobs/{job_id}/events",
    summary="订阅渲染作业事件流",
    description=(
        "以 SSE 形式输出渲染作业的状态变更、段完成、block 完成、checkpoint 等事件。"
        "作业进入完成、失败、暂停或 cancel partial 终态后会关闭连接。"
    ),
    responses=NOT_FOUND_RESPONSE,
)
def stream_render_job_events(request: Request, job_id: str) -> StreamingResponse:
    runtime = request.app.state.edit_session_runtime
    repository = request.app.state.edit_session_repository
    current_job = runtime.get_job(job_id)
    stored_job = repository.get_render_job(job_id)
    if current_job is None and stored_job is None:
        raise EditSessionNotFoundError(f"Render job '{job_id}' not found.")

    subscriber = runtime.subscribe(job_id)

    def event_stream():
        try:
            if current_job is None and stored_job is not None:
                payload = stored_job.model_dump(mode="json")
                yield _encode_sse_event("job_state_changed", payload)
                if _is_terminal_job_payload(stored_job.model_dump(mode="json")):
                    return
            while True:
                try:
                    envelope = subscriber.get(timeout=15)
                    event_type = envelope.get("event", "job_state_changed")
                    payload = envelope.get("data", {})
                    yield _encode_sse_event(event_type, payload)
                    if _should_close_live_event_stream(event_type, payload):
                        return
                except queue.Empty:
                    yield ": keep-alive\n\n"
        finally:
            runtime.unsubscribe(job_id, subscriber)

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.post(
    "/render-jobs/{job_id}/cancel",
    response_model=RenderJobResponse,
    summary="请求取消渲染作业",
    description="请求当前作业在安全边界处取消。若作业已开始执行，通常会在当前段完成后以 `cancelled_partial` 结束。",
    responses=NOT_FOUND_RESPONSE,
)
def cancel_render_job(request: Request, job_id: str) -> RenderJobResponse:
    service = _build_readonly_render_job_service(request)
    job = service.get_job(job_id)
    if job is None:
        raise EditSessionNotFoundError(f"Render job '{job_id}' not found.")
    service.cancel_job(job_id)
    updated_job = service.get_job(job_id)
    assert updated_job is not None
    return updated_job


@router.post(
    "/render-jobs/{job_id}/pause",
    response_model=RenderJobResponse,
    summary="请求暂停渲染作业",
    description="请求当前作业在安全边界处暂停。成功暂停后可通过 resume 接口恢复。",
    responses=NOT_FOUND_RESPONSE,
)
def pause_render_job(request: Request, job_id: str) -> RenderJobResponse:
    service = _build_readonly_render_job_service(request)
    job = service.get_job(job_id)
    if job is None:
        raise EditSessionNotFoundError(f"Render job '{job_id}' not found.")
    service.pause_job(job_id)
    updated_job = service.get_job(job_id)
    assert updated_job is not None
    return updated_job


@router.post(
    "/render-jobs/{job_id}/resume",
    response_model=RenderJobAcceptedResponse,
    status_code=202,
    summary="恢复暂停作业",
    description="从当前可恢复 checkpoint 创建一个新的 resume 作业，继续完成剩余段的渲染。",
    responses={**NOT_FOUND_RESPONSE, **CONFLICT_RESPONSE},
)
def resume_render_job(request: Request, job_id: str) -> RenderJobAcceptedResponse:
    service = _build_render_job_service(request)
    return service.create_resume_job(job_id)
