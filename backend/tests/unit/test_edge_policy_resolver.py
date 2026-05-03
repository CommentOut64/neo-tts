from backend.app.schemas.edit_session import (
    DocumentSnapshot,
    EditableEdge,
    EditableSegment,
    RenderProfile,
    VoiceBinding,
)
from backend.app.services.render_config_resolver import RenderConfigResolver


def _segment(segment_id: str, order_key: int, voice_binding_id: str) -> EditableSegment:
    return EditableSegment(
        segment_id=segment_id,
        document_id="doc-1",
        order_key=order_key,
        previous_segment_id="seg-1" if order_key == 2 else None,
        next_segment_id="seg-2" if order_key == 1 else None,
        stem=f"第{order_key}句",
        text_language="zh",
        terminal_raw="。",
        terminal_source="original",
        detected_language="zh",
        inference_exclusion_reason="none",
        render_version=1,
        render_asset_id=f"render-{segment_id}",
        voice_binding_id=voice_binding_id,
    )


def _snapshot(voice_bindings: list[VoiceBinding]) -> DocumentSnapshot:
    segments = [
        _segment("seg-1", 1, voice_bindings[0].voice_binding_id),
        _segment("seg-2", 2, voice_bindings[1].voice_binding_id),
    ]
    return DocumentSnapshot(
        snapshot_id="head-1",
        document_id="doc-1",
        snapshot_kind="head",
        document_version=2,
        segments=segments,
        edges=[
            EditableEdge(
                edge_id="edge-seg-1-seg-2",
                document_id="doc-1",
                left_segment_id="seg-1",
                right_segment_id="seg-2",
                boundary_strategy="latent_overlap_then_equal_power_crossfade",
            )
        ],
        render_profiles=[
            RenderProfile(render_profile_id="profile-session", scope="session", name="session"),
        ],
        voice_bindings=voice_bindings,
        default_render_profile_id="profile-session",
        default_voice_binding_id=voice_bindings[0].voice_binding_id,
    )


def test_edge_policy_resolver_downgrades_to_crossfade_only_when_voice_changes():
    snapshot = _snapshot(
        [
            VoiceBinding(voice_binding_id="binding-a", scope="segment", voice_id="voice-a", model_key="model-a"),
            VoiceBinding(voice_binding_id="binding-b", scope="segment", voice_id="voice-b", model_key="model-a"),
        ]
    )

    resolved = RenderConfigResolver().resolve_edge(snapshot=snapshot, edge_id="edge-seg-1-seg-2")

    assert resolved.effective_boundary_strategy == "crossfade_only"


def test_edge_policy_resolver_keeps_requested_strategy_when_voice_and_model_match():
    snapshot = _snapshot(
        [
            VoiceBinding(voice_binding_id="binding-a", scope="segment", voice_id="voice-a", model_key="model-a"),
            VoiceBinding(voice_binding_id="binding-b", scope="segment", voice_id="voice-a", model_key="model-a"),
        ]
    )

    resolved = RenderConfigResolver().resolve_edge(snapshot=snapshot, edge_id="edge-seg-1-seg-2")

    assert resolved.effective_boundary_strategy == "latent_overlap_then_equal_power_crossfade"
