from __future__ import annotations

import asyncio
from contextlib import suppress
import json
from pathlib import Path
import queue
import shutil
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import Response, StreamingResponse
from pydantic import ValidationError

from backend.app.inference.audio_processing import build_wav_bytes, float_audio_chunk_to_pcm16_bytes
from backend.app.inference.engine import PyTorchInferenceEngine
from backend.app.inference.model_cache import PyTorchModelCache
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
from backend.app.services.inference_runtime import InferenceRuntimeController
from backend.app.services.synthesis_result_store import SynthesisResultStore
from backend.app.services.tts_service import TtsService
from backend.app.services.voice_service import VoiceService


router = APIRouter(prefix="/v1/audio", tags=["tts"])


def _build_voice_service(request: Request) -> VoiceService:
    settings = request.app.state.settings
    repository = VoiceRepository(config_path=settings.voices_config_path, settings=settings)
    return VoiceService(repository)


def _build_inference_engine(request: Request) -> PyTorchInferenceEngine:
    existing_engine = getattr(request.app.state, "inference_engine", None)
    if existing_engine is not None:
        return existing_engine

    settings = request.app.state.settings
    model_cache = getattr(request.app.state, "model_cache", None)
    if model_cache is None:
        model_cache = PyTorchModelCache(
            project_root=settings.project_root,
            cnhubert_base_path=settings.cnhubert_base_path,
            bert_path=settings.bert_path,
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


@router.post("/speech")
async def text_to_speech(request: Request) -> Response:
    payload, temporary_files = await _parse_speech_request(request)
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

        voice_service = _build_voice_service(request)
        voice_profile = voice_service.get_voice(payload.voice)

        tts_service = TtsService()
        prepared_request = tts_service.prepare_request(payload, voice_profile)
        inference_engine = _build_inference_engine(request)

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

            runtime.update_progress(
                task_id=task_id,
                status="inferencing",
                progress=0.97,
                message="正在编码音频并缓存结果。",
            )
            wav_bytes = build_wav_bytes(sample_rate=sample_rate, pcm16_payload=b"".join(pcm16_chunks))
            saved_result = _build_result_store(request).save_wav(wav_bytes)
            runtime.mark_completed(
                task_id=task_id,
                result_id=saved_result.result_id,
                message="推理完成，结果已缓存。",
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
            except InferenceCancelledError:
                runtime.mark_cancelled(task_id=task_id, message="推理已被强制暂停。")
                return
            except Exception as exc:
                runtime.mark_failed(task_id=task_id, message=f"流式推理异常: {exc}")
                raise
            finally:
                _cleanup_temporary_files(temporary_files)

        response = StreamingResponse(generate_audio(), media_type="audio/mpeg")
        response.headers["X-Inference-Task-Id"] = task_id
        return response
    except LookupError as exc:
        if task_id is not None:
            runtime.mark_failed(task_id=task_id, message=str(exc))
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        if task_id is not None:
            runtime.mark_failed(task_id=task_id, message=str(exc))
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        if task_id is not None:
            runtime.mark_failed(task_id=task_id, message=f"Inference assets not found: {exc}")
        raise HTTPException(status_code=422, detail=f"Inference assets not found: {exc}") from exc
    except InferenceCancelledError as exc:
        if task_id is not None:
            runtime.mark_cancelled(task_id=task_id, message=str(exc))
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:
        if task_id is not None:
            runtime.mark_failed(task_id=task_id, message=f"Inference initialization failed: {exc}")
        raise HTTPException(status_code=500, detail=f"Inference initialization failed: {exc}") from exc
    finally:
        if cleanup_after_return:
            _cleanup_temporary_files(temporary_files)


@router.get("/inference/progress", response_model=InferenceProgressState)
def get_inference_progress(request: Request) -> InferenceProgressState:
    return _build_inference_runtime(request).snapshot()


@router.get("/inference/progress/stream")
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


@router.post("/inference/force-pause", response_model=ForcePauseResponse)
def force_pause_inference(request: Request) -> ForcePauseResponse:
    runtime = _build_inference_runtime(request)
    accepted = runtime.request_force_pause(message="收到强制暂停请求，正在中断推理。")
    return ForcePauseResponse(accepted=accepted, state=runtime.snapshot())


@router.post("/inference/cleanup-residuals", response_model=CleanupResidualsResponse)
def cleanup_inference_residuals(request: Request) -> CleanupResidualsResponse:
    runtime = _build_inference_runtime(request)
    cancelled = runtime.request_force_pause(message="收到残留清理请求，已触发强制暂停。")
    removed_temp_ref_dirs = _cleanup_temporary_reference_dirs(request)
    removed_result_files = _build_result_store(request).clear_all_results()
    runtime.reset_if_idle(message="推理残留已清理。")
    return CleanupResidualsResponse(
        cancelled_active_task=cancelled,
        removed_temp_ref_dirs=removed_temp_ref_dirs,
        removed_result_files=removed_result_files,
        state=runtime.snapshot(),
    )


@router.delete("/results/{result_id}", response_model=DeleteSynthesisResultResponse)
def delete_synthesis_result(request: Request, result_id: str) -> DeleteSynthesisResultResponse:
    store = _build_result_store(request)
    try:
        deleted = store.delete_result(result_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if not deleted:
        raise HTTPException(status_code=404, detail=f"Synthesis result '{result_id}' not found.")
    return DeleteSynthesisResultResponse(status="deleted", result_id=result_id)


@router.get("/inference/params-cache", response_model=InferenceParamsCacheResponse)
def get_inference_params_cache(request: Request) -> InferenceParamsCacheResponse:
    store = _build_params_cache_store(request)
    cached = store.load()
    if cached is None:
        return InferenceParamsCacheResponse(payload={}, updated_at=None)
    payload, updated_at = cached
    return InferenceParamsCacheResponse(payload=payload, updated_at=updated_at)


@router.put("/inference/params-cache", response_model=InferenceParamsCacheResponse)
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


def _cleanup_temporary_reference_dirs(request: Request) -> int:
    settings = request.app.state.settings
    temp_root = settings.managed_voices_dir
    if not temp_root.is_absolute():
        temp_root = settings.project_root / temp_root
    temp_root = temp_root / "_temp_refs"

    if not temp_root.exists():
        return 0

    removed = 0
    for child in temp_root.iterdir():
        if child.is_dir():
            shutil.rmtree(child, ignore_errors=False)
            removed += 1
    with suppress(OSError):
        if not any(temp_root.iterdir()):
            temp_root.rmdir()
    return removed


async def _parse_speech_request(request: Request) -> tuple[SpeechRequest, list[Path]]:
    content_type = request.headers.get("content-type", "")
    if content_type.startswith("multipart/form-data"):
        form = await request.form()
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
            _validate_ref_audio_filename(filename)
            raw_bytes = await ref_audio_file.read()
            temp_path = _store_temporary_reference_audio(
                request=request,
                filename=filename or "reference.wav",
                payload=raw_bytes,
            )
            temporary_files.append(temp_path)
            payload["ref_audio"] = str(temp_path)

        try:
            return SpeechRequest.model_validate(payload), temporary_files
        except ValidationError as exc:
            raise RequestValidationError(exc.errors()) from exc

    body = await request.json()
    try:
        return SpeechRequest.model_validate(body), []
    except ValidationError as exc:
        raise RequestValidationError(exc.errors()) from exc


def _validate_ref_audio_filename(filename: str | None) -> None:
    if not filename:
        raise HTTPException(status_code=400, detail="ref_audio_file is required when using multipart/form-data.")
    suffix = Path(filename).suffix.lower()
    if suffix not in {".wav", ".mp3", ".flac"}:
        raise HTTPException(status_code=400, detail="ref_audio_file must use one of: .flac, .mp3, .wav.")


def _store_temporary_reference_audio(*, request: Request, filename: str, payload: bytes) -> Path:
    settings = request.app.state.settings
    temp_dir = settings.managed_voices_dir
    if not temp_dir.is_absolute():
        temp_dir = settings.project_root / temp_dir
    target_dir = temp_dir / "_temp_refs" / uuid4().hex
    target_dir.mkdir(parents=True, exist_ok=False)
    target_path = target_dir / Path(filename).name
    target_path.write_bytes(payload)
    return target_path


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
