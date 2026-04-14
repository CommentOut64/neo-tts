from pathlib import Path

from backend.app.core.logging import configure_logging
from backend.app.core.settings import get_settings


def _set_packaged_runtime_env(
    *,
    monkeypatch,
    distribution_kind: str,
    project_root: Path,
    resources_root: Path,
    user_data_root: Path,
    exports_root: Path,
) -> None:
    monkeypatch.setenv("NEO_TTS_DISTRIBUTION_KIND", distribution_kind)
    monkeypatch.setenv("NEO_TTS_PROJECT_ROOT", str(project_root))
    monkeypatch.setenv("NEO_TTS_RESOURCES_ROOT", str(resources_root))
    monkeypatch.setenv("NEO_TTS_USER_DATA_ROOT", str(user_data_root))
    monkeypatch.setenv("NEO_TTS_EXPORTS_ROOT", str(exports_root))


def test_installed_runtime_uses_appdata_and_documents(tmp_path, monkeypatch):
    runtime_root = tmp_path / "NeoTTS"
    resources_root = runtime_root / "resources" / "app-runtime"
    user_data_root = tmp_path / "AppData" / "Local" / "NeoTTS"
    exports_root = tmp_path / "Documents" / "NeoTTS" / "Exports"
    _set_packaged_runtime_env(
        monkeypatch=monkeypatch,
        distribution_kind="installed",
        project_root=runtime_root,
        resources_root=resources_root,
        user_data_root=user_data_root,
        exports_root=exports_root,
    )

    settings = get_settings()
    log_dir = configure_logging(project_root=settings.project_root, force=True)

    assert settings.distribution_kind == "installed"
    assert settings.project_root == runtime_root.resolve()
    assert settings.resources_root == resources_root.resolve()
    assert settings.user_data_root == user_data_root.resolve()
    assert settings.logs_dir == user_data_root.resolve() / "logs"
    assert settings.builtin_voices_config_path == resources_root.resolve() / "config" / "voices.json"
    assert settings.voices_config_path == user_data_root.resolve() / "config" / "voices.json"
    assert settings.managed_voices_dir == user_data_root.resolve() / "managed_voices"
    assert settings.synthesis_results_dir == user_data_root.resolve() / "synthesis_results"
    assert settings.inference_params_cache_file == user_data_root.resolve() / "inference" / "params_cache.json"
    assert settings.edit_session_db_file == user_data_root.resolve() / "edit_session" / "session.db"
    assert settings.edit_session_assets_dir == user_data_root.resolve() / "edit_session" / "assets"
    assert settings.edit_session_exports_dir == exports_root.resolve()
    assert log_dir == settings.logs_dir


def test_portable_runtime_uses_side_by_side_data_dirs(tmp_path, monkeypatch):
    runtime_root = tmp_path / "NeoTTS-Portable"
    resources_root = runtime_root / "resources" / "app-runtime"
    user_data_root = runtime_root / "data"
    exports_root = runtime_root / "exports"
    _set_packaged_runtime_env(
        monkeypatch=monkeypatch,
        distribution_kind="portable",
        project_root=runtime_root,
        resources_root=resources_root,
        user_data_root=user_data_root,
        exports_root=exports_root,
    )

    settings = get_settings()
    log_dir = configure_logging(project_root=settings.project_root, force=True)

    assert settings.distribution_kind == "portable"
    assert settings.project_root == runtime_root.resolve()
    assert settings.resources_root == resources_root.resolve()
    assert settings.user_data_root == user_data_root.resolve()
    assert settings.logs_dir == user_data_root.resolve() / "logs"
    assert settings.builtin_voices_config_path == resources_root.resolve() / "config" / "voices.json"
    assert settings.voices_config_path == user_data_root.resolve() / "config" / "voices.json"
    assert settings.managed_voices_dir == user_data_root.resolve() / "managed_voices"
    assert settings.synthesis_results_dir == user_data_root.resolve() / "synthesis_results"
    assert settings.inference_params_cache_file == user_data_root.resolve() / "inference" / "params_cache.json"
    assert settings.edit_session_db_file == user_data_root.resolve() / "edit_session" / "session.db"
    assert settings.edit_session_assets_dir == user_data_root.resolve() / "edit_session" / "assets"
    assert settings.edit_session_exports_dir == exports_root.resolve()
    assert log_dir == settings.logs_dir
