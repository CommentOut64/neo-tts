from __future__ import annotations

import json
import queue

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from backend.app.schemas.inference import (
    CleanupResidualsResponse,
    ForcePauseResponse,
    InferenceParamsCacheResponse,
    InferenceParamsCacheUpsertRequest,
    InferenceProgressState,
)
from backend.app.services.inference_params_cache import InferenceParamsCacheStore
from backend.app.services.inference_residual_service import InferenceResidualService
from backend.app.services.inference_runtime import InferenceRuntimeController
from backend.app.services.synthesis_result_store import SynthesisResultStore


router = APIRouter(prefix="/v1/audio", tags=["tts"])


def _build_inference_runtime(request: Request) -> InferenceRuntimeController:
    existing = getattr(request.app.state, "inference_runtime", None)
    if existing is not None:
        return existing
    runtime = InferenceRuntimeController()
    request.app.state.inference_runtime = runtime
    return runtime


def _build_result_store(request: Request) -> SynthesisResultStore:
    existing = getattr(request.app.state, "synthesis_result_store", None)
    if existing is not None:
        return existing
    settings = request.app.state.settings
    store = SynthesisResultStore(
        project_root=settings.project_root,
        results_dir=settings.synthesis_results_dir,
    )
    request.app.state.synthesis_result_store = store
    return store


def _build_params_cache_store(request: Request) -> InferenceParamsCacheStore:
    existing = getattr(request.app.state, "inference_params_cache_store", None)
    if existing is not None:
        return existing
    settings = request.app.state.settings
    store = InferenceParamsCacheStore(
        project_root=settings.project_root,
        cache_file=settings.inference_params_cache_file,
    )
    request.app.state.inference_params_cache_store = store
    return store


def _build_inference_residual_service(request: Request) -> InferenceResidualService:
    return InferenceResidualService(
        settings=request.app.state.settings,
        runtime=_build_inference_runtime(request),
        result_store=_build_result_store(request),
    )


@router.get(
    "/inference/progress",
    response_model=InferenceProgressState,
    summary="读取当前推理进度",
    description="返回当前全局推理任务的快照状态；若空闲则返回 `idle`。",
)
def get_inference_progress(request: Request) -> InferenceProgressState:
    return _build_inference_runtime(request).snapshot()


@router.get(
    "/inference/progress/stream",
    summary="订阅推理进度事件流",
    description="以 SSE 形式持续输出当前推理进度事件；空闲时会发送 keep-alive 注释帧维持连接。",
)
def stream_inference_progress(request: Request) -> StreamingResponse:
    runtime = _build_inference_runtime(request)
    subscriber = runtime.subscribe()

    def event_stream():
        try:
            while True:
                try:
                    payload = subscriber.get(timeout=15)
                    yield _encode_sse_event("progress", payload)
                except queue.Empty:
                    # SSE 保活注释帧，避免中间层长连接超时。
                    yield ": keep-alive\n\n"
        finally:
            runtime.unsubscribe(subscriber)

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.post(
    "/inference/force-pause",
    response_model=ForcePauseResponse,
    summary="请求强制暂停推理",
    description="向当前活动推理任务发送强制暂停请求；该请求被接受后，任务会尽快进入 cancelling/cancelled 状态。",
)
def force_pause_inference(request: Request) -> ForcePauseResponse:
    runtime = _build_inference_runtime(request)
    accepted = runtime.request_force_pause(message="收到强制暂停请求，正在中断推理。")
    return ForcePauseResponse(accepted=accepted, state=runtime.snapshot())


@router.post(
    "/inference/cleanup-residuals",
    response_model=CleanupResidualsResponse,
    summary="清理推理残留",
    description="取消当前任务、清理临时参考音频目录和历史结果缓存，并在空闲时重置推理运行态。",
)
def cleanup_inference_residuals(request: Request) -> CleanupResidualsResponse:
    return _build_inference_residual_service(request).cleanup().to_response()


@router.get(
    "/inference/params-cache",
    response_model=InferenceParamsCacheResponse,
    summary="读取推理参数缓存",
    description="返回当前保存的推理参数缓存，用于前端恢复上次使用的表单状态。",
)
def get_inference_params_cache(request: Request) -> InferenceParamsCacheResponse:
    store = _build_params_cache_store(request)
    cached = store.load()
    if cached is None:
        return InferenceParamsCacheResponse(payload={}, updated_at=None)
    payload, updated_at = cached
    return InferenceParamsCacheResponse(payload=payload, updated_at=updated_at)


@router.put(
    "/inference/params-cache",
    response_model=InferenceParamsCacheResponse,
    summary="写入推理参数缓存",
    description="覆盖保存当前推理参数缓存，供前端下次进入页面时恢复使用。",
)
def put_inference_params_cache(
    request: Request,
    body: InferenceParamsCacheUpsertRequest,
) -> InferenceParamsCacheResponse:
    store = _build_params_cache_store(request)
    updated_at = store.save(body.payload)
    return InferenceParamsCacheResponse(payload=body.payload, updated_at=updated_at)


def _encode_sse_event(event: str, payload: dict) -> str:
    encoded_payload = json.dumps(payload, ensure_ascii=False)
    return f"event: {event}\ndata: {encoded_payload}\n\n"
