from __future__ import annotations

import json
from pathlib import Path
import queue

from fastapi import APIRouter, Request
from fastapi.responses import Response, StreamingResponse

from backend.app.core.exceptions import AssetNotFoundError, EditSessionNotFoundError
from backend.app.inference.editable_gateway import EditableInferenceGateway
from backend.app.repositories.voice_repository import VoiceRepository
from backend.app.schemas.edit_session import (
    AppendSegmentsRequest,
    BaselineSnapshotResponse,
    BoundaryAssetResponse,
    CompositionResponse,
    CreateSegmentRequest,
    CurrentCheckpointResponse,
    EdgeListResponse,
    EditSessionSnapshotResponse,
    InitializeEditSessionRequest,
    PlaybackMapResponse,
    PreviewRequest,
    PreviewResponse,
    RenderProfilePatchRequest,
    RenderJobAcceptedResponse,
    RenderJobResponse,
    SegmentAssetResponse,
    SegmentListResponse,
    SwapSegmentsRequest,
    TimelineManifest,
    UpdateEdgeRequest,
    UpdateSegmentRequest,
    VoiceBindingPatchRequest,
)
from backend.app.services.audio_delivery_service import AudioDeliveryService
from backend.app.services.edit_session_service import EditSessionService
from backend.app.services.render_job_service import RenderJobService
from backend.app.services.voice_service import VoiceService


router = APIRouter(prefix="/v1/edit-session", tags=["edit-session"])


class _UnavailableEditableBackend:
    def build_reference_context(self, request):
        raise RuntimeError("Editable inference backend is unavailable for read-only operations.")

    def render_segment_base(self, segment, context):
        raise RuntimeError("Editable inference backend is unavailable for read-only operations.")

    def render_boundary_asset(self, left_asset, right_asset, edge, context):
        raise RuntimeError("Editable inference backend is unavailable for read-only operations.")


def _build_voice_service(request: Request) -> VoiceService:
    settings = request.app.state.settings
    repository = VoiceRepository(config_path=settings.voices_config_path, settings=settings)
    return VoiceService(repository)


def _resolve_project_path(project_root: Path, raw_path: str) -> str:
    path = Path(raw_path)
    if path.is_absolute():
        return str(path)
    return str((project_root / path).resolve())


def _build_editable_gateway(request: Request, *, voice_id: str) -> EditableInferenceGateway:
    existing = getattr(request.app.state, "editable_inference_gateway", None)
    if existing is not None:
        return existing

    settings = request.app.state.settings
    voice_service = _build_voice_service(request)
    voice = voice_service.get_voice(voice_id)
    cache: dict[tuple[str, str], EditableInferenceGateway] = getattr(
        request.app.state,
        "editable_inference_gateway_cache",
        {},
    )
    cache_key = (voice.gpt_path, voice.sovits_path)
    if cache_key not in cache:
        from backend.app.inference.pytorch_optimized import GPTSoVITSOptimizedInference

        backend = GPTSoVITSOptimizedInference(
            _resolve_project_path(settings.project_root, voice.gpt_path),
            _resolve_project_path(settings.project_root, voice.sovits_path),
            settings.cnhubert_base_path,
            settings.bert_path,
        )
        cache[cache_key] = EditableInferenceGateway(backend)
        request.app.state.editable_inference_gateway_cache = cache
    return cache[cache_key]


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
        session_service=_build_edit_session_service(request),
        gateway=_build_editable_gateway(request, voice_id=voice_id),
        audio_delivery_service=AudioDeliveryService(),
    )


def _build_readonly_render_job_service(request: Request) -> RenderJobService:
    gateway = getattr(request.app.state, "editable_inference_gateway", None)
    if gateway is None:
        gateway = EditableInferenceGateway(_UnavailableEditableBackend())
    return RenderJobService(
        repository=request.app.state.edit_session_repository,
        asset_store=request.app.state.edit_asset_store,
        runtime=request.app.state.edit_session_runtime,
        session_service=_build_edit_session_service(request),
        gateway=gateway,
        audio_delivery_service=AudioDeliveryService(),
        run_jobs_in_background=False,
    )


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


@router.post("/initialize", response_model=RenderJobAcceptedResponse, status_code=202)
def initialize_edit_session(request: Request, body: InitializeEditSessionRequest) -> RenderJobAcceptedResponse:
    service = _build_render_job_service(request, voice_id=body.voice_id)
    return service.create_initialize_job(body)


@router.post("/render-jobs", response_model=RenderJobAcceptedResponse, status_code=202)
def create_render_job(request: Request, body: InitializeEditSessionRequest) -> RenderJobAcceptedResponse:
    service = _build_render_job_service(request, voice_id=body.voice_id)
    return service.create_initialize_job(body)


@router.get("/snapshot", response_model=EditSessionSnapshotResponse)
def get_snapshot(request: Request) -> EditSessionSnapshotResponse:
    return _build_edit_session_service(request).get_snapshot()


@router.get("/baseline", response_model=BaselineSnapshotResponse)
def get_baseline(request: Request) -> BaselineSnapshotResponse:
    return _build_edit_session_service(request).get_baseline()


@router.get("/timeline", response_model=TimelineManifest)
def get_timeline(request: Request) -> TimelineManifest:
    return _build_edit_session_service(request).get_timeline()


@router.get("/checkpoints/current", response_model=CurrentCheckpointResponse)
def get_current_checkpoint(request: Request) -> CurrentCheckpointResponse:
    return _build_edit_session_service(request).get_current_checkpoint()


@router.delete("", status_code=204)
def delete_session(request: Request) -> Response:
    _build_edit_session_service(request).delete_session()
    return Response(status_code=204)


@router.post("/restore-baseline", response_model=RenderJobAcceptedResponse, status_code=202)
def restore_baseline(request: Request) -> RenderJobAcceptedResponse:
    return _build_render_job_service(request).create_restore_baseline_job()


@router.get("/segments", response_model=SegmentListResponse)
def list_segments(request: Request, limit: int = 1000, cursor: int | None = None) -> SegmentListResponse:
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


@router.post("/segments", response_model=RenderJobAcceptedResponse, status_code=202)
def create_segment(request: Request, body: CreateSegmentRequest) -> RenderJobAcceptedResponse:
    return _build_render_job_service(request).create_insert_segment_job(body)


@router.post("/append", response_model=RenderJobAcceptedResponse, status_code=202)
def append_segments(request: Request, body: AppendSegmentsRequest) -> RenderJobAcceptedResponse:
    return _build_render_job_service(request).create_append_job(body)


@router.patch("/segments/{segment_id}", response_model=RenderJobAcceptedResponse, status_code=202)
def patch_segment(request: Request, segment_id: str, body: UpdateSegmentRequest) -> RenderJobAcceptedResponse:
    return _build_render_job_service(request).create_update_segment_job(segment_id, body)


@router.post("/segments/swap", response_model=RenderJobAcceptedResponse, status_code=202)
def swap_segments(request: Request, body: SwapSegmentsRequest) -> RenderJobAcceptedResponse:
    return _build_render_job_service(request).create_swap_segments_job(body)


@router.delete("/segments/{segment_id}", response_model=RenderJobAcceptedResponse, status_code=202)
def delete_segment(request: Request, segment_id: str) -> RenderJobAcceptedResponse:
    return _build_render_job_service(request).create_delete_segment_job(segment_id)


@router.get("/edges", response_model=EdgeListResponse)
def list_edges(request: Request, limit: int = 1000, cursor: int | None = None) -> EdgeListResponse:
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


@router.patch("/edges/{edge_id}", response_model=RenderJobAcceptedResponse, status_code=202)
def patch_edge(request: Request, edge_id: str, body: UpdateEdgeRequest) -> RenderJobAcceptedResponse:
    return _build_render_job_service(request).create_update_edge_job(edge_id, body)


@router.patch("/session/render-profile", response_model=RenderJobAcceptedResponse, status_code=202)
def patch_session_render_profile(request: Request, body: RenderProfilePatchRequest) -> RenderJobAcceptedResponse:
    return _build_render_job_service(request).create_patch_session_render_profile_job(body)


@router.patch("/session/voice-binding", response_model=RenderJobAcceptedResponse, status_code=202)
def patch_session_voice_binding(request: Request, body: VoiceBindingPatchRequest) -> RenderJobAcceptedResponse:
    return _build_render_job_service(request).create_patch_session_voice_binding_job(body)


@router.patch("/groups/{group_id}/render-profile", response_model=RenderJobAcceptedResponse, status_code=202)
def patch_group_render_profile(
    request: Request,
    group_id: str,
    body: RenderProfilePatchRequest,
) -> RenderJobAcceptedResponse:
    return _build_render_job_service(request).create_patch_group_render_profile_job(group_id, body)


@router.patch("/groups/{group_id}/voice-binding", response_model=RenderJobAcceptedResponse, status_code=202)
def patch_group_voice_binding(
    request: Request,
    group_id: str,
    body: VoiceBindingPatchRequest,
) -> RenderJobAcceptedResponse:
    return _build_render_job_service(request).create_patch_group_voice_binding_job(group_id, body)


@router.patch("/segments/{segment_id}/render-profile", response_model=RenderJobAcceptedResponse, status_code=202)
def patch_segment_render_profile(
    request: Request,
    segment_id: str,
    body: RenderProfilePatchRequest,
) -> RenderJobAcceptedResponse:
    return _build_render_job_service(request).create_patch_segment_render_profile_job(segment_id, body)


@router.patch("/segments/{segment_id}/voice-binding", response_model=RenderJobAcceptedResponse, status_code=202)
def patch_segment_voice_binding(
    request: Request,
    segment_id: str,
    body: VoiceBindingPatchRequest,
) -> RenderJobAcceptedResponse:
    return _build_render_job_service(request).create_patch_segment_voice_binding_job(segment_id, body)


@router.get("/composition", response_model=CompositionResponse)
def get_composition(request: Request) -> CompositionResponse:
    return _build_readonly_render_job_service(request).get_composition_response()


@router.get("/playback-map", response_model=PlaybackMapResponse)
def get_playback_map(request: Request) -> PlaybackMapResponse:
    return _build_readonly_render_job_service(request).get_playback_map_response()


@router.get("/preview", response_model=PreviewResponse)
def get_preview(
    request: Request,
    segment_id: str | None = None,
    edge_id: str | None = None,
    block_id: str | None = None,
) -> PreviewResponse:
    body = PreviewRequest(segment_id=segment_id, edge_id=edge_id, block_id=block_id)
    return _build_readonly_render_job_service(request).get_preview_response(body)


@router.get("/assets/compositions/{composition_manifest_id}/audio")
def get_composition_audio(request: Request, composition_manifest_id: str, download: bool = False) -> Response:
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


@router.get("/assets/previews/{preview_asset_id}/audio")
def get_preview_audio(request: Request, preview_asset_id: str, download: bool = False) -> Response:
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


@router.get("/assets/segments/{render_asset_id}", response_model=SegmentAssetResponse)
def get_segment_asset(request: Request, render_asset_id: str) -> SegmentAssetResponse:
    return _build_readonly_render_job_service(request).get_segment_asset_response(render_asset_id)


@router.get("/assets/segments/{render_asset_id}/audio")
def get_segment_audio(request: Request, render_asset_id: str, download: bool = False) -> Response:
    response = _build_readonly_render_job_service(request).get_segment_asset_response(render_asset_id)
    return _stream_audio_asset(
        request,
        asset_path=request.app.state.edit_asset_store.segment_asset_path(render_asset_id),
        etag=response.audio_delivery.etag,
        download=download,
    )


@router.get("/assets/boundaries/{boundary_asset_id}", response_model=BoundaryAssetResponse)
def get_boundary_asset(request: Request, boundary_asset_id: str) -> BoundaryAssetResponse:
    return _build_readonly_render_job_service(request).get_boundary_asset_response(boundary_asset_id)


@router.get("/assets/boundaries/{boundary_asset_id}/audio")
def get_boundary_audio(request: Request, boundary_asset_id: str, download: bool = False) -> Response:
    response = _build_readonly_render_job_service(request).get_boundary_asset_response(boundary_asset_id)
    return _stream_audio_asset(
        request,
        asset_path=request.app.state.edit_asset_store.boundary_asset_path(boundary_asset_id),
        etag=response.audio_delivery.etag,
        download=download,
    )


@router.get("/assets/blocks/{block_asset_id}/audio")
def get_block_audio(request: Request, block_asset_id: str, download: bool = False) -> Response:
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


@router.get("/render-jobs/{job_id}", response_model=RenderJobResponse)
def get_render_job(request: Request, job_id: str) -> RenderJobResponse:
    job = _build_readonly_render_job_service(request).get_job(job_id)
    if job is None:
        raise EditSessionNotFoundError(f"Render job '{job_id}' not found.")
    return job


@router.get("/render-jobs/{job_id}/events")
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


@router.post("/render-jobs/{job_id}/cancel", response_model=RenderJobResponse)
def cancel_render_job(request: Request, job_id: str) -> RenderJobResponse:
    service = _build_readonly_render_job_service(request)
    job = service.get_job(job_id)
    if job is None:
        raise EditSessionNotFoundError(f"Render job '{job_id}' not found.")
    service.cancel_job(job_id)
    updated_job = service.get_job(job_id)
    assert updated_job is not None
    return updated_job


@router.post("/render-jobs/{job_id}/pause", response_model=RenderJobResponse)
def pause_render_job(request: Request, job_id: str) -> RenderJobResponse:
    service = _build_readonly_render_job_service(request)
    job = service.get_job(job_id)
    if job is None:
        raise EditSessionNotFoundError(f"Render job '{job_id}' not found.")
    service.pause_job(job_id)
    updated_job = service.get_job(job_id)
    assert updated_job is not None
    return updated_job


@router.post("/render-jobs/{job_id}/resume", response_model=RenderJobAcceptedResponse, status_code=202)
def resume_render_job(request: Request, job_id: str) -> RenderJobAcceptedResponse:
    service = _build_render_job_service(request)
    return service.create_resume_job(job_id)
