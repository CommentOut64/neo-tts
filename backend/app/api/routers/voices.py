from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile, status

from backend.app.repositories.voice_repository import VoiceRepository
from backend.app.schemas.voice import VoiceDefaults, VoiceProfile
from backend.app.services.voice_service import VoiceService
from backend.app.tts_registry.model_registry import ModelRegistry


router = APIRouter(prefix="/v1/voices", tags=["voices"])


def _build_service(request: Request) -> VoiceService:
    settings = request.app.state.settings
    repository = VoiceRepository(config_path=settings.voices_config_path, settings=settings)
    return VoiceService(repository, _build_model_registry(request))


def _build_model_registry(request: Request) -> ModelRegistry:
    settings = request.app.state.settings
    registry_root = settings.tts_registry_root or (settings.user_data_root / "tts-registry")
    return ModelRegistry(registry_root)


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
    copy_weights_into_project: bool = Form(default=False, description="是否把权重复制到项目内受管目录。"),
    ref_text: str = Form(..., description="参考音频对应的参考文本。"),
    ref_lang: str = Form(default="zh", description="参考文本语言。"),
    speed: float = Form(default=1.0, description="默认语速。"),
    top_k: int = Form(default=15, description="默认采样 top_k。"),
    top_p: float = Form(default=1.0, description="默认采样 top_p。"),
    temperature: float = Form(default=1.0, description="默认采样温度。"),
    noise_scale: float = Form(default=0.35, description="默认 SoVITS 解码噪声系数。"),
    pause_length: float = Form(default=0.3, description="默认句间停顿秒数。"),
    gpt_external_path: str | None = Form(default=None, description="外部 GPT 权重绝对路径。"),
    sovits_external_path: str | None = Form(default=None, description="外部 SoVITS 权重绝对路径。"),
    gpt_file: UploadFile | None = File(default=None, description="GPT 权重文件，扩展名必须为 `.ckpt`。"),
    sovits_file: UploadFile | None = File(default=None, description="SoVITS 权重文件，扩展名必须为 `.pth`。"),
    ref_audio_file: UploadFile = File(..., description="参考音频文件，支持 `.wav`、`.mp3`、`.flac`。"),
) -> VoiceProfile:
    _validate_weight_inputs(
        copy_weights_into_project=copy_weights_into_project,
        gpt_external_path=gpt_external_path,
        sovits_external_path=sovits_external_path,
        gpt_file=gpt_file,
        sovits_file=sovits_file,
        require_mode=True,
    )
    if gpt_file is not None:
        _validate_upload_file(filename=gpt_file.filename, allowed_extensions={".ckpt"}, field_name="gpt_file")
    if sovits_file is not None:
        _validate_upload_file(filename=sovits_file.filename, allowed_extensions={".pth"}, field_name="sovits_file")
    _validate_upload_file(filename=ref_audio_file.filename, allowed_extensions={".wav", ".mp3", ".flac"}, field_name="ref_audio_file")

    service = _build_service(request)
    try:
        return service.create_uploaded_voice(
            name=name,
            description=description,
            copy_weights_into_project=copy_weights_into_project,
            ref_text=ref_text,
            ref_lang=ref_lang,
            defaults=VoiceDefaults(
                speed=speed,
                top_k=top_k,
                top_p=top_p,
                temperature=temperature,
                noise_scale=noise_scale,
                pause_length=pause_length,
            ),
            gpt_external_path=gpt_external_path,
            sovits_external_path=sovits_external_path,
            gpt_filename=gpt_file.filename if gpt_file is not None else None,
            gpt_bytes=gpt_file.file.read() if gpt_file is not None else None,
            sovits_filename=sovits_file.filename if sovits_file is not None else None,
            sovits_bytes=sovits_file.file.read() if sovits_file is not None else None,
            ref_audio_filename=ref_audio_file.filename or "reference.wav",
            ref_audio_bytes=ref_audio_file.file.read(),
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.patch(
    "/{voice_name}",
    response_model=VoiceProfile,
    summary="编辑托管音色",
    description="更新托管音色的元数据，或按需替换 GPT、SoVITS 与参考音频文件。",
    responses={
        400: {"description": "上传文件扩展名不合法。"},
        404: {"description": "目标音色不存在。"},
        409: {"description": "目标音色不是托管音色，无法编辑。"},
    },
)
def update_voice(
    voice_name: str,
    request: Request,
    description: str | None = Form(default=None, description="音色说明；未传则保留原值。"),
    copy_weights_into_project: bool | None = Form(default=None, description="是否把权重复制到项目内受管目录。"),
    ref_text: str | None = Form(default=None, description="参考音频对应的参考文本；未传则保留原值。"),
    ref_lang: str | None = Form(default=None, description="参考文本语言；未传则保留原值。"),
    gpt_external_path: str | None = Form(default=None, description="可选替换的外部 GPT 权重绝对路径。"),
    sovits_external_path: str | None = Form(default=None, description="可选替换的外部 SoVITS 权重绝对路径。"),
    gpt_file: UploadFile | None = File(default=None, description="可选替换的 GPT 权重文件。"),
    sovits_file: UploadFile | None = File(default=None, description="可选替换的 SoVITS 权重文件。"),
    ref_audio_file: UploadFile | None = File(default=None, description="可选替换的参考音频文件。"),
) -> VoiceProfile:
    _validate_weight_inputs(
        copy_weights_into_project=copy_weights_into_project,
        gpt_external_path=gpt_external_path,
        sovits_external_path=sovits_external_path,
        gpt_file=gpt_file,
        sovits_file=sovits_file,
        require_mode=False,
    )
    if gpt_file is not None:
        _validate_upload_file(filename=gpt_file.filename, allowed_extensions={".ckpt"}, field_name="gpt_file")
    if sovits_file is not None:
        _validate_upload_file(filename=sovits_file.filename, allowed_extensions={".pth"}, field_name="sovits_file")
    if ref_audio_file is not None:
        _validate_upload_file(
            filename=ref_audio_file.filename,
            allowed_extensions={".wav", ".mp3", ".flac"},
            field_name="ref_audio_file",
        )

    service = _build_service(request)
    try:
        return service.update_managed_voice(
            voice_name=voice_name,
            description=description,
            copy_weights_into_project=copy_weights_into_project,
            ref_text=ref_text,
            ref_lang=ref_lang,
            gpt_external_path=gpt_external_path,
            sovits_external_path=sovits_external_path,
            gpt_filename=gpt_file.filename if gpt_file is not None else None,
            gpt_bytes=gpt_file.file.read() if gpt_file is not None else None,
            sovits_filename=sovits_file.filename if sovits_file is not None else None,
            sovits_bytes=sovits_file.file.read() if sovits_file is not None else None,
            ref_audio_filename=ref_audio_file.filename if ref_audio_file is not None else None,
            ref_audio_bytes=ref_audio_file.file.read() if ref_audio_file is not None else None,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
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


def _validate_weight_inputs(
    *,
    copy_weights_into_project: bool | None,
    gpt_external_path: str | None,
    sovits_external_path: str | None,
    gpt_file: UploadFile | None,
    sovits_file: UploadFile | None,
    require_mode: bool,
) -> None:
    has_external_paths = bool(gpt_external_path) or bool(sovits_external_path)
    has_uploaded_files = gpt_file is not None or sovits_file is not None

    if has_external_paths and has_uploaded_files:
        raise HTTPException(
            status_code=400,
            detail="Provide either external weight paths or uploaded weight files, not both.",
        )

    if copy_weights_into_project is False and has_uploaded_files:
        raise HTTPException(
            status_code=400,
            detail="Provide either external weight paths or uploaded weight files, not both.",
        )

    if copy_weights_into_project is True and has_external_paths:
        raise HTTPException(
            status_code=400,
            detail="Provide either external weight paths or uploaded weight files, not both.",
        )

    if copy_weights_into_project is False:
        if not gpt_external_path or not sovits_external_path:
            raise HTTPException(
                status_code=400,
                detail="gpt_external_path and sovits_external_path are required when copy_weights_into_project is false.",
            )
        return

    if copy_weights_into_project is True:
        if gpt_file is None or sovits_file is None:
            raise HTTPException(
                status_code=400,
                detail="gpt_file and sovits_file are required when copy_weights_into_project is true.",
            )
        return

    if require_mode and not has_uploaded_files:
        raise HTTPException(
            status_code=400,
            detail="gpt_external_path and sovits_external_path are required when copy_weights_into_project is false.",
        )
