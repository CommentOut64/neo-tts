from backend.app.schemas.edit_session import (
    DocumentSnapshot,
    EditableSegment,
    RenderProfile,
    SegmentGroup,
    VoiceBinding,
)
from backend.app.services.render_config_resolver import RenderConfigResolver


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


def _snapshot(*, segments: list[EditableSegment], groups: list[SegmentGroup]) -> DocumentSnapshot:
    render_profiles = [
        RenderProfile(render_profile_id="profile-session", scope="session", name="session", speed=1.0, temperature=1.0),
        RenderProfile(render_profile_id="profile-group", scope="group", name="group", speed=1.1, temperature=0.9),
        RenderProfile(render_profile_id="profile-segment", scope="segment", name="segment", speed=0.9, temperature=0.8),
    ]
    voice_bindings = [
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
    ]
    return DocumentSnapshot(
        snapshot_id="head-1",
        document_id="doc-1",
        snapshot_kind="head",
        document_version=2,
        raw_text="".join(segment.raw_text for segment in segments),
        normalized_text="".join(segment.normalized_text for segment in segments),
        segments=segments,
        edges=[],
        groups=groups,
        render_profiles=render_profiles,
        voice_bindings=voice_bindings,
        default_render_profile_id="profile-session",
        default_voice_binding_id="binding-session",
    )


def test_render_config_resolver_prefers_segment_then_group_then_session_scope():
    snapshot = _snapshot(
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
    )

    resolved = RenderConfigResolver().resolve_segment(snapshot=snapshot, segment_id="seg-2")

    assert resolved.render_profile.render_profile_id == "profile-segment"
    assert resolved.voice_binding.voice_binding_id == "binding-segment"
    assert resolved.render_profile_fingerprint
    assert resolved.model_cache_key == "voice-c:model-b"


def test_render_config_resolver_falls_back_to_group_then_session_scope():
    snapshot = _snapshot(
        segments=[
            _segment(
                "seg-1",
                1,
                group_id="group-1",
            )
        ],
        groups=[
            SegmentGroup(
                group_id="group-1",
                name="append-group",
                segment_ids=["seg-1"],
                render_profile_id="profile-group",
                voice_binding_id="binding-group",
                created_by="append",
            )
        ],
    )

    resolved = RenderConfigResolver().resolve_segment(snapshot=snapshot, segment_id="seg-1")

    assert resolved.render_profile.render_profile_id == "profile-group"
    assert resolved.voice_binding.voice_binding_id == "binding-group"
    assert resolved.model_cache_key == "voice-b:model-a"
