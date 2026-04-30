from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path


@dataclass(frozen=True)
class AppSettings:
    project_root: Path
    voices_config_path: Path
    app_version: str = "0.0.1"
    display_version: str = "0.0.1"
    owner_control_origin: str | None = None
    owner_control_token: str | None = None
    owner_session_id: str | None = None
    distribution_kind: str = "development"
    resources_root: Path | None = None
    app_core_root: Path | None = None
    runtime_root: Path | None = None
    models_root: Path | None = None
    pretrained_models_root: Path | None = None
    gpt_sovits_root: Path | None = None
    gpt_sovits_adapter_installed: bool | None = None
    user_data_root: Path | None = None
    tts_registry_root: Path | None = None
    cache_root: Path | None = None
    logs_dir: Path | None = None
    builtin_voices_config_path: Path | None = None
    user_models_dir: Path | None = None
    managed_voices_dir: Path = Path("storage/managed_voices")
    synthesis_results_dir: Path = Path("storage/synthesis_results")
    inference_params_cache_file: Path = Path("storage/inference/params_cache.json")
    edit_session_db_file: Path = Path("storage/edit_session/session.db")
    edit_session_assets_dir: Path = Path("storage/edit_session/assets")
    edit_session_exports_dir: Path = Path("storage/edit_session/exports")
    edit_session_staging_ttl_seconds: int = 3600
    cnhubert_base_path: Path = Path("pretrained_models/chinese-hubert-base")
    bert_path: Path = Path("pretrained_models/chinese-roberta-wwm-ext-large")
    preload_on_start: bool = False
    preload_voice_ids: tuple[str, ...] = ()
    gpu_offload_enabled: bool = True
    gpu_min_free_mb: int = 2048
    gpu_reserve_mb_for_load: int = 4096

    def __post_init__(self) -> None:
        resolved_project_root = self.project_root.resolve()
        distribution_kind = _normalize_distribution_kind(self.distribution_kind)
        app_core_root = (
            self.app_core_root.resolve()
            if self.app_core_root is not None
            else (
                self.resources_root.resolve()
                if self.resources_root is not None
                else resolved_project_root
            )
        )
        resources_root = app_core_root
        runtime_root = (
            self.runtime_root.resolve()
            if self.runtime_root is not None
            else app_core_root
        )
        models_root = (
            self.models_root.resolve()
            if self.models_root is not None
            else app_core_root
        )
        pretrained_models_root = (
            self.pretrained_models_root.resolve()
            if self.pretrained_models_root is not None
            else app_core_root
        )
        gpt_sovits_root = (
            self.gpt_sovits_root.resolve()
            if self.gpt_sovits_root is not None
            else (resources_root / "GPT_SoVITS").resolve()
        )
        gpt_sovits_adapter_installed = (
            self.gpt_sovits_adapter_installed
            if self.gpt_sovits_adapter_installed is not None
            else gpt_sovits_root.is_dir()
        )
        user_data_root = (
            self.user_data_root.resolve()
            if self.user_data_root is not None
            else (resolved_project_root / "storage").resolve()
        )
        tts_registry_root = (
            self.tts_registry_root.resolve()
            if self.tts_registry_root is not None
            else (user_data_root / "tts-registry").resolve()
        )
        cache_root = (
            self.cache_root.resolve()
            if self.cache_root is not None
            else (user_data_root / "cache").resolve()
        )
        default_logs_dir = (
            (resolved_project_root / "logs").resolve()
            if distribution_kind == "development"
            else (user_data_root / "logs").resolve()
        )
        logs_dir = self.logs_dir.resolve() if self.logs_dir is not None else default_logs_dir
        builtin_voices_config_path = (
            self.builtin_voices_config_path.resolve()
            if self.builtin_voices_config_path is not None
            else self.voices_config_path.resolve()
        )
        user_models_dir = (
            self.user_models_dir.resolve()
            if self.user_models_dir is not None
            else (
                (user_data_root / "models").resolve()
                if distribution_kind == "development"
                else (tts_registry_root / "models").resolve()
            )
        )

        object.__setattr__(self, "project_root", resolved_project_root)
        object.__setattr__(self, "distribution_kind", distribution_kind)
        object.__setattr__(self, "app_version", _normalize_app_version(self.app_version, project_root=resolved_project_root))
        object.__setattr__(self, "display_version", _normalize_display_version(self.display_version, self.app_version))
        object.__setattr__(self, "app_core_root", app_core_root)
        object.__setattr__(self, "runtime_root", runtime_root)
        object.__setattr__(self, "models_root", models_root)
        object.__setattr__(self, "pretrained_models_root", pretrained_models_root)
        object.__setattr__(self, "gpt_sovits_root", gpt_sovits_root)
        object.__setattr__(self, "gpt_sovits_adapter_installed", bool(gpt_sovits_adapter_installed))
        object.__setattr__(self, "resources_root", resources_root)
        object.__setattr__(self, "user_data_root", user_data_root)
        object.__setattr__(self, "tts_registry_root", tts_registry_root)
        object.__setattr__(self, "cache_root", cache_root)
        object.__setattr__(self, "logs_dir", logs_dir)
        object.__setattr__(self, "builtin_voices_config_path", builtin_voices_config_path)
        object.__setattr__(self, "user_models_dir", user_models_dir)
        object.__setattr__(self, "voices_config_path", _resolve_path(self.voices_config_path, base=resolved_project_root))
        default_managed_voices_dir = Path("storage/managed_voices")
        if distribution_kind != "development" and self.managed_voices_dir == default_managed_voices_dir:
            managed_voices_dir = (tts_registry_root / "managed_voices").resolve()
        else:
            managed_voices_dir = _resolve_path(self.managed_voices_dir, base=resolved_project_root)
        object.__setattr__(self, "managed_voices_dir", managed_voices_dir)
        object.__setattr__(
            self,
            "synthesis_results_dir",
            (
                (cache_root / "synthesis_results").resolve()
                if distribution_kind != "development" and self.synthesis_results_dir == Path("storage/synthesis_results")
                else _resolve_path(self.synthesis_results_dir, base=resolved_project_root)
            ),
        )
        object.__setattr__(
            self,
            "inference_params_cache_file",
            (
                (cache_root / "inference" / "params_cache.json").resolve()
                if distribution_kind != "development"
                and self.inference_params_cache_file == Path("storage/inference/params_cache.json")
                else _resolve_path(self.inference_params_cache_file, base=resolved_project_root)
            ),
        )
        object.__setattr__(
            self,
            "edit_session_db_file",
            (
                (user_data_root / "edit-session" / "session.db").resolve()
                if distribution_kind != "development"
                and self.edit_session_db_file == Path("storage/edit_session/session.db")
                else _resolve_path(self.edit_session_db_file, base=resolved_project_root)
            ),
        )
        object.__setattr__(
            self,
            "edit_session_assets_dir",
            (
                (user_data_root / "edit-session" / "assets").resolve()
                if distribution_kind != "development"
                and self.edit_session_assets_dir == Path("storage/edit_session/assets")
                else _resolve_path(self.edit_session_assets_dir, base=resolved_project_root)
            ),
        )
        object.__setattr__(
            self,
            "edit_session_exports_dir",
            (
                (user_data_root / "exports").resolve()
                if distribution_kind != "development"
                and self.edit_session_exports_dir == Path("storage/edit_session/exports")
                else _resolve_path(self.edit_session_exports_dir, base=resolved_project_root)
            ),
        )
        object.__setattr__(self, "cnhubert_base_path", _resolve_path(self.cnhubert_base_path, base=resources_root))
        object.__setattr__(self, "bert_path", _resolve_path(self.bert_path, base=resources_root))


def _parse_bool_env(raw_value: str | None, *, default: bool) -> bool:
    if raw_value is None:
        return default
    normalized = raw_value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default


def _parse_csv_env(raw_value: str | None, *, default: tuple[str, ...]) -> tuple[str, ...]:
    if raw_value is None:
        return default
    values = [item.strip() for item in raw_value.split(",")]
    return tuple(item for item in values if item)


def _normalize_distribution_kind(raw_value: str | None) -> str:
    normalized = (raw_value or "development").strip().lower()
    if normalized in {"development", "installed", "portable"}:
        return normalized
    raise ValueError(f"Unsupported NEO_TTS_DISTRIBUTION_KIND '{raw_value}'.")


def _resolve_path(raw_value: Path | None, *, base: Path) -> Path:
    candidate = raw_value if raw_value is not None else Path(".")
    if candidate.is_absolute():
        return candidate.resolve()
    return (base / candidate).resolve()


def _resolve_from_env(raw_value: str | None, *, default: Path) -> Path:
    if raw_value:
        return Path(raw_value).resolve()
    return default.resolve()


def _read_desktop_package_version(project_root: Path) -> str | None:
    package_json_path = project_root / "desktop" / "package.json"
    if not package_json_path.is_file():
        return None
    try:
        payload = json.loads(package_json_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    raw_version = payload.get("version")
    if isinstance(raw_version, str) and raw_version.strip():
        return raw_version.strip()
    return None


def _normalize_app_version(raw_value: str | None, *, project_root: Path) -> str:
    normalized = (raw_value or "").strip()
    if normalized:
        return normalized
    discovered = _read_desktop_package_version(project_root)
    if discovered:
        return discovered
    return "0.0.1"


def _normalize_display_version(raw_value: str | None, app_version: str) -> str:
    normalized = (raw_value or "").strip().replace("v", "", 1) if raw_value else ""
    if normalized:
        return normalized
    base_version = app_version.strip().removeprefix("v").split("-", 1)[0].strip()
    return base_version or "0.0.1"


def get_settings() -> AppSettings:
    default_project_root = Path(__file__).resolve().parents[3]
    distribution_kind = _normalize_distribution_kind(os.environ.get("NEO_TTS_DISTRIBUTION_KIND"))
    project_root_env = os.environ.get("NEO_TTS_PROJECT_ROOT")
    resources_root_env = os.environ.get("NEO_TTS_RESOURCES_ROOT")
    app_core_root_env = os.environ.get("NEO_TTS_APP_CORE_ROOT")
    runtime_root_env = os.environ.get("NEO_TTS_RUNTIME_ROOT")
    models_root_env = os.environ.get("NEO_TTS_MODELS_ROOT")
    pretrained_models_root_env = os.environ.get("NEO_TTS_PRETRAINED_MODELS_ROOT")
    gpt_sovits_root_env = os.environ.get("NEO_TTS_GPT_SOVITS_ROOT")
    model_registry_root_env = os.environ.get("NEO_TTS_MODEL_REGISTRY_ROOT")
    support_assets_root_env = os.environ.get("NEO_TTS_SUPPORT_ASSETS_ROOT")
    user_data_root_env = os.environ.get("NEO_TTS_USER_DATA_ROOT")
    exports_root_env = os.environ.get("NEO_TTS_EXPORTS_ROOT")
    logs_root_env = os.environ.get("NEO_TTS_LOGS_ROOT")
    voices_config_env = os.environ.get("GPT_SOVITS_VOICES_CONFIG")
    managed_voices_dir_env = os.environ.get("GPT_SOVITS_MANAGED_VOICES_DIR")
    synthesis_results_dir_env = os.environ.get("GPT_SOVITS_SYNTHESIS_RESULTS_DIR")
    inference_params_cache_file_env = os.environ.get("GPT_SOVITS_INFERENCE_PARAMS_CACHE_FILE")
    edit_session_db_file_env = os.environ.get("GPT_SOVITS_EDIT_SESSION_DB_FILE")
    edit_session_assets_dir_env = os.environ.get("GPT_SOVITS_EDIT_SESSION_ASSETS_DIR")
    edit_session_exports_dir_env = os.environ.get("GPT_SOVITS_EDIT_SESSION_EXPORTS_DIR")
    edit_session_staging_ttl_env = os.environ.get("GPT_SOVITS_EDIT_SESSION_STAGING_TTL_SECONDS")
    cnhubert_path_env = os.environ.get("CNHUBERT_PATH") or os.environ.get("GPT_SOVITS_CNHUBERT_PATH")
    bert_path_env = os.environ.get("BERT_PATH") or os.environ.get("GPT_SOVITS_BERT_PATH")
    preload_on_start_env = os.environ.get("GPT_SOVITS_PRELOAD_ON_START")
    preload_voices_env = os.environ.get("GPT_SOVITS_PRELOAD_VOICES")
    gpu_offload_enabled_env = os.environ.get("GPT_SOVITS_GPU_OFFLOAD_ENABLED")
    gpu_min_free_mb_env = os.environ.get("GPT_SOVITS_GPU_MIN_FREE_MB")
    gpu_reserve_mb_for_load_env = os.environ.get("GPT_SOVITS_GPU_RESERVE_MB_FOR_LOAD")
    app_version_env = os.environ.get("NEO_TTS_APP_VERSION")
    display_version_env = os.environ.get("NEO_TTS_DISPLAY_VERSION")
    owner_control_origin = os.environ.get("NEO_TTS_OWNER_CONTROL_ORIGIN")
    owner_control_token = os.environ.get("NEO_TTS_OWNER_CONTROL_TOKEN")
    owner_session_id = os.environ.get("NEO_TTS_OWNER_SESSION_ID")
    project_root = _resolve_from_env(project_root_env, default=default_project_root)
    app_version = _normalize_app_version(app_version_env, project_root=project_root)
    display_version = _normalize_display_version(display_version_env, app_version)

    if distribution_kind == "development":
        app_core_root = _resolve_from_env(app_core_root_env or resources_root_env, default=project_root)
        resources_root = app_core_root
        runtime_root = _resolve_from_env(runtime_root_env, default=project_root)
        models_root = _resolve_from_env(models_root_env, default=project_root)
        pretrained_models_root = _resolve_from_env(pretrained_models_root_env, default=project_root)
        gpt_sovits_root = Path(gpt_sovits_root_env) if gpt_sovits_root_env else app_core_root / "GPT_SoVITS"
        user_data_root = _resolve_from_env(user_data_root_env, default=project_root / "storage")
        logs_dir = _resolve_from_env(logs_root_env, default=project_root / "logs")
        builtin_voices_config_path = app_core_root / "config" / "voices.json"
        voices_config_path = Path(voices_config_env) if voices_config_env else project_root / "config" / "voices.json"
        managed_voices_dir = Path(managed_voices_dir_env) if managed_voices_dir_env else project_root / "storage" / "managed_voices"
        synthesis_results_dir = (
            Path(synthesis_results_dir_env) if synthesis_results_dir_env else project_root / "storage" / "synthesis_results"
        )
        inference_params_cache_file = (
            Path(inference_params_cache_file_env)
            if inference_params_cache_file_env
            else project_root / "storage" / "inference" / "params_cache.json"
        )
        edit_session_db_file = (
            Path(edit_session_db_file_env)
            if edit_session_db_file_env
            else project_root / "storage" / "edit_session" / "session.db"
        )
        edit_session_assets_dir = (
            Path(edit_session_assets_dir_env)
            if edit_session_assets_dir_env
            else project_root / "storage" / "edit_session" / "assets"
        )
        exports_root = _resolve_from_env(
            exports_root_env,
            default=project_root / "storage" / "edit_session" / "exports",
        )
        edit_session_exports_dir = Path(edit_session_exports_dir_env) if edit_session_exports_dir_env else exports_root
        user_models_dir = user_data_root / "models"
        cnhubert_base_path = (
            Path(cnhubert_path_env)
            if cnhubert_path_env
            else project_root / "pretrained_models" / "chinese-hubert-base"
        )
        bert_path = (
            Path(bert_path_env)
            if bert_path_env
            else project_root / "pretrained_models" / "chinese-roberta-wwm-ext-large"
        )
    else:
        app_core_root = _resolve_from_env(
            app_core_root_env or resources_root_env,
            default=project_root / "resources" / "app-runtime",
        )
        resources_root = app_core_root
        runtime_root = _resolve_from_env(runtime_root_env, default=app_core_root)
        user_data_root = _resolve_from_env(user_data_root_env, default=project_root / "data")
        tts_registry_root = _resolve_from_env(model_registry_root_env, default=user_data_root / "tts-registry")
        support_assets_root = _resolve_from_env(support_assets_root_env, default=app_core_root)
        models_root = _resolve_from_env(models_root_env, default=tts_registry_root)
        pretrained_models_root = _resolve_from_env(
            pretrained_models_root_env,
            default=support_assets_root / "support-assets" / "shared",
        )
        gpt_sovits_root = Path(gpt_sovits_root_env) if gpt_sovits_root_env else app_core_root / "GPT_SoVITS"
        cache_root = user_data_root / "cache"
        logs_dir = _resolve_from_env(logs_root_env, default=user_data_root / "logs")
        builtin_voices_config_path = app_core_root / "config" / "voices.json"
        voices_config_path = (
            Path(voices_config_env) if voices_config_env else user_data_root / "config" / "voices.json"
        )
        managed_voices_dir = (
            Path(managed_voices_dir_env) if managed_voices_dir_env else tts_registry_root / "managed_voices"
        )
        synthesis_results_dir = (
            Path(synthesis_results_dir_env) if synthesis_results_dir_env else cache_root / "synthesis_results"
        )
        inference_params_cache_file = (
            Path(inference_params_cache_file_env)
            if inference_params_cache_file_env
            else cache_root / "inference" / "params_cache.json"
        )
        edit_session_db_file = (
            Path(edit_session_db_file_env) if edit_session_db_file_env else user_data_root / "edit-session" / "session.db"
        )
        edit_session_assets_dir = (
            Path(edit_session_assets_dir_env) if edit_session_assets_dir_env else user_data_root / "edit-session" / "assets"
        )
        exports_root = _resolve_from_env(exports_root_env, default=user_data_root / "exports")
        edit_session_exports_dir = Path(edit_session_exports_dir_env) if edit_session_exports_dir_env else exports_root
        user_models_dir = tts_registry_root / "models"
        cnhubert_base_path = (
            Path(cnhubert_path_env)
            if cnhubert_path_env
            else support_assets_root / "support-assets" / "gpt-sovits" / "chinese-hubert-base"
        )
        bert_path = (
            Path(bert_path_env)
            if bert_path_env
            else support_assets_root / "support-assets" / "gpt-sovits" / "chinese-roberta-wwm-ext-large"
        )

    edit_session_staging_ttl_seconds = int(edit_session_staging_ttl_env or 3600)
    # 开发态默认预加载，打包态默认关闭（可通过环境变量显式开启），
    # 避免桌面应用启动阶段被模型导入/预热阻塞。
    preload_default = distribution_kind == "development"
    preload_on_start = _parse_bool_env(preload_on_start_env, default=preload_default)
    preload_voice_ids = _parse_csv_env(preload_voices_env, default=("neuro2",))
    gpu_offload_enabled = _parse_bool_env(gpu_offload_enabled_env, default=True)
    gpu_min_free_mb = int(gpu_min_free_mb_env or 2048)
    gpu_reserve_mb_for_load = int(gpu_reserve_mb_for_load_env or 4096)
    return AppSettings(
        project_root=project_root,
        voices_config_path=voices_config_path,
        app_version=app_version,
        display_version=display_version,
        owner_control_origin=owner_control_origin,
        owner_control_token=owner_control_token,
        owner_session_id=owner_session_id,
        distribution_kind=distribution_kind,
        resources_root=resources_root,
        app_core_root=app_core_root,
        runtime_root=runtime_root,
        models_root=models_root,
        pretrained_models_root=pretrained_models_root,
        gpt_sovits_root=gpt_sovits_root,
        user_data_root=user_data_root,
        tts_registry_root=tts_registry_root if distribution_kind != "development" else None,
        cache_root=cache_root if distribution_kind != "development" else None,
        logs_dir=logs_dir,
        builtin_voices_config_path=builtin_voices_config_path,
        user_models_dir=user_models_dir,
        managed_voices_dir=managed_voices_dir,
        synthesis_results_dir=synthesis_results_dir,
        inference_params_cache_file=inference_params_cache_file,
        edit_session_db_file=edit_session_db_file,
        edit_session_assets_dir=edit_session_assets_dir,
        edit_session_exports_dir=edit_session_exports_dir,
        edit_session_staging_ttl_seconds=edit_session_staging_ttl_seconds,
        cnhubert_base_path=cnhubert_base_path,
        bert_path=bert_path,
        preload_on_start=preload_on_start,
        preload_voice_ids=preload_voice_ids,
        gpu_offload_enabled=gpu_offload_enabled,
        gpu_min_free_mb=gpu_min_free_mb,
        gpu_reserve_mb_for_load=gpu_reserve_mb_for_load,
    )
