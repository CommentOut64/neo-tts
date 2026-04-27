from backend.app.schemas.edit_session import (
    DocumentSnapshot,
    ReferenceBindingOverride,
    ReferenceBindingOverridePatchRequest,
    RenderProfile,
    RenderProfilePatchRequest,
    VoiceBinding,
)
from backend.app.services.segment_group_service import SegmentGroupService


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
