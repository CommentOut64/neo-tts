from backend.app.schemas.edit_session import ReferenceBindingOverride
from backend.app.services.reference_binding import (
    build_binding_key,
    merge_reference_override,
    migrate_legacy_render_profile_payload,
)


def test_build_binding_key_uses_voice_id_and_model_key():
    assert build_binding_key(voice_id="voice-a", model_key="model-b") == "voice-a:model-b"


def test_build_binding_key_uses_binding_ref_quadruple_for_formal_registry_binding():
    assert (
        build_binding_key(
            binding_ref={
                "workspace_id": "ws_qwen3",
                "main_model_id": "qwen3_tts_1_7b",
                "submodel_id": "default",
                "preset_id": "speaker_vivian",
            }
        )
        == "ws_qwen3:qwen3_tts_1_7b:default:speaker_vivian"
    )


def test_merge_reference_override_prefers_override_and_falls_back_to_preset_per_field():
    merged = merge_reference_override(
        preset_reference={
            "reference_audio_path": "preset.wav",
            "reference_text": "预设文本",
            "reference_language": "zh",
        },
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


def test_merge_reference_override_supports_registry_preset_reference_payload():
    merged = merge_reference_override(
        preset_reference={
            "reference_audio_path": "refs/registry.wav",
            "reference_text": "registry preset text",
            "reference_language": "en",
        },
        override=ReferenceBindingOverride(
            reference_audio_path=None,
            reference_text="custom text",
            reference_language=None,
        ),
    )

    assert merged == {
        "reference_audio_path": "refs/registry.wav",
        "reference_text": "custom text",
        "reference_language": "en",
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
