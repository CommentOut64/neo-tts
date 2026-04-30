from backend.app.schemas.edit_session import (
    DocumentSnapshot,
    ReferenceBindingOverride,
    ReferenceBindingOverridePatchRequest,
    RenderProfile,
    RenderProfilePatchRequest,
    VoiceBinding,
    VoiceBindingPatchRequest,
)
from backend.app.services.segment_group_service import SegmentGroupService
from backend.app.schemas.voice import VoiceDefaults, VoiceProfile


def _snapshot() -> DocumentSnapshot:
    return DocumentSnapshot(
        snapshot_id="head-1",
        document_id="doc-1",
        snapshot_kind="head",
        document_version=1,
        raw_text="第一句。",
        normalized_text="第一句。",
        segments=[],
        edges=[],
        groups=[],
        render_profiles=[
            RenderProfile(
                render_profile_id="profile-session",
                scope="session",
                name="session",
                reference_overrides_by_binding={
                    "voice-a:model-a": ReferenceBindingOverride(
                        reference_audio_path="custom-a.wav",
                        reference_text="自定义-A",
                        reference_language="zh",
                    )
                },
                reference_audio_path="legacy.wav",
                reference_text="legacy",
                reference_language="ja",
            )
        ],
        voice_bindings=[
            VoiceBinding(
                voice_binding_id="binding-session",
                scope="session",
                voice_id="voice-a",
                model_key="model-a",
                model_instance_id="model-a-instance",
                preset_id="preset-a",
                gpt_path="weights/voice-a.ckpt",
                sovits_path="weights/voice-a.pth",
            )
        ],
        default_render_profile_id="profile-session",
        default_voice_binding_id="binding-session",
    )


def test_create_render_profile_upserts_reference_override_for_target_binding():
    next_snapshot, profile = SegmentGroupService.create_render_profile(
        snapshot=_snapshot(),
        scope="session",
        patch=RenderProfilePatchRequest(
            reference_override=ReferenceBindingOverridePatchRequest(
                binding_key="voice-b:model-b",
                operation="upsert",
                session_reference_asset_id="session-ref-b",
                reference_audio_path="custom-b.wav",
                reference_text="自定义-B",
                reference_language="en",
            )
        ),
        base_profile_id="profile-session",
    )

    assert next_snapshot.render_profiles[-1].reference_overrides_by_binding["voice-a:model-a"].reference_text == "自定义-A"
    assert profile.reference_overrides_by_binding["voice-b:model-b"].reference_audio_path == "custom-b.wav"
    assert profile.reference_overrides_by_binding["voice-b:model-b"].session_reference_asset_id == "session-ref-b"
    assert profile.reference_audio_path is None
    assert profile.reference_text is None
    assert profile.reference_language is None


def test_create_render_profile_clear_removes_only_target_binding_override():
    next_snapshot, profile = SegmentGroupService.create_render_profile(
        snapshot=_snapshot(),
        scope="session",
        patch=RenderProfilePatchRequest(
            reference_override=ReferenceBindingOverridePatchRequest(
                binding_key="voice-a:model-a",
                operation="clear",
            )
        ),
        base_profile_id="profile-session",
    )

    assert "voice-a:model-a" not in profile.reference_overrides_by_binding
    assert next_snapshot.render_profiles[-1].reference_overrides_by_binding == profile.reference_overrides_by_binding


def test_create_voice_binding_projects_new_binding_metadata_when_voice_changes():
    next_snapshot, binding = SegmentGroupService.create_voice_binding(
        snapshot=_snapshot(),
        scope="segment",
        patch=VoiceBindingPatchRequest(
            voice_id="voice-b",
            model_key="model-b",
        ),
        base_binding_id="binding-session",
        projected_voice=VoiceProfile(
            name="voice-b",
            model_instance_id="model-b-instance",
            preset_id="preset-b",
            gpt_path="weights/voice-b.ckpt",
            sovits_path="weights/voice-b.pth",
            ref_audio="refs/voice-b.wav",
            ref_text="voice-b ref",
            ref_lang="zh",
            defaults=VoiceDefaults(),
        ),
    )

    assert next_snapshot.voice_bindings[-1].voice_binding_id == binding.voice_binding_id
    assert binding.voice_id == "voice-b"
    assert binding.model_key == "model-b"
    assert binding.model_instance_id == "model-b-instance"
    assert binding.preset_id == "preset-b"
    assert binding.gpt_path == "weights/voice-b.ckpt"
    assert binding.sovits_path == "weights/voice-b.pth"


def test_create_voice_binding_clears_stale_projected_fields_when_voice_changes_without_projection():
    next_snapshot, binding = SegmentGroupService.create_voice_binding(
        snapshot=_snapshot(),
        scope="segment",
        patch=VoiceBindingPatchRequest(
            voice_id="voice-c",
            model_key="model-c",
        ),
        base_binding_id="binding-session",
    )

    assert next_snapshot.voice_bindings[-1].voice_binding_id == binding.voice_binding_id
    assert binding.voice_id == "voice-c"
    assert binding.model_key == "model-c"
    assert binding.model_instance_id is None
    assert binding.preset_id is None
    assert binding.gpt_path is None
    assert binding.sovits_path is None
