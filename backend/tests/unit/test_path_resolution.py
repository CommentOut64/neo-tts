from pathlib import Path

from backend.app.core.path_resolution import resolve_runtime_path


def test_resolve_runtime_path_maps_managed_voice_relative_path_into_registry_root(tmp_path):
    user_data_root = tmp_path / "data"
    managed_voices_dir = user_data_root / "tts-registry" / "managed_voices"
    expected = managed_voices_dir / "demo" / "weights" / "demo.ckpt"

    resolved = resolve_runtime_path(
        "managed_voices/demo/weights/demo.ckpt",
        project_root=tmp_path,
        user_data_root=user_data_root,
        resources_root=tmp_path / "packages" / "app-core" / "v0.0.1",
        managed_voices_dir=managed_voices_dir,
    )

    assert resolved == expected.resolve()


def test_resolve_runtime_path_prefers_user_config_under_user_data_root(tmp_path):
    user_data_root = tmp_path / "data"
    user_config = user_data_root / "config" / "voices.json"
    user_config.parent.mkdir(parents=True, exist_ok=True)
    user_config.write_text("{}", encoding="utf-8")
    app_core_root = tmp_path / "packages" / "app-core" / "v0.0.1"
    (app_core_root / "config").mkdir(parents=True, exist_ok=True)
    (app_core_root / "config" / "voices.json").write_text("{\"builtin\": true}", encoding="utf-8")

    resolved = resolve_runtime_path(
        Path("config/voices.json"),
        project_root=tmp_path,
        user_data_root=user_data_root,
        resources_root=app_core_root,
        managed_voices_dir=user_data_root / "tts-registry" / "managed_voices",
    )

    assert resolved == user_config.resolve()
