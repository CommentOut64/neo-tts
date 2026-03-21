from __future__ import annotations

from contextlib import suppress
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import Response, StreamingResponse
from pydantic import ValidationError

from backend.app.inference.audio_processing import build_wav_bytes, float_audio_chunk_to_pcm16_bytes
from backend.app.inference.engine import PyTorchInferenceEngine
from backend.app.inference.model_cache import PyTorchModelCache
from backend.app.repositories.voice_repository import VoiceRepository
from backend.app.schemas.tts import SpeechRequest
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


@router.post("/speech")
async def text_to_speech(request: Request) -> Response:
    payload, temporary_files = await _parse_speech_request(request)
    cleanup_after_return = True

    try:
        voice_service = _build_voice_service(request)
        try:
            voice_profile = voice_service.get_voice(payload.voice)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

        tts_service = TtsService()
        prepared_request = tts_service.prepare_request(payload, voice_profile)

        inference_engine = _build_inference_engine(request)
        try:
            sample_rate, stream = tts_service.synthesize_prepared_stream(
                prepared_request=prepared_request,
                inference_engine=inference_engine,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except FileNotFoundError as exc:
            raise HTTPException(status_code=422, detail=f"Inference assets not found: {exc}") from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Inference initialization failed: {exc}") from exc

        if prepared_request.response_format == "wav":
            pcm16_chunks: list[bytes] = []
            for chunk in stream:
                if chunk is not None and len(chunk) > 0:
                    pcm16_chunks.append(float_audio_chunk_to_pcm16_bytes(chunk))
            wav_bytes = build_wav_bytes(sample_rate=sample_rate, pcm16_payload=b"".join(pcm16_chunks))
            return Response(content=wav_bytes, media_type="audio/wav")

        cleanup_after_return = False

        def generate_audio():
            try:
                for chunk in stream:
                    if chunk is not None and len(chunk) > 0:
                        yield float_audio_chunk_to_pcm16_bytes(chunk)
            finally:
                _cleanup_temporary_files(temporary_files)

        return StreamingResponse(generate_audio(), media_type="audio/mpeg")
    finally:
        if cleanup_after_return:
            _cleanup_temporary_files(temporary_files)


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
