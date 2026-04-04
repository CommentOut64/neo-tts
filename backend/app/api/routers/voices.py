from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile, status

from backend.app.repositories.voice_repository import VoiceRepository
from backend.app.schemas.voice import VoiceDefaults, VoiceProfile
from backend.app.services.voice_service import VoiceService


router = APIRouter(prefix="/v1/voices", tags=["voices"])


def _build_service(request: Request) -> VoiceService:
    settings = request.app.state.settings
    repository = VoiceRepository(config_path=settings.voices_config_path, settings=settings)
    return VoiceService(repository)


@router.get(
    "",
    response_model=list[VoiceProfile],
    summary="列出可用音色",
    description="返回当前配置中可用于 TTS 与 edit-session 初始化的音色列表。",
)
def list_voices(request: Request) -> list[VoiceProfile]:
    return _build_service(request).list_voices()


@router.post(
    "/reload",
    summary="重载音色配置",
    description="重新从配置文件加载音色定义，适合模型管理页面在更新后刷新缓存。",
)
def reload_voices(request: Request) -> dict[str, int | str]:
    count = _build_service(request).reload_voices()
    return {"status": "success", "count": count}


@router.post(
    "/upload",
    response_model=VoiceProfile,
    status_code=status.HTTP_201_CREATED,
    summary="上传新的音色",
    description="上传一组 GPT、SoVITS 与参考音频文件，并注册为新的 voice profile。",
    responses={
        400: {"description": "上传文件缺失或文件扩展名不合法。"},
        409: {"description": "音色名称冲突，或目标音色目录已存在。"},
    },
)
def upload_voice(
    request: Request,
    name: str = Form(..., description="新音色名称；创建后会作为 voice ID 使用。"),
    description: str = Form(default="", description="音色说明，供管理页展示。"),
    ref_text: str = Form(..., description="参考音频对应的参考文本。"),
    ref_lang: str = Form(default="zh", description="参考文本语言。"),
    speed: float = Form(default=1.0, description="默认语速。"),
    top_k: int = Form(default=15, description="默认采样 top_k。"),
    top_p: float = Form(default=1.0, description="默认采样 top_p。"),
    temperature: float = Form(default=1.0, description="默认采样温度。"),
    pause_length: float = Form(default=0.3, description="默认句间停顿秒数。"),
    gpt_file: UploadFile = File(..., description="GPT 权重文件，扩展名必须为 `.ckpt`。"),
    sovits_file: UploadFile = File(..., description="SoVITS 权重文件，扩展名必须为 `.pth`。"),
    ref_audio_file: UploadFile = File(..., description="参考音频文件，支持 `.wav`、`.mp3`、`.flac`。"),
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


@router.get(
    "/{voice_name}",
    response_model=VoiceProfile,
    summary="读取音色详情",
    description="按音色名称读取单个 voice profile，前端可在初始化前展示详情或校验选择结果。",
    responses={404: {"description": "目标音色不存在。"}},
)
def get_voice_detail(voice_name: str, request: Request) -> VoiceProfile:
    try:
        return _build_service(request).get_voice(voice_name)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete(
    "/{voice_name}",
    summary="删除音色",
    description="删除指定 voice profile 及其关联文件。",
    responses={404: {"description": "目标音色不存在。"}},
)
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
