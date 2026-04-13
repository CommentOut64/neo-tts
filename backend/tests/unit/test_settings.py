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
