from backend.app.schemas.edit_session import (
    DocumentSnapshot,
    EditableSegment,
    ReferenceBindingOverride,
    RenderProfile,
    SegmentGroup,
    VoiceBinding,
)
from backend.app.schemas.voice import VoiceDefaults, VoiceProfile
from backend.app.services.render_config_resolver import RenderConfigResolver


class _FakeVoiceService:
    def __init__(self) -> None:
        self._voices = {
            "voice-a": VoiceProfile(
                name="voice-a",
                gpt_path="a.ckpt",
                sovits_path="a.pth",
                ref_audio="preset-a.wav",
                ref_text="预设-A",
                ref_lang="zh",
                defaults=VoiceDefaults(),
                managed=True,
            ),
            "voice-b": VoiceProfile(
                name="voice-b",
                gpt_path="b.ckpt",
                sovits_path="b.pth",
                ref_audio="preset-b.wav",
                ref_text="预设-B",
                ref_lang="ja",
                defaults=VoiceDefaults(),
                managed=True,
            ),
            "voice-c": VoiceProfile(
                name="voice-c",
                gpt_path="c.ckpt",
                sovits_path="c.pth",
                ref_audio="preset-c.wav",
                ref_text="预设-C",
                ref_lang="en",
                defaults=VoiceDefaults(),
                managed=True,
            ),
        }

    def get_voice(self, voice_name: str) -> VoiceProfile:
        return self._voices[voice_name]


def _segment(segment_id: str, order_key: int, **overrides) -> EditableSegment:
    payload = {
        "segment_id": segment_id,
        "document_id": "doc-1",
        "order_key": order_key,
        "raw_text": f"第{order_key}句。",
        "normalized_text": f"第{order_key}句。",
        "text_language": "zh",
        "render_version": 1,
        "render_asset_id": f"render-{segment_id}",
    }
    payload.update(overrides)
    return EditableSegment(**payload)


def _resolver() -> RenderConfigResolver:
    return RenderConfigResolver(voice_service=_FakeVoiceService())


def test_render_config_resolver_prefers_segment_then_group_then_session_scope_and_resolves_binding_reference():
    snapshot = DocumentSnapshot(
        snapshot_id="head-1",
        document_id="doc-1",
        snapshot_kind="head",
        document_version=2,
        raw_text="第一句。第二句。",
        normalized_text="第一句。第二句。",
        segments=[
            _segment("seg-1", 1),
            _segment(
                "seg-2",
                2,
                group_id="group-1",
                render_profile_id="profile-segment",
                voice_binding_id="binding-segment",
            ),
        ],
        edges=[],
        groups=[
            SegmentGroup(
                group_id="group-1",
                name="append-group",
                segment_ids=["seg-2"],
                render_profile_id="profile-group",
                voice_binding_id="binding-group",
                created_by="append",
            )
        ],
        render_profiles=[
            RenderProfile(render_profile_id="profile-session", scope="session", name="session", speed=1.0),
            RenderProfile(
                render_profile_id="profile-group",
                scope="group",
                name="group",
                speed=1.1,
                reference_overrides_by_binding={
                    "voice-b:model-a": ReferenceBindingOverride(
                        reference_audio_path="group-custom.wav",
                        reference_text="组级自定义",
                        reference_language="ja",
                    )
                },
            ),
            RenderProfile(
                render_profile_id="profile-segment",
                scope="segment",
                name="segment",
                speed=0.9,
                reference_overrides_by_binding={
                    "voice-c:model-b": ReferenceBindingOverride(
                        reference_audio_path="segment-custom.wav",
                        reference_text="段级自定义",
                        reference_language="en",
                    )
                },
            ),
        ],
        voice_bindings=[
            VoiceBinding(
                voice_binding_id="binding-session",
                scope="session",
                voice_id="voice-a",
                model_key="model-a",
            ),
            VoiceBinding(
                voice_binding_id="binding-group",
                scope="group",
                voice_id="voice-b",
                model_key="model-a",
            ),
            VoiceBinding(
                voice_binding_id="binding-segment",
                scope="segment",
                voice_id="voice-c",
                model_key="model-b",
            ),
        ],
        default_render_profile_id="profile-session",
        default_voice_binding_id="binding-session",
    )

    resolved = _resolver().resolve_segment(snapshot=snapshot, segment_id="seg-2")

    assert resolved.render_profile.render_profile_id == "profile-segment"
    assert resolved.voice_binding.voice_binding_id == "binding-segment"
    assert resolved.resolved_reference is not None
    assert resolved.resolved_reference.binding_key == "voice-c:model-b"
    assert resolved.resolved_reference.source == "custom"
    assert resolved.render_profile.reference_audio_path == "segment-custom.wav"
    assert resolved.render_profile.reference_text == "段级自定义"
    assert resolved.render_profile.reference_language == "en"
    assert resolved.render_context_fingerprint
    assert resolved.model_cache_key == "voice-c:model-b"


def test_render_config_resolver_unrelated_binding_override_does_not_change_current_segment_fingerprint():
    before_snapshot = DocumentSnapshot(
        snapshot_id="head-before",
        document_id="doc-1",
        snapshot_kind="head",
        document_version=1,
        raw_text="第一句。",
        normalized_text="第一句。",
        segments=[_segment("seg-1", 1)],
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
    after_snapshot = before_snapshot.model_copy(
        deep=True,
        update={
            "render_profiles": [
                before_snapshot.render_profiles[0].model_copy(
                    deep=True,
                    update={
                        "reference_overrides_by_binding": {
                            **before_snapshot.render_profiles[0].reference_overrides_by_binding,
                            "voice-c:model-b": ReferenceBindingOverride(
                                reference_audio_path="custom-c.wav",
                                reference_text="自定义-C",
                                reference_language="en",
                            ),
                        }
                    },
                )
            ]
        },
    )

    before_resolved = _resolver().resolve_segment(snapshot=before_snapshot, segment_id="seg-1")
    after_resolved = _resolver().resolve_segment(snapshot=after_snapshot, segment_id="seg-1")

    assert before_resolved.resolved_reference is not None
    assert after_resolved.resolved_reference is not None
    assert before_resolved.resolved_reference.reference_audio_path == "custom-a.wav"
    assert after_resolved.resolved_reference.reference_audio_path == "custom-a.wav"
    assert before_resolved.render_context_fingerprint == after_resolved.render_context_fingerprint
