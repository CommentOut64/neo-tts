from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile, status

from backend.app.repositories.voice_repository import VoiceRepository
from backend.app.schemas.voice import VoiceDefaults, VoiceProfile
from backend.app.services.voice_service import VoiceService


router = APIRouter(prefix="/v1/voices", tags=["voices"])


def _build_service(request: Request) -> VoiceService:
    settings = request.app.state.settings
    repository = VoiceRepository(config_path=settings.voices_config_path, settings=settings)
    return VoiceService(repository)


@router.get("", response_model=list[VoiceProfile])
def list_voices(request: Request) -> list[VoiceProfile]:
    return _build_service(request).list_voices()


@router.post("/reload")
def reload_voices(request: Request) -> dict[str, int | str]:
    count = _build_service(request).reload_voices()
    return {"status": "success", "count": count}


@router.post("/upload", response_model=VoiceProfile, status_code=status.HTTP_201_CREATED)
def upload_voice(
    request: Request,
    name: str = Form(...),
    description: str = Form(default=""),
    ref_text: str = Form(...),
    ref_lang: str = Form(default="zh"),
    speed: float = Form(default=1.0),
    top_k: int = Form(default=15),
    top_p: float = Form(default=1.0),
    temperature: float = Form(default=1.0),
    pause_length: float = Form(default=0.3),
    gpt_file: UploadFile = File(...),
    sovits_file: UploadFile = File(...),
    ref_audio_file: UploadFile = File(...),
) -> VoiceProfile:
    _validate_upload_file(filename=gpt_file.filename, allowed_extensions={".ckpt"}, field_name="gpt_file")
    _validate_upload_file(filename=sovits_file.filename, allowed_extensions={".pth"}, field_name="sovits_file")
    _validate_upload_file(filename=ref_audio_file.filename, allowed_extensions={".wav", ".mp3", ".flac"}, field_name="ref_audio_file")

    service = _build_service(request)
    try:
        return service.create_uploaded_voice(
            name=name,
            description=description,
            ref_text=ref_text,
            ref_lang=ref_lang,
            defaults=VoiceDefaults(
                speed=speed,
                top_k=top_k,
                top_p=top_p,
                temperature=temperature,
                pause_length=pause_length,
            ),
            gpt_filename=gpt_file.filename or "model.ckpt",
            gpt_bytes=gpt_file.file.read(),
            sovits_filename=sovits_file.filename or "model.pth",
            sovits_bytes=sovits_file.file.read(),
            ref_audio_filename=ref_audio_file.filename or "reference.wav",
            ref_audio_bytes=ref_audio_file.file.read(),
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/{voice_name}", response_model=VoiceProfile)
def get_voice_detail(voice_name: str, request: Request) -> VoiceProfile:
    try:
        return _build_service(request).get_voice(voice_name)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/{voice_name}")
def delete_voice(voice_name: str, request: Request) -> dict[str, str]:
    try:
        _build_service(request).delete_voice(voice_name)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"status": "success", "name": voice_name}


def _validate_upload_file(*, filename: str | None, allowed_extensions: set[str], field_name: str) -> None:
    if not filename:
        raise HTTPException(status_code=400, detail=f"{field_name} is required.")
    suffix = "".join((filename or "").lower().rsplit(".", maxsplit=1)[-1:])
    normalized_suffix = f".{suffix}" if suffix and not suffix.startswith(".") else suffix
    if normalized_suffix not in allowed_extensions:
        allowed = ", ".join(sorted(allowed_extensions))
        raise HTTPException(status_code=400, detail=f"{field_name} must use one of: {allowed}.")
