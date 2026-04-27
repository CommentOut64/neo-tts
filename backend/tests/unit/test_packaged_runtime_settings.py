from pathlib import Path

from backend.app.core.logging import configure_logging
from backend.app.core.settings import get_settings


def _set_packaged_runtime_env(
    *,
    monkeypatch,
    distribution_kind: str,
    project_root: Path,
    app_core_root: Path,
    runtime_root: Path,
    models_root: Path,
    pretrained_models_root: Path,
    user_data_root: Path,
    exports_root: Path,
) -> None:
    monkeypatch.setenv("NEO_TTS_DISTRIBUTION_KIND", distribution_kind)
    monkeypatch.setenv("NEO_TTS_PROJECT_ROOT", str(project_root))
    monkeypatch.setenv("NEO_TTS_APP_CORE_ROOT", str(app_core_root))
    monkeypatch.setenv("NEO_TTS_RUNTIME_ROOT", str(runtime_root))
    monkeypatch.setenv("NEO_TTS_MODELS_ROOT", str(models_root))
    monkeypatch.setenv("NEO_TTS_PRETRAINED_MODELS_ROOT", str(pretrained_models_root))
    monkeypatch.setenv("NEO_TTS_USER_DATA_ROOT", str(user_data_root))
    monkeypatch.setenv("NEO_TTS_EXPORTS_ROOT", str(exports_root))


def test_installed_runtime_uses_appdata_and_documents(tmp_path, monkeypatch):
    runtime_root = tmp_path / "NeoTTS"
    app_core_root = runtime_root / "packages" / "app-core" / "v0.0.1"
    python_root = runtime_root / "packages" / "runtime" / "py311-cu124-v1"
    models_root = runtime_root / "packages" / "models" / "builtin-v1"
    pretrained_models_root = runtime_root / "packages" / "pretrained-models" / "support-v1"
    user_data_root = tmp_path / "AppData" / "Local" / "NeoTTS"
    exports_root = tmp_path / "Documents" / "NeoTTS" / "Exports"
    _set_packaged_runtime_env(
        monkeypatch=monkeypatch,
        distribution_kind="installed",
        project_root=runtime_root,
        app_core_root=app_core_root,
        runtime_root=python_root,
        models_root=models_root,
        pretrained_models_root=pretrained_models_root,
        user_data_root=user_data_root,
        exports_root=exports_root,
    )

    settings = get_settings()
    log_dir = configure_logging(project_root=settings.project_root, force=True)

    assert settings.distribution_kind == "installed"
    assert settings.project_root == runtime_root.resolve()
    assert settings.resources_root == app_core_root.resolve()
    assert settings.app_core_root == app_core_root.resolve()
    assert settings.runtime_root == python_root.resolve()
    assert settings.models_root == models_root.resolve()
    assert settings.pretrained_models_root == pretrained_models_root.resolve()
    assert settings.user_data_root == user_data_root.resolve()
    assert settings.logs_dir == user_data_root.resolve() / "logs"
    assert settings.builtin_voices_config_path == app_core_root.resolve() / "config" / "voices.json"
    assert settings.voices_config_path == user_data_root.resolve() / "config" / "voices.json"
    assert settings.cnhubert_base_path == models_root.resolve() / "models" / "builtin" / "chinese-hubert-base"
    assert settings.bert_path == models_root.resolve() / "models" / "builtin" / "chinese-roberta-wwm-ext-large"
    assert settings.managed_voices_dir == user_data_root.resolve() / "managed_voices"
    assert settings.synthesis_results_dir == user_data_root.resolve() / "synthesis_results"
    assert settings.inference_params_cache_file == user_data_root.resolve() / "inference" / "params_cache.json"
    assert settings.edit_session_db_file == user_data_root.resolve() / "edit_session" / "session.db"
    assert settings.edit_session_assets_dir == user_data_root.resolve() / "edit_session" / "assets"
    assert settings.edit_session_exports_dir == exports_root.resolve()
    assert log_dir == settings.logs_dir


def test_portable_runtime_uses_side_by_side_data_dirs(tmp_path, monkeypatch):
    runtime_root = tmp_path / "NeoTTS-Portable"
    app_core_root = runtime_root / "packages" / "app-core" / "v0.0.1"
    python_root = runtime_root / "packages" / "runtime" / "py311-cu124-v1"
    models_root = runtime_root / "packages" / "models" / "builtin-v1"
    pretrained_models_root = runtime_root / "packages" / "pretrained-models" / "support-v1"
    user_data_root = runtime_root / "data"
    exports_root = runtime_root / "exports"
    _set_packaged_runtime_env(
        monkeypatch=monkeypatch,
        distribution_kind="portable",
        project_root=runtime_root,
        app_core_root=app_core_root,
        runtime_root=python_root,
        models_root=models_root,
        pretrained_models_root=pretrained_models_root,
        user_data_root=user_data_root,
        exports_root=exports_root,
    )

    settings = get_settings()
    log_dir = configure_logging(project_root=settings.project_root, force=True)

    assert settings.distribution_kind == "portable"
    assert settings.project_root == runtime_root.resolve()
    assert settings.resources_root == app_core_root.resolve()
    assert settings.app_core_root == app_core_root.resolve()
    assert settings.runtime_root == python_root.resolve()
    assert settings.models_root == models_root.resolve()
    assert settings.pretrained_models_root == pretrained_models_root.resolve()
    assert settings.user_data_root == user_data_root.resolve()
    assert settings.logs_dir == user_data_root.resolve() / "logs"
    assert settings.builtin_voices_config_path == app_core_root.resolve() / "config" / "voices.json"
    assert settings.voices_config_path == user_data_root.resolve() / "config" / "voices.json"
    assert settings.cnhubert_base_path == models_root.resolve() / "models" / "builtin" / "chinese-hubert-base"
    assert settings.bert_path == models_root.resolve() / "models" / "builtin" / "chinese-roberta-wwm-ext-large"
    assert settings.managed_voices_dir == user_data_root.resolve() / "managed_voices"
    assert settings.synthesis_results_dir == user_data_root.resolve() / "synthesis_results"
    assert settings.inference_params_cache_file == user_data_root.resolve() / "inference" / "params_cache.json"
    assert settings.edit_session_db_file == user_data_root.resolve() / "edit_session" / "session.db"
    assert settings.edit_session_assets_dir == user_data_root.resolve() / "edit_session" / "assets"
    assert settings.edit_session_exports_dir == exports_root.resolve()
    assert log_dir == settings.logs_dir
