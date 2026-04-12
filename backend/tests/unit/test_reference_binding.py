from backend.app.schemas.edit_session import ReferenceBindingOverride
from backend.app.schemas.voice import VoiceDefaults, VoiceProfile
from backend.app.services.reference_binding import (
    build_binding_key,
    merge_reference_override,
    migrate_legacy_render_profile_payload,
)


def test_build_binding_key_uses_voice_id_and_model_key():
    assert build_binding_key(voice_id="voice-a", model_key="model-b") == "voice-a:model-b"


def test_merge_reference_override_prefers_override_and_falls_back_to_preset_per_field():
    preset = VoiceProfile(
        name="voice-a",
        gpt_path="demo.ckpt",
        sovits_path="demo.pth",
        ref_audio="preset.wav",
        ref_text="预设文本",
        ref_lang="zh",
        description="",
        defaults=VoiceDefaults(),
        managed=True,
    )

    merged = merge_reference_override(
        preset_voice=preset,
        override=ReferenceBindingOverride(
            reference_audio_path="custom.wav",
            reference_text=None,
            reference_language="ja",
        ),
    )

    assert merged == {
        "reference_audio_path": "custom.wav",
        "reference_text": "预设文本",
        "reference_language": "ja",
    }


def test_migrate_legacy_render_profile_payload_moves_reference_fields_into_binding_override_map():
    binding_key = build_binding_key(voice_id="voice-a", model_key="model-a")
    migrated = migrate_legacy_render_profile_payload(
        {
            "render_profile_id": "profile-session",
            "scope": "session",
            "name": "session",
            "speed": 1.0,
            "top_k": 15,
            "top_p": 1.0,
            "temperature": 1.0,
            "noise_scale": 0.35,
            "reference_audio_path": "legacy.wav",
            "reference_text": "遗留参考文本",
            "reference_language": "en",
            "extra_overrides": {},
        },
        binding_key=binding_key,
    )

    assert migrated["reference_overrides_by_binding"] == {
        binding_key: {
            "reference_audio_path": "legacy.wav",
            "reference_text": "遗留参考文本",
            "reference_language": "en",
        }
    }
    assert "reference_audio_path" not in migrated
    assert "reference_text" not in migrated
    assert "reference_language" not in migrated
