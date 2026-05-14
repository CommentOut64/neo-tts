from backend.app.core.settings import get_settings


def test_get_settings_disables_preload_by_default_even_in_development(monkeypatch):
    monkeypatch.delenv("GPT_SOVITS_PRELOAD_ON_START", raising=False)
    monkeypatch.delenv("GPT_SOVITS_PRELOAD_VOICES", raising=False)

    settings = get_settings()

    assert settings.preload_on_start is False
    assert settings.preload_voice_ids == ("neuro2",)


def test_get_settings_disables_preload_by_default_in_packaged_mode(monkeypatch):
    monkeypatch.setenv("NEO_TTS_DISTRIBUTION_KIND", "portable")
    monkeypatch.delenv("GPT_SOVITS_PRELOAD_ON_START", raising=False)
    monkeypatch.delenv("GPT_SOVITS_PRELOAD_VOICES", raising=False)

    settings = get_settings()

    assert settings.preload_on_start is False
    assert settings.preload_voice_ids == ("neuro2",)


def test_get_settings_allows_overriding_preload_behavior(monkeypatch):
    monkeypatch.setenv("GPT_SOVITS_PRELOAD_ON_START", "0")
    monkeypatch.setenv("GPT_SOVITS_PRELOAD_VOICES", "demo, alt , ,voice-c")

    settings = get_settings()

    assert settings.preload_on_start is False
    assert settings.preload_voice_ids == ("demo", "alt", "voice-c")


def test_get_settings_defaults_gpu_offload_thresholds(monkeypatch):
    monkeypatch.delenv("GPT_SOVITS_GPU_OFFLOAD_ENABLED", raising=False)
    monkeypatch.delenv("GPT_SOVITS_GPU_MIN_FREE_MB", raising=False)
    monkeypatch.delenv("GPT_SOVITS_GPU_RESERVE_MB_FOR_LOAD", raising=False)

    settings = get_settings()

    assert settings.gpu_offload_enabled is True
    assert settings.gpu_min_free_mb == 2048
    assert settings.gpu_reserve_mb_for_load == 4096


def test_get_settings_allows_overriding_gpu_offload_thresholds(monkeypatch):
    monkeypatch.setenv("GPT_SOVITS_GPU_OFFLOAD_ENABLED", "false")
    monkeypatch.setenv("GPT_SOVITS_GPU_MIN_FREE_MB", "1024")
    monkeypatch.setenv("GPT_SOVITS_GPU_RESERVE_MB_FOR_LOAD", "3072")

    settings = get_settings()

    assert settings.gpu_offload_enabled is False
    assert settings.gpu_min_free_mb == 1024
    assert settings.gpu_reserve_mb_for_load == 3072


def test_get_settings_product_mode_derives_registry_cache_and_edit_session_paths(tmp_path, monkeypatch):
    runtime_root = tmp_path / "NeoTTS-Portable"
    app_core_root = runtime_root / "packages" / "app-core" / "v0.0.1"
    python_root = runtime_root / "packages" / "python-runtime" / "py311-cu128-v1"
    user_data_root = runtime_root / "data"

    monkeypatch.setenv("NEO_TTS_DISTRIBUTION_KIND", "portable")
    monkeypatch.setenv("NEO_TTS_PROJECT_ROOT", str(runtime_root))
    monkeypatch.setenv("NEO_TTS_APP_CORE_ROOT", str(app_core_root))
    monkeypatch.setenv("NEO_TTS_RUNTIME_ROOT", str(python_root))
    monkeypatch.setenv("NEO_TTS_USER_DATA_ROOT", str(user_data_root))
    monkeypatch.delenv("NEO_TTS_MODEL_REGISTRY_ROOT", raising=False)
    monkeypatch.delenv("GPT_SOVITS_MANAGED_VOICES_DIR", raising=False)
    monkeypatch.delenv("GPT_SOVITS_SYNTHESIS_RESULTS_DIR", raising=False)
    monkeypatch.delenv("GPT_SOVITS_INFERENCE_PARAMS_CACHE_FILE", raising=False)
    monkeypatch.delenv("GPT_SOVITS_EDIT_SESSION_DB_FILE", raising=False)
    monkeypatch.delenv("GPT_SOVITS_EDIT_SESSION_ASSETS_DIR", raising=False)

    settings = get_settings()

    assert settings.user_data_root == user_data_root.resolve()
    assert settings.voices_config_path == user_data_root.resolve() / "config" / "voices.json"
    assert settings.tts_registry_root == user_data_root.resolve() / "tts-registry"
    assert settings.user_models_dir == user_data_root.resolve() / "tts-registry" / "models"
    assert settings.managed_voices_dir == user_data_root.resolve() / "tts-registry" / "managed_voices"
    assert settings.cache_root == user_data_root.resolve() / "cache"
    assert settings.synthesis_results_dir == user_data_root.resolve() / "cache" / "synthesis_results"
    assert settings.inference_params_cache_file == user_data_root.resolve() / "cache" / "inference" / "params_cache.json"
    assert settings.edit_session_db_file == user_data_root.resolve() / "edit-session" / "session.db"
    assert settings.edit_session_assets_dir == user_data_root.resolve() / "edit-session" / "assets"


def test_get_settings_product_mode_allows_empty_registry_without_builtin_models(tmp_path, monkeypatch):
    runtime_root = tmp_path / "NeoTTS-CorePortable"
    app_core_root = runtime_root / "packages" / "app-core" / "v0.0.1"
    python_root = runtime_root / "packages" / "python-runtime" / "py311-cu128-v1"

    monkeypatch.setenv("NEO_TTS_DISTRIBUTION_KIND", "portable")
    monkeypatch.setenv("NEO_TTS_PROJECT_ROOT", str(runtime_root))
    monkeypatch.setenv("NEO_TTS_APP_CORE_ROOT", str(app_core_root))
    monkeypatch.setenv("NEO_TTS_RUNTIME_ROOT", str(python_root))
    monkeypatch.delenv("NEO_TTS_MODELS_ROOT", raising=False)
    monkeypatch.delenv("NEO_TTS_PRETRAINED_MODELS_ROOT", raising=False)
    monkeypatch.delenv("NEO_TTS_MODEL_REGISTRY_ROOT", raising=False)
    monkeypatch.delenv("GPT_SOVITS_VOICES_CONFIG", raising=False)

    settings = get_settings()

    assert settings.distribution_kind == "portable"
    assert settings.tts_registry_root == runtime_root.resolve() / "data" / "tts-registry"
    assert settings.builtin_voices_config_path == app_core_root.resolve() / "config" / "voices.json"
    assert settings.gpt_sovits_adapter_installed is False


def test_get_settings_marks_gpt_sovits_adapter_available_when_runtime_package_exists(tmp_path, monkeypatch):
    runtime_root = tmp_path / "NeoTTS-Portable"
    app_core_root = runtime_root / "packages" / "app-core" / "v0.0.1"
    python_root = runtime_root / "packages" / "python-runtime" / "py311-cu128-v1"
    gpt_sovits_root = app_core_root / "GPT_SoVITS"
    gpt_sovits_root.mkdir(parents=True, exist_ok=True)

    monkeypatch.setenv("NEO_TTS_DISTRIBUTION_KIND", "portable")
    monkeypatch.setenv("NEO_TTS_PROJECT_ROOT", str(runtime_root))
    monkeypatch.setenv("NEO_TTS_APP_CORE_ROOT", str(app_core_root))
    monkeypatch.setenv("NEO_TTS_RUNTIME_ROOT", str(python_root))

    settings = get_settings()

    assert settings.gpt_sovits_root == gpt_sovits_root.resolve()
    assert settings.gpt_sovits_adapter_installed is True


def test_get_settings_marks_qwen3_adapter_available_when_qwen_tts_package_is_installed(monkeypatch):
    monkeypatch.delenv("NEO_TTS_QWEN3_TTS_ROOT", raising=False)

    settings = get_settings()

    assert settings.qwen3_tts_adapter_installed is True
