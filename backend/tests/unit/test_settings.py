from backend.app.core.settings import get_settings


def test_get_settings_defaults_to_preloading_neuro2(monkeypatch):
    monkeypatch.delenv("GPT_SOVITS_PRELOAD_ON_START", raising=False)
    monkeypatch.delenv("GPT_SOVITS_PRELOAD_VOICES", raising=False)

    settings = get_settings()

    assert settings.preload_on_start is True
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
