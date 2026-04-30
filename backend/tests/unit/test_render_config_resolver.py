from datetime import datetime, timezone

from backend.app.schemas.edit_session import (
    DocumentSnapshot,
    EditableSegment,
    ReferenceBindingOverride,
    RenderProfile,
    SegmentGroup,
    VoiceBinding,
)
from backend.app.schemas.voice import VoiceDefaults, VoiceProfile
from backend.app.inference.asset_fingerprint import fingerprint_file
from backend.app.services.render_config_resolver import RenderConfigResolver
from backend.app.services.session_reference_asset_service import SessionReferenceAsset


class _FakeVoiceService:
    def __init__(self, *, session_assets: dict[str, SessionReferenceAsset] | None = None) -> None:
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
        self._session_assets = session_assets or {}

    def get_voice(self, voice_name: str) -> VoiceProfile:
        return self._voices[voice_name]

    def get_session_reference_asset(self, reference_asset_id: str) -> SessionReferenceAsset:
        return self._session_assets[reference_asset_id]


def _segment(segment_id: str, order_key: int, **overrides) -> EditableSegment:
    payload = {
        "segment_id": segment_id,
        "document_id": "doc-1",
        "order_key": order_key,
        "stem": f"第{order_key}句",
        "text_language": "zh",
        "terminal_raw": "。",
        "terminal_source": "original",
        "detected_language": "zh",
        "inference_exclusion_reason": "none",
        "render_version": 1,
        "render_asset_id": f"render-{segment_id}",
    }
    payload.update(overrides)
    return EditableSegment(**payload)


def _resolver(voice_service: _FakeVoiceService | None = None) -> RenderConfigResolver:
    return RenderConfigResolver(voice_service=voice_service or _FakeVoiceService())


def test_render_config_resolver_prefers_segment_then_group_then_session_scope_and_resolves_binding_reference():
    snapshot = DocumentSnapshot(
        snapshot_id="head-1",
        document_id="doc-1",
        snapshot_kind="head",
        document_version=2,
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

    session_resolved = _resolver().resolve_segment(snapshot=snapshot, segment_id="seg-1")
    resolved = _resolver().resolve_segment(snapshot=snapshot, segment_id="seg-2")

    assert session_resolved.render_profile.render_profile_id == "profile-session"
    assert session_resolved.voice_binding.voice_binding_id == "binding-session"
    assert resolved.render_profile.render_profile_id == "profile-segment"
    assert resolved.voice_binding.voice_binding_id == "binding-segment"
    assert resolved.resolved_reference is not None
    assert resolved.resolved_reference.binding_key == "voice-c:model-b"
    assert resolved.resolved_reference.source == "custom"
    assert resolved.resolved_reference.reference_scope == "session_override"
    assert resolved.resolved_reference.reference_identity == "voice-c:model-b"
    assert resolved.render_profile.reference_audio_path == "segment-custom.wav"
    assert resolved.render_profile.reference_text == "段级自定义"
    assert resolved.render_profile.reference_language == "en"
    assert resolved.render_context_fingerprint
    assert resolved.model_cache_key == "voice-c:model-b"


def test_render_config_resolver_prefers_group_binding_when_segment_has_no_direct_binding():
    snapshot = DocumentSnapshot(
        snapshot_id="head-group",
        document_id="doc-1",
        snapshot_kind="head",
        document_version=1,
        segments=[
            _segment("seg-1", 1, group_id="group-1"),
        ],
        edges=[],
        groups=[
            SegmentGroup(
                group_id="group-1",
                name="group-1",
                segment_ids=["seg-1"],
                render_profile_id="profile-group",
                voice_binding_id="binding-group",
                created_by="manual",
            )
        ],
        render_profiles=[
            RenderProfile(render_profile_id="profile-session", scope="session", name="session", speed=1.0),
            RenderProfile(render_profile_id="profile-group", scope="group", name="group", speed=1.1),
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
                model_key="model-b",
            ),
        ],
        default_render_profile_id="profile-session",
        default_voice_binding_id="binding-session",
    )

    resolved = _resolver().resolve_segment(snapshot=snapshot, segment_id="seg-1")

    assert resolved.render_profile.render_profile_id == "profile-group"
    assert resolved.voice_binding.voice_binding_id == "binding-group"
    assert resolved.voice_binding.voice_id == "voice-b"
    assert resolved.model_cache_key == "voice-b:model-b"


def test_render_config_resolver_unrelated_binding_override_does_not_change_current_segment_fingerprint():
    before_snapshot = DocumentSnapshot(
        snapshot_id="head-before",
        document_id="doc-1",
        snapshot_kind="head",
        document_version=1,
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


def test_render_config_resolver_prefers_session_reference_asset_identity_over_flat_override_path(tmp_path):
    asset_audio_path = tmp_path / "references" / "asset-a" / "audio.wav"
    asset_audio_path.parent.mkdir(parents=True, exist_ok=True)
    asset_audio_path.write_bytes(b"RIFFasset-a")
    session_asset = SessionReferenceAsset(
        reference_asset_id="asset-a",
        session_id="doc-1",
        binding_key="voice-a:model-a",
        audio_path=str(asset_audio_path),
        audio_fingerprint=fingerprint_file(str(asset_audio_path)),
        reference_text="",
        reference_text_fingerprint="",
        reference_language="",
        created_at=datetime.now(timezone.utc),
    )
    snapshot = DocumentSnapshot(
        snapshot_id="head-asset",
        document_id="doc-1",
        snapshot_kind="head",
        document_version=1,
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
                        session_reference_asset_id="asset-a",
                        reference_audio_path="stale-flat-path.wav",
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

    resolved = _resolver(_FakeVoiceService(session_assets={"asset-a": session_asset})).resolve_segment(
        snapshot=snapshot,
        segment_id="seg-1",
    )

    assert resolved.resolved_reference is not None
    assert resolved.resolved_reference.reference_scope == "session_override"
    assert resolved.resolved_reference.reference_identity == "doc-1:asset-a"
    assert resolved.resolved_reference.reference_audio_path == str(asset_audio_path)
    assert resolved.resolved_reference.reference_audio_fingerprint == session_asset.audio_fingerprint
    assert resolved.render_profile.reference_audio_path == str(asset_audio_path)
    assert resolved.render_profile.reference_text == "预设-A"
    assert resolved.render_profile.reference_language == "zh"


def test_render_config_resolver_session_reference_asset_identity_change_updates_fingerprint(tmp_path):
    asset_audio_path = tmp_path / "references" / "shared" / "audio.wav"
    asset_audio_path.parent.mkdir(parents=True, exist_ok=True)
    asset_audio_path.write_bytes(b"RIFFshared")
    shared_fingerprint = fingerprint_file(str(asset_audio_path))
    voice_service = _FakeVoiceService(
        session_assets={
            "asset-a": SessionReferenceAsset(
                reference_asset_id="asset-a",
                session_id="doc-1",
                binding_key="voice-a:model-a",
                audio_path=str(asset_audio_path),
                audio_fingerprint=shared_fingerprint,
                reference_text="",
                reference_text_fingerprint="",
                reference_language="",
                created_at=datetime.now(timezone.utc),
            ),
            "asset-b": SessionReferenceAsset(
                reference_asset_id="asset-b",
                session_id="doc-1",
                binding_key="voice-a:model-a",
                audio_path=str(asset_audio_path),
                audio_fingerprint=shared_fingerprint,
                reference_text="",
                reference_text_fingerprint="",
                reference_language="",
                created_at=datetime.now(timezone.utc),
            ),
        }
    )
    before_snapshot = DocumentSnapshot(
        snapshot_id="head-before",
        document_id="doc-1",
        snapshot_kind="head",
        document_version=1,
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
                        session_reference_asset_id="asset-a",
                        reference_audio_path=str(asset_audio_path),
                        reference_text="自定义参考",
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
                            "voice-a:model-a": ReferenceBindingOverride(
                                session_reference_asset_id="asset-b",
                                reference_audio_path=str(asset_audio_path),
                                reference_text="自定义参考",
                                reference_language="zh",
                            )
                        }
                    },
                )
            ]
        },
    )

    before_resolved = _resolver(voice_service).resolve_segment(snapshot=before_snapshot, segment_id="seg-1")
    after_resolved = _resolver(voice_service).resolve_segment(snapshot=after_snapshot, segment_id="seg-1")

    assert before_resolved.resolved_reference is not None
    assert after_resolved.resolved_reference is not None
    assert before_resolved.resolved_reference.reference_audio_path == after_resolved.resolved_reference.reference_audio_path
    assert before_resolved.resolved_reference.reference_audio_fingerprint == after_resolved.resolved_reference.reference_audio_fingerprint
    assert before_resolved.resolved_reference.reference_identity == "doc-1:asset-a"
    assert after_resolved.resolved_reference.reference_identity == "doc-1:asset-b"
    assert before_resolved.render_context_fingerprint != after_resolved.render_context_fingerprint
