from __future__ import annotations

import asyncio
from contextlib import suppress
import json
from pathlib import Path
import queue
import time

from fastapi import APIRouter, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import Response, StreamingResponse
from pydantic import ValidationError

from backend.app.core.logging import get_logger
from backend.app.api.reference_audio_upload import (
    store_temporary_reference_audio,
    validate_reference_audio_filename,
)
from backend.app.inference.audio_processing import build_wav_bytes, float_audio_chunk_to_pcm16_bytes
from backend.app.inference.types import InferenceCancelledError
from backend.app.repositories.voice_repository import VoiceRepository
from backend.app.schemas.inference import (
    CleanupResidualsResponse,
    DeleteSynthesisResultResponse,
    ForcePauseResponse,
    InferenceParamsCacheResponse,
    InferenceParamsCacheUpsertRequest,
    InferenceProgressState,
)
from backend.app.schemas.tts import SpeechRequest
from backend.app.services.inference_params_cache import InferenceParamsCacheStore
from backend.app.services.inference_residual_service import InferenceResidualService
from backend.app.services.inference_runtime import InferenceRuntimeController
from backend.app.services.synthesis_result_store import SynthesisResultStore
from backend.app.services.tts_service import TtsService
from backend.app.services.voice_service import VoiceService
from backend.app.tts_registry.model_registry import ModelRegistry


router = APIRouter(prefix="/v1/audio", tags=["tts"])
tts_logger = get_logger("tts_router")


COMMON_ERROR_RESPONSES = {
    400: {"description": "请求参数不合法。"},
    404: {"description": "目标音色或结果不存在。"},
    409: {"description": "当前已有活动推理任务，或任务已被取消。"},
    422: {"description": "推理依赖的模型或资源文件缺失。"},
    500: {"description": "推理初始化或执行过程中出现未预期错误。"},
}


def _speech_request_properties(*, include_binary_file: bool) -> dict[str, dict]:
    properties: dict[str, dict] = {
        "input": {"type": "string", "description": "要合成的文本内容。"},
        "voice": {"type": "string", "description": "使用的音色 ID。", "default": "default"},
        "model": {"type": "string", "description": "模型标识。", "default": "gpt-sovits-v2"},
        "response_format": {"type": "string", "description": "响应格式；通常为 `wav`。", "default": "wav"},
        "speed": {"type": "number", "description": "可选的语速覆盖值。"},
        "top_k": {"type": "integer", "description": "可选的采样 top_k。"},
        "top_p": {"type": "number", "description": "可选的采样 top_p。"},
        "temperature": {"type": "number", "description": "可选的采样温度。"},
        "text_lang": {"type": "string", "description": "输入文本语言。", "default": "auto"},
        "text_split_method": {"type": "string", "description": "文本切分策略。", "default": "cut5"},
        "chunk_length": {"type": "integer", "description": "分块推理长度。", "default": 24},
        "history_window": {"type": "integer", "description": "跨 chunk 历史窗口大小。", "default": 4},
        "pause_length": {"type": "number", "description": "句间停顿时长覆盖值。"},
        "noise_scale": {"type": "number", "description": "可选的 noise scale。"},
        "sid": {"type": "integer", "description": "可选的说话人索引。"},
        "ref_text": {"type": "string", "description": "参考文本。"},
        "ref_lang": {"type": "string", "description": "参考文本语言。"},
    }
    if include_binary_file:
        properties["ref_audio_file"] = {
            "type": "string",
            "format": "binary",
            "description": "multipart/form-data 模式下上传的参考音频文件。",
        }
    else:
        properties["ref_audio"] = {
            "type": "string",
            "description": "JSON 模式下直接传入的参考音频路径。",
        }
    return properties


def _build_voice_service(request: Request) -> VoiceService:
    settings = request.app.state.settings
    repository = VoiceRepository(config_path=settings.voices_config_path, settings=settings)
    registry_root = settings.tts_registry_root or (settings.user_data_root / "tts-registry")
    return VoiceService(repository, ModelRegistry(registry_root))


def _build_inference_engine(request: Request) -> PyTorchInferenceEngine:
    from backend.app.inference.engine import PyTorchInferenceEngine
    from backend.app.inference.model_cache import PyTorchModelCache, build_model_cache_from_settings

    existing_engine = getattr(request.app.state, "inference_engine", None)
    if existing_engine is not None:
        return existing_engine

    settings = request.app.state.settings
    model_cache = getattr(request.app.state, "model_cache", None)
    if model_cache is None:
        model_cache = build_model_cache_from_settings(
            settings=settings,
            model_cache_cls=PyTorchModelCache,
        )
        request.app.state.model_cache = model_cache

    engine = PyTorchInferenceEngine(
        model_cache=model_cache,
        project_root=settings.project_root,
    )
    request.app.state.inference_engine = engine
    return engine


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


@router.post(
    "/speech",
    summary="执行文本转语音",
    description=(
        "发起一次 TTS 推理请求。支持 `application/json` 和 `multipart/form-data` 两种请求体。"
        "当 `response_format=wav` 时返回完整 wav 二进制，并在响应头中附带推理任务 ID；"
        "非 wav 模式下返回流式音频响应。"
    ),
    responses={
        200: {
            "description": "推理成功，返回音频数据。",
            "content": {
                "audio/wav": {"schema": {"type": "string", "format": "binary"}},
                "audio/mpeg": {"schema": {"type": "string", "format": "binary"}},
            },
        },
        **COMMON_ERROR_RESPONSES,
    },
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "application/json": {
                    "schema": {
                        "type": "object",
                        "required": ["input"],
                        "properties": _speech_request_properties(include_binary_file=False),
                    }
                },
                "multipart/form-data": {
                    "schema": {
                        "type": "object",
                        "required": ["input"],
                        "properties": _speech_request_properties(include_binary_file=True),
                    }
                },
            },
        }
    },
)
async def text_to_speech(request: Request) -> Response:
    request_started = time.perf_counter()
    tts_logger.info("收到 TTS 请求")
    payload, temporary_files, parse_metrics = await _parse_speech_request(request)
    tts_logger.info(
        "TTS 请求体解析完成 content_type={} elapsed_ms={:.2f}",
        request.headers.get("content-type", ""),
        parse_metrics["total_ms"],
    )
    runtime = _build_inference_runtime(request)
    task_id: str | None = None
    cleanup_after_return = True

    try:
        try:
            task_id = runtime.start_task(message=f"收到推理请求，voice={payload.voice}。")
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

        runtime.update_progress(
            task_id=task_id,
            status="preparing",
            progress=0.01,
            message="正在加载音色配置。",
        )

        voice_started = time.perf_counter()
        voice_service = _build_voice_service(request)
        voice_profile = voice_service.get_voice(payload.voice)
        tts_logger.debug(
            "音色配置加载完成 voice={} elapsed_ms={:.2f}",
            payload.voice,
            (time.perf_counter() - voice_started) * 1000,
        )

        prepare_started = time.perf_counter()
        tts_service = TtsService()
        prepared_request = tts_service.prepare_request(payload, voice_profile)
        tts_logger.debug(
            "推理请求组装完成 voice={} elapsed_ms={:.2f}",
            payload.voice,
            (time.perf_counter() - prepare_started) * 1000,
        )

        engine_started = time.perf_counter()
        inference_engine = _build_inference_engine(request)
        tts_logger.info(
            "推理引擎准备完成 voice={} elapsed_ms={:.2f}",
            payload.voice,
            (time.perf_counter() - engine_started) * 1000,
        )

        def should_cancel() -> bool:
            assert task_id is not None
            return runtime.should_cancel(task_id)

        def progress_callback(event: dict) -> None:
            assert task_id is not None
            status = event.get("status")
            progress = event.get("progress")
            message = event.get("message")
            current_segment = event.get("current_segment")
            total_segments = event.get("total_segments")
            runtime.update_progress(
                task_id=task_id,
                status=status if isinstance(status, str) else None,
                progress=float(progress) if isinstance(progress, (int, float)) else None,
                message=message if isinstance(message, str) else None,
                current_segment=current_segment if isinstance(current_segment, int) else None,
                total_segments=total_segments if isinstance(total_segments, int) else None,
            )

        sample_rate, stream = tts_service.synthesize_prepared_stream(
            prepared_request=prepared_request,
            inference_engine=inference_engine,
            progress_callback=progress_callback,
            should_cancel=should_cancel,
        )
        tts_logger.info(
            "推理流已创建 task_id={} sample_rate={} total_setup_ms={:.2f}",
            task_id,
            sample_rate,
            (time.perf_counter() - request_started) * 1000,
        )

        if prepared_request.response_format == "wav":
            def _consume_stream() -> list[bytes]:
                chunks: list[bytes] = []
                for chunk in stream:
                    if should_cancel():
                        raise InferenceCancelledError("Inference cancelled by force pause request.")
                    if chunk is not None and len(chunk) > 0:
                        chunks.append(float_audio_chunk_to_pcm16_bytes(chunk))
                return chunks

            # 在线程池中执行推理，避免阻塞事件循环导致 SSE 进度无法推送
            pcm16_chunks = await asyncio.to_thread(_consume_stream)

            wav_bytes = build_wav_bytes(sample_rate=sample_rate, pcm16_payload=b"".join(pcm16_chunks))
            saved_result = _build_result_store(request).save_wav(wav_bytes)
            runtime.mark_completed(
                task_id=task_id,
                result_id=saved_result.result_id,
                message="推理完成，结果已缓存。",
            )
            tts_logger.info(
                "TTS 推理结果已缓存 task_id={} result_id={} total_ms={:.2f}",
                task_id,
                saved_result.result_id,
                (time.perf_counter() - request_started) * 1000,
            )

            response = Response(content=wav_bytes, media_type="audio/wav")
            response.headers["X-Inference-Task-Id"] = task_id
            response.headers["X-Synthesis-Result-Id"] = saved_result.result_id
            return response

        cleanup_after_return = False

        def generate_audio():
            assert task_id is not None
            try:
                for chunk in stream:
                    if should_cancel():
                        runtime.mark_cancelled(task_id=task_id, message="推理已被强制暂停。")
                        return
                    if chunk is not None and len(chunk) > 0:
                        yield float_audio_chunk_to_pcm16_bytes(chunk)
                runtime.mark_completed(task_id=task_id, message="流式推理完成。")
                tts_logger.info(
                    "TTS 流式推理完成 task_id={} total_ms={:.2f}",
                    task_id,
                    (time.perf_counter() - request_started) * 1000,
                )
            except InferenceCancelledError:
                runtime.mark_cancelled(task_id=task_id, message="推理已被强制暂停。")
                tts_logger.warning("TTS 流式推理被取消 task_id={}", task_id)
                return
            except Exception as exc:
                runtime.mark_failed(task_id=task_id, message=f"流式推理异常: {exc}")
                tts_logger.exception("TTS 流式推理异常 task_id={}", task_id)
                raise
            finally:
                _cleanup_temporary_files(temporary_files)

        response = StreamingResponse(generate_audio(), media_type="audio/mpeg")
        response.headers["X-Inference-Task-Id"] = task_id
        return response
    except LookupError as exc:
        if task_id is not None:
            runtime.mark_failed(task_id=task_id, message=str(exc))
        tts_logger.warning("TTS 请求失败，音色不存在 voice={} detail={}", payload.voice, exc)
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        if task_id is not None:
            runtime.mark_failed(task_id=task_id, message=str(exc))
        tts_logger.warning("TTS 请求参数非法 voice={} detail={}", payload.voice, exc)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        if task_id is not None:
            runtime.mark_failed(task_id=task_id, message=f"Inference assets not found: {exc}")
        tts_logger.error("TTS 推理依赖缺失 voice={} detail={}", payload.voice, exc)
        raise HTTPException(status_code=422, detail=f"Inference assets not found: {exc}") from exc
    except InferenceCancelledError as exc:
        if task_id is not None:
            runtime.mark_cancelled(task_id=task_id, message=str(exc))
        tts_logger.warning("TTS 推理被取消 task_id={} detail={}", task_id, exc)
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:
        if task_id is not None:
            runtime.mark_failed(task_id=task_id, message=f"Inference initialization failed: {exc}")
        tts_logger.exception("TTS 初始化失败 voice={} task_id={}", payload.voice, task_id)
        raise HTTPException(status_code=500, detail=f"Inference initialization failed: {exc}") from exc
    finally:
        if cleanup_after_return:
            _cleanup_temporary_files(temporary_files)


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


@router.delete(
    "/results/{result_id}",
    response_model=DeleteSynthesisResultResponse,
    summary="删除合成结果",
    description="删除一个已缓存的合成结果文件。",
    responses={
        400: {"description": "结果 ID 非法。"},
        404: {"description": "目标结果不存在。"},
    },
)
def delete_synthesis_result(request: Request, result_id: str) -> DeleteSynthesisResultResponse:
    store = _build_result_store(request)
    try:
        deleted = store.delete_result(result_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if not deleted:
        raise HTTPException(status_code=404, detail=f"Synthesis result '{result_id}' not found.")
    return DeleteSynthesisResultResponse(status="deleted", result_id=result_id)


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


async def _parse_speech_request(request: Request) -> tuple[SpeechRequest, list[Path], dict[str, float]]:
    parse_started = time.perf_counter()
    content_type = request.headers.get("content-type", "")
    if content_type.startswith("multipart/form-data"):
        form_started = time.perf_counter()
        form = await request.form()
        tts_logger.debug("multipart 表单解析完成 elapsed_ms={:.2f}", (time.perf_counter() - form_started) * 1000)
        payload: dict[str, str] = {}
        for key, value in form.items():
            if key == "ref_audio_file":
                continue
            if hasattr(value, "filename"):
                continue
            payload[key] = str(value)

        temporary_files: list[Path] = []
        ref_audio_file = form.get("ref_audio_file")
        if ref_audio_file is not None:
            filename = getattr(ref_audio_file, "filename", None)
            safe_filename = validate_reference_audio_filename(filename)
            read_started = time.perf_counter()
            raw_bytes = await ref_audio_file.read()
            tts_logger.debug(
                "自定义参考音频读取完成 filename={} size_bytes={} elapsed_ms={:.2f}",
                filename or "reference.wav",
                len(raw_bytes),
                (time.perf_counter() - read_started) * 1000,
            )
            temp_path = _store_temporary_reference_audio(
                request=request,
                filename=safe_filename,
                payload=raw_bytes,
            )
            temporary_files.append(temp_path)
            payload["ref_audio"] = str(temp_path)

        try:
            validated = SpeechRequest.model_validate(payload)
            return validated, temporary_files, {"total_ms": (time.perf_counter() - parse_started) * 1000}
        except ValidationError as exc:
            raise RequestValidationError(exc.errors()) from exc

    json_started = time.perf_counter()
    body = await request.json()
    tts_logger.debug("JSON 请求体解析完成 elapsed_ms={:.2f}", (time.perf_counter() - json_started) * 1000)
    try:
        validated = SpeechRequest.model_validate(body)
        return validated, [], {"total_ms": (time.perf_counter() - parse_started) * 1000}
    except ValidationError as exc:
        raise RequestValidationError(exc.errors()) from exc


def _store_temporary_reference_audio(*, request: Request, filename: str, payload: bytes) -> Path:
    return store_temporary_reference_audio(request=request, filename=filename, payload=payload)


def _cleanup_temporary_files(paths: list[Path]) -> None:
    for path in paths:
        with suppress(FileNotFoundError):
            path.unlink()
        parent = path.parent
        with suppress(OSError):
            if parent.exists() and not any(parent.iterdir()):
                parent.rmdir()
        grandparent = parent.parent
        with suppress(OSError):
            if grandparent.exists() and not any(grandparent.iterdir()):
                grandparent.rmdir()
