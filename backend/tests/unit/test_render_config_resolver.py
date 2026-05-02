from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from backend.app.inference.adapter_definition import AdapterBlockLimits, AdapterDefinition
from backend.app.inference.asset_fingerprint import fingerprint_file
from backend.app.inference.block_adapter_errors import BlockAdapterError
from backend.app.inference.block_adapter_registry import AdapterRegistry
from backend.app.inference.block_adapter_types import AdapterCapabilities
from backend.app.schemas.edit_session import (
    BindingReference,
    DocumentSnapshot,
    EditableSegment,
    ReferenceBindingOverride,
    RenderProfile,
    SegmentGroup,
    VoiceBinding,
)
from backend.app.services.render_config_resolver import RenderConfigResolver
from backend.app.services.session_reference_asset_service import SessionReferenceAsset
from backend.app.tts_registry.model_registry import ModelRegistry
from backend.app.tts_registry.secret_store import SecretStore
from backend.app.tts_registry.types import ModelInstance, ModelPreset


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


class _FakeWorkspaceService:
    def __init__(self, *, session_assets: dict[str, SessionReferenceAsset] | None = None) -> None:
        self._bindings = {
            "ws_voice_a:voice-a:default:speaker-a": {
                "adapter_id": "gpt_sovits_local",
                "voice_id": "voice-a__speaker-a",
                "model_key": "ws_voice_a:voice-a:default",
                "model_instance_id": "ws_voice_a:voice-a:default",
                "reference_audio_path": "preset-a.wav",
                "reference_text": "预设-A",
                "reference_language": "zh",
                "resolved_assets": {
                    "gpt_weight": {"path": "weights/a.ckpt", "fingerprint": "gpt-a-fp"},
                    "sovits_weight": {"path": "weights/a.pth", "fingerprint": "sovits-a-fp"},
                },
                "gpt_path": "weights/a.ckpt",
                "sovits_path": "weights/a.pth",
                "endpoint": None,
                "account_binding": {},
                "adapter_options": {},
                "preset_fixed_fields": {},
            },
            "ws_voice_b:voice-b:default:speaker-b": {
                "adapter_id": "gpt_sovits_local",
                "voice_id": "voice-b__speaker-b",
                "model_key": "ws_voice_b:voice-b:default",
                "model_instance_id": "ws_voice_b:voice-b:default",
                "reference_audio_path": "preset-b.wav",
                "reference_text": "预设-B",
                "reference_language": "ja",
                "resolved_assets": {
                    "gpt_weight": {"path": "weights/b.ckpt", "fingerprint": "gpt-b-fp"},
                    "sovits_weight": {"path": "weights/b.pth", "fingerprint": "sovits-b-fp"},
                },
                "gpt_path": "weights/b.ckpt",
                "sovits_path": "weights/b.pth",
                "endpoint": None,
                "account_binding": {},
                "adapter_options": {},
                "preset_fixed_fields": {},
            },
            "ws_voice_c:voice-c:default:speaker-c": {
                "adapter_id": "gpt_sovits_local",
                "voice_id": "voice-c__speaker-c",
                "model_key": "ws_voice_c:voice-c:default",
                "model_instance_id": "ws_voice_c:voice-c:default",
                "reference_audio_path": "preset-c.wav",
                "reference_text": "预设-C",
                "reference_language": "en",
                "resolved_assets": {
                    "gpt_weight": {"path": "weights/c.ckpt", "fingerprint": "gpt-c-fp"},
                    "sovits_weight": {"path": "weights/c.pth", "fingerprint": "sovits-c-fp"},
                },
                "gpt_path": "weights/c.ckpt",
                "sovits_path": "weights/c.pth",
                "endpoint": None,
                "account_binding": {},
                "adapter_options": {},
                "preset_fixed_fields": {},
            },
        }
        self._session_assets = session_assets or {}

    def resolve_binding_reference(self, binding_ref):
        if isinstance(binding_ref, dict):
            key = ":".join(
                [
                    str(binding_ref["workspace_id"]),
                    str(binding_ref["main_model_id"]),
                    str(binding_ref["submodel_id"]),
                    str(binding_ref["preset_id"]),
                ]
            )
        else:
            key = ":".join(
                [
                    binding_ref.workspace_id,
                    binding_ref.main_model_id,
                    binding_ref.submodel_id,
                    binding_ref.preset_id,
                ]
            )
        if key not in self._bindings:
            raise LookupError(key)
        return self._bindings[key]

    def get_session_reference_asset(self, reference_asset_id: str) -> SessionReferenceAsset:
        return self._session_assets[reference_asset_id]


def _resolver(workspace_service: _FakeWorkspaceService | None = None) -> RenderConfigResolver:
    return RenderConfigResolver(workspace_service=workspace_service or _FakeWorkspaceService())


def _binding(binding_id: str, *, scope: str, workspace_id: str, main_model_id: str, preset_id: str) -> VoiceBinding:
    binding_ref = BindingReference(
        workspace_id=workspace_id,
        main_model_id=main_model_id,
        submodel_id="default",
        preset_id=preset_id,
    )
    return VoiceBinding(
        voice_binding_id=binding_id,
        scope=scope,
        binding_ref=binding_ref,
        voice_id=binding_ref.to_legacy_voice_id(),
        model_key=binding_ref.to_legacy_model_key(),
        model_instance_id=f"{workspace_id}:{main_model_id}:default",
        preset_id=preset_id,
        gpt_path=f"weights/{main_model_id}.ckpt",
        sovits_path=f"weights/{main_model_id}.pth",
    )


def _adapter_registry(*, adapter_id: str = "gpt_sovits_local") -> AdapterRegistry:
    registry = AdapterRegistry()
    registry.register(
        AdapterDefinition(
            adapter_id=adapter_id,
            display_name=adapter_id,
            adapter_family=adapter_id.split("_", 1)[0],
            runtime_kind="local_in_process",
            capabilities=AdapterCapabilities(
                block_render=True,
                exact_segment_output=True,
                segment_level_voice_binding=True,
            ),
            block_limits=AdapterBlockLimits(
                max_block_seconds=40,
                max_block_chars=300,
                max_segment_count=50,
                max_payload_bytes=1024 * 1024,
            ),
        )
    )
    return registry


def _model_registry(tmp_path, *, adapter_id: str = "gpt_sovits_local") -> tuple[ModelRegistry, SecretStore]:
    root = tmp_path / "tts-registry"
    registry = ModelRegistry(root)
    registry.replace_models(
        [
            ModelInstance(
                model_instance_id="model-demo",
                adapter_id=adapter_id,
                source_type="local_package",
                display_name="Demo Model",
                status="ready",
                storage_mode="managed",
                instance_assets={
                    "bert": {
                        "path": "pretrained/bert.bin",
                        "fingerprint": "bert-fp",
                    }
                },
                endpoint=None,
                account_binding=None,
                presets=[
                    ModelPreset(
                        preset_id="preset-default",
                        display_name="Default",
                        kind="imported",
                        status="ready",
                        fixed_fields={},
                        defaults={
                            "speed": 1.0,
                            "top_k": 15,
                            "top_p": 1.0,
                            "temperature": 1.0,
                            "noise_scale": 0.35,
                            "reference_text": "测试参考文本",
                            "reference_language": "zh",
                        },
                        preset_assets={
                            "gpt_weight": {
                                "path": "weights/demo.ckpt",
                                "fingerprint": "gpt-fp",
                            },
                            "sovits_weight": {
                                "path": "weights/demo.pth",
                                "fingerprint": "sovits-fp",
                            },
                            "reference_audio": {
                                "path": "refs/demo.wav",
                                "fingerprint": "ref-fp",
                            },
                        },
                        fingerprint="preset-fp",
                    )
                ],
                fingerprint="model-fp",
            )
        ]
    )
    return registry, SecretStore(root)


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
                    "ws_voice_b:voice-b:default:speaker-b": ReferenceBindingOverride(
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
                    "ws_voice_c:voice-c:default:speaker-c": ReferenceBindingOverride(
                        reference_audio_path="segment-custom.wav",
                        reference_text="段级自定义",
                        reference_language="en",
                    )
                },
            ),
        ],
        voice_bindings=[
            _binding("binding-session", scope="session", workspace_id="ws_voice_a", main_model_id="voice-a", preset_id="speaker-a"),
            _binding("binding-group", scope="group", workspace_id="ws_voice_b", main_model_id="voice-b", preset_id="speaker-b"),
            _binding("binding-segment", scope="segment", workspace_id="ws_voice_c", main_model_id="voice-c", preset_id="speaker-c"),
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
    assert resolved.resolved_reference.binding_key == "ws_voice_c:voice-c:default:speaker-c"
    assert resolved.resolved_reference.source == "custom"
    assert resolved.resolved_reference.reference_scope == "session_override"
    assert resolved.resolved_reference.reference_identity == "ws_voice_c:voice-c:default:speaker-c"
    assert resolved.render_profile.reference_audio_path == "segment-custom.wav"
    assert resolved.render_profile.reference_text == "段级自定义"
    assert resolved.render_profile.reference_language == "en"
    assert resolved.render_context_fingerprint
    assert resolved.model_cache_key == "ws_voice_c:voice-c:default:speaker-c"


def test_render_config_resolver_prefers_group_binding_when_segment_has_no_direct_binding():
    snapshot = DocumentSnapshot(
        snapshot_id="head-group",
        document_id="doc-1",
        snapshot_kind="head",
        document_version=1,
        segments=[_segment("seg-1", 1, group_id="group-1")],
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
            _binding("binding-session", scope="session", workspace_id="ws_voice_a", main_model_id="voice-a", preset_id="speaker-a"),
            _binding("binding-group", scope="group", workspace_id="ws_voice_b", main_model_id="voice-b", preset_id="speaker-b"),
        ],
        default_render_profile_id="profile-session",
        default_voice_binding_id="binding-session",
    )

    resolved = _resolver().resolve_segment(snapshot=snapshot, segment_id="seg-1")

    assert resolved.render_profile.render_profile_id == "profile-group"
    assert resolved.voice_binding.voice_binding_id == "binding-group"
    assert resolved.voice_binding.voice_id == "voice-b__speaker-b"
    assert resolved.model_cache_key == "ws_voice_b:voice-b:default:speaker-b"


def test_render_config_resolver_unrelated_binding_override_does_not_change_current_segment_fingerprint():
    binding = _binding(
        "binding-session",
        scope="session",
        workspace_id="ws_voice_a",
        main_model_id="voice-a",
        preset_id="speaker-a",
    )
    binding_key = "ws_voice_a:voice-a:default:speaker-a"
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
                    binding_key: ReferenceBindingOverride(
                        reference_audio_path="custom-a.wav",
                        reference_text="自定义-A",
                        reference_language="zh",
                    )
                },
            )
        ],
        voice_bindings=[binding],
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
                            "ws_voice_c:voice-c:default:speaker-c": ReferenceBindingOverride(
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
        binding_key="ws_voice_a:voice-a:default:speaker-a",
        audio_path=str(asset_audio_path),
        audio_fingerprint=fingerprint_file(str(asset_audio_path)),
        reference_text="",
        reference_text_fingerprint="",
        reference_language="",
        created_at=datetime.now(timezone.utc),
    )
    binding = _binding(
        "binding-session",
        scope="session",
        workspace_id="ws_voice_a",
        main_model_id="voice-a",
        preset_id="speaker-a",
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
                    "ws_voice_a:voice-a:default:speaker-a": ReferenceBindingOverride(
                        session_reference_asset_id="asset-a",
                        reference_audio_path="stale-flat-path.wav",
                    )
                },
            )
        ],
        voice_bindings=[binding],
        default_render_profile_id="profile-session",
        default_voice_binding_id="binding-session",
    )

    resolved = _resolver(_FakeWorkspaceService(session_assets={"asset-a": session_asset})).resolve_segment(
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
    workspace_service = _FakeWorkspaceService(
        session_assets={
            "asset-a": SessionReferenceAsset(
                reference_asset_id="asset-a",
                session_id="doc-1",
                binding_key="ws_voice_a:voice-a:default:speaker-a",
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
                binding_key="ws_voice_a:voice-a:default:speaker-a",
                audio_path=str(asset_audio_path),
                audio_fingerprint=shared_fingerprint,
                reference_text="",
                reference_text_fingerprint="",
                reference_language="",
                created_at=datetime.now(timezone.utc),
            ),
        }
    )
    binding = _binding(
        "binding-session",
        scope="session",
        workspace_id="ws_voice_a",
        main_model_id="voice-a",
        preset_id="speaker-a",
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
                    "ws_voice_a:voice-a:default:speaker-a": ReferenceBindingOverride(
                        session_reference_asset_id="asset-a",
                        reference_audio_path=str(asset_audio_path),
                        reference_text="自定义参考",
                        reference_language="zh",
                    )
                },
            )
        ],
        voice_bindings=[binding],
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
                            "ws_voice_a:voice-a:default:speaker-a": ReferenceBindingOverride(
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

    before_resolved = _resolver(workspace_service).resolve_segment(snapshot=before_snapshot, segment_id="seg-1")
    after_resolved = _resolver(workspace_service).resolve_segment(snapshot=after_snapshot, segment_id="seg-1")

    assert before_resolved.resolved_reference is not None
    assert after_resolved.resolved_reference is not None
    assert before_resolved.resolved_reference.reference_audio_path == after_resolved.resolved_reference.reference_audio_path
    assert before_resolved.resolved_reference.reference_audio_fingerprint == after_resolved.resolved_reference.reference_audio_fingerprint
    assert before_resolved.resolved_reference.reference_identity == "doc-1:asset-a"
    assert after_resolved.resolved_reference.reference_identity == "doc-1:asset-b"
    assert before_resolved.render_context_fingerprint != after_resolved.render_context_fingerprint


def test_render_config_resolver_resolves_standard_model_binding_from_binding_fields(tmp_path):
    registry, secret_store = _model_registry(tmp_path)
    snapshot = DocumentSnapshot(
        snapshot_id="head-model-binding",
        document_id="doc-1",
        snapshot_kind="head",
        document_version=1,
        segments=[_segment("seg-1", 1)],
        edges=[],
        groups=[],
        render_profiles=[RenderProfile(render_profile_id="profile-session", scope="session", name="session", speed=1.0)],
        voice_bindings=[
            VoiceBinding(
                voice_binding_id="binding-session",
                scope="session",
                voice_id="voice-a",
                model_key="legacy-model-a",
                model_instance_id="model-demo",
                preset_id="preset-default",
            )
        ],
        default_render_profile_id="profile-session",
        default_voice_binding_id="binding-session",
    )

    resolved = RenderConfigResolver(
        model_registry=registry,
        adapter_registry=_adapter_registry(),
        secret_store=secret_store,
    ).resolve_segment(snapshot=snapshot, segment_id="seg-1")

    assert resolved.resolved_model_binding is not None
    assert resolved.resolved_model_binding.adapter_id == "gpt_sovits_local"
    assert resolved.resolved_model_binding.model_instance_id == "model-demo"
    assert resolved.resolved_model_binding.preset_id == "preset-default"
    assert resolved.resolved_model_binding.resolved_assets["bert"]["fingerprint"] == "bert-fp"
    assert resolved.resolved_model_binding.resolved_assets["gpt_weight"]["fingerprint"] == "gpt-fp"
    assert resolved.resolved_model_binding.resolved_parameters["speed"] == 1.0
    assert resolved.model_cache_key == resolved.resolved_model_binding.binding_fingerprint


def test_render_config_resolver_resolves_formal_binding_ref_through_workspace_service(tmp_path):
    binding_ref = BindingReference(
        workspace_id="ws_voice_a",
        main_model_id="voice-a",
        submodel_id="default",
        preset_id="speaker-a",
    )
    snapshot = DocumentSnapshot(
        snapshot_id="head-formal-binding-ref",
        document_id="doc-1",
        snapshot_kind="head",
        document_version=1,
        segments=[_segment("seg-1", 1)],
        edges=[],
        groups=[],
        render_profiles=[RenderProfile(render_profile_id="profile-session", scope="session", name="session")],
        voice_bindings=[
            VoiceBinding(
                voice_binding_id="binding-session",
                scope="session",
                binding_ref=binding_ref,
                voice_id=binding_ref.to_legacy_voice_id(),
                model_key=binding_ref.to_legacy_model_key(),
            )
        ],
        default_render_profile_id="profile-session",
        default_voice_binding_id="binding-session",
    )

    resolved = RenderConfigResolver(
        model_registry=None,
        adapter_registry=_adapter_registry(),
        secret_store=SecretStore(tmp_path / "tts-registry-workspaces"),
        workspace_service=_FakeWorkspaceService(),
    ).resolve_segment(snapshot=snapshot, segment_id="seg-1")

    assert resolved.resolved_model_binding is not None
    assert resolved.resolved_model_binding.adapter_id == "gpt_sovits_local"
    assert resolved.resolved_model_binding.model_instance_id == "ws_voice_a:voice-a:default"
    assert resolved.resolved_model_binding.preset_id == "speaker-a"
    assert resolved.resolved_model_binding.resolved_assets["gpt_weight"]["fingerprint"] == "gpt-a-fp"
    assert resolved.resolved_reference is not None
    assert resolved.resolved_reference.binding_key == "ws_voice_a:voice-a:default:speaker-a"
    assert resolved.resolved_reference.reference_audio_path == "preset-a.wav"


def test_render_config_resolver_returns_model_required_when_registry_is_empty(tmp_path):
    empty_registry = ModelRegistry(tmp_path / "empty-registry")
    snapshot = DocumentSnapshot(
        snapshot_id="head-empty-registry",
        document_id="doc-1",
        snapshot_kind="head",
        document_version=1,
        segments=[_segment("seg-1", 1)],
        edges=[],
        groups=[],
        render_profiles=[RenderProfile(render_profile_id="profile-session", scope="session", name="session")],
        voice_bindings=[
            VoiceBinding(
                voice_binding_id="binding-session",
                scope="session",
                voice_id="voice-a",
                model_key="legacy-model-a",
                model_instance_id="model-demo",
                preset_id="preset-default",
            )
        ],
        default_render_profile_id="profile-session",
        default_voice_binding_id="binding-session",
    )

    with pytest.raises(BlockAdapterError, match="缺少可用模型绑定"):
        RenderConfigResolver(
            model_registry=empty_registry,
            adapter_registry=_adapter_registry(),
            secret_store=SecretStore(tmp_path / "empty-registry"),
        ).resolve_segment(snapshot=snapshot, segment_id="seg-1")


def test_render_config_resolver_returns_adapter_not_installed_when_model_adapter_missing(tmp_path):
    registry, secret_store = _model_registry(tmp_path, adapter_id="missing_adapter")
    snapshot = DocumentSnapshot(
        snapshot_id="head-missing-adapter",
        document_id="doc-1",
        snapshot_kind="head",
        document_version=1,
        segments=[_segment("seg-1", 1)],
        edges=[],
        groups=[],
        render_profiles=[RenderProfile(render_profile_id="profile-session", scope="session", name="session")],
        voice_bindings=[
            VoiceBinding(
                voice_binding_id="binding-session",
                scope="session",
                voice_id="voice-a",
                model_key="legacy-model-a",
                model_instance_id="model-demo",
                preset_id="preset-default",
            )
        ],
        default_render_profile_id="profile-session",
        default_voice_binding_id="binding-session",
    )

    with pytest.raises(BlockAdapterError, match="missing_adapter"):
        RenderConfigResolver(
            model_registry=registry,
            adapter_registry=_adapter_registry(adapter_id="gpt_sovits_local"),
            secret_store=secret_store,
        ).resolve_segment(snapshot=snapshot, segment_id="seg-1")


def test_render_config_resolver_derives_secret_handles_from_secret_store_when_registry_payload_has_no_handles(tmp_path):
    registry, secret_store = _model_registry(tmp_path, adapter_id="external_http_tts")
    model = registry.get_model("model-demo")
    assert model is not None
    registry.replace_model(
        model.model_copy(
            update={
                "account_binding": {
                    "provider": "example",
                    "account_id": "acct-1",
                    "required_secrets": ["api_key"],
                    "secret_handles": {},
                }
            }
        )
    )
    secret_store.put_model_secrets("model-demo", {"api_key": "top-secret"})
    snapshot = DocumentSnapshot(
        snapshot_id="head-secret-handle",
        document_id="doc-1",
        snapshot_kind="head",
        document_version=1,
        segments=[_segment("seg-1", 1)],
        edges=[],
        groups=[],
        render_profiles=[RenderProfile(render_profile_id="profile-session", scope="session", name="session")],
        voice_bindings=[
            VoiceBinding(
                voice_binding_id="binding-session",
                scope="session",
                voice_id="voice-a",
                model_key="legacy-model-a",
                model_instance_id="model-demo",
                preset_id="preset-default",
            )
        ],
        default_render_profile_id="profile-session",
        default_voice_binding_id="binding-session",
    )

    resolved = RenderConfigResolver(
        model_registry=registry,
        adapter_registry=_adapter_registry(adapter_id="external_http_tts"),
        secret_store=secret_store,
    ).resolve_segment(snapshot=snapshot, segment_id="seg-1")

    assert resolved.resolved_model_binding is not None
    assert resolved.resolved_model_binding.secret_handles == {
        "api_key": "secret://model-demo/api_key"
    }


def test_render_config_resolver_exposes_external_http_endpoint_fixed_fields_and_adapter_options(tmp_path):
    registry, secret_store = _model_registry(tmp_path, adapter_id="external_http_tts")
    model = registry.get_model("model-demo")
    assert model is not None
    registry.replace_model(
        model.model_copy(
            update={
                "endpoint": {"url": "https://api.example.com/tts"},
                "account_binding": {
                    "provider": "example",
                    "account_id": "acct-1",
                    "required_secrets": ["api_key"],
                    "secret_handles": {},
                },
                "adapter_options": {
                    "max_concurrent_requests": 2,
                    "requests_per_minute": 30,
                },
                "presets": [
                    model.presets[0].model_copy(
                        update={
                            "fixed_fields": {"remote_voice_id": "voice_a"},
                        }
                    )
                ],
            }
        )
    )
    secret_store.put_model_secrets("model-demo", {"api_key": "top-secret"})
    snapshot = DocumentSnapshot(
        snapshot_id="head-external-http",
        document_id="doc-1",
        snapshot_kind="head",
        document_version=1,
        segments=[_segment("seg-1", 1)],
        edges=[],
        groups=[],
        render_profiles=[RenderProfile(render_profile_id="profile-session", scope="session", name="session")],
        voice_bindings=[
            VoiceBinding(
                voice_binding_id="binding-session",
                scope="session",
                voice_id="voice-a",
                model_key="legacy-model-a",
                model_instance_id="model-demo",
                preset_id="preset-default",
            )
        ],
        default_render_profile_id="profile-session",
        default_voice_binding_id="binding-session",
    )

    resolved = RenderConfigResolver(
        model_registry=registry,
        adapter_registry=_adapter_registry(adapter_id="external_http_tts"),
        secret_store=secret_store,
    ).resolve_segment(snapshot=snapshot, segment_id="seg-1")

    assert resolved.resolved_model_binding is not None
    assert resolved.resolved_model_binding.endpoint == {"url": "https://api.example.com/tts"}
    assert resolved.resolved_model_binding.account_binding == {
        "provider": "example",
        "account_id": "acct-1",
        "required_secrets": ["api_key"],
        "secret_handles": {},
    }
    assert resolved.resolved_model_binding.preset_fixed_fields == {"remote_voice_id": "voice_a"}
    assert resolved.resolved_model_binding.adapter_options == {
        "max_concurrent_requests": 2,
        "requests_per_minute": 30,
    }
    assert resolved.resolved_model_binding.secret_handles == {"api_key": "secret://model-demo/api_key"}
