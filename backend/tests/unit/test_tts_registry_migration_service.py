import json
from pathlib import Path

from backend.app.schemas.edit_session import BindingReference
from backend.app.tts_registry.adapter_definition_store import build_default_adapter_definition_store
from backend.app.tts_registry.migration_service import TtsRegistryMigrationService
from backend.app.tts_registry.secret_store import SecretStore
from backend.app.tts_registry.workspace_service import WorkspaceService
from backend.app.tts_registry.workspace_store import WorkspaceStore


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _build_workspace_service(registry_root: Path) -> WorkspaceService:
    return WorkspaceService(
        adapter_store=build_default_adapter_definition_store(enable_gpt_sovits_local=True),
        workspace_store=WorkspaceStore(registry_root),
        secret_store=SecretStore(registry_root),
    )


def test_migration_service_persists_legacy_voice_alias_for_formal_binding_resolution(tmp_path: Path):
    registry_root = tmp_path / "tts-registry"
    voices_config_path = tmp_path / "voices.json"
    _write_json(
        voices_config_path,
        {
            "Demo Voice": {
                "gpt_path": "weights/demo.ckpt",
                "sovits_path": "weights/demo.pth",
                "ref_audio": "refs/demo.wav",
                "ref_text": "hello world",
                "ref_lang": "en",
            }
        },
    )
    workspace_service = _build_workspace_service(registry_root)
    migration_service = TtsRegistryMigrationService(
        workspace_service=workspace_service,
        registry_root=registry_root,
    )

    created = migration_service.migrate_legacy_voices_file(
        voices_config_path=voices_config_path,
    )

    assert created == [
        {
            "legacy_voice_id": "Demo Voice",
            "binding_ref": {
                "workspace_id": "ws_legacy_gpt_sovits",
                "main_model_id": "demo_voice",
                "submodel_id": "default",
                "preset_id": "default",
            },
        }
    ]

    resolved = workspace_service.resolve_binding_reference(
        BindingReference(
            workspace_id="legacy",
            main_model_id="Demo Voice",
            submodel_id="gpt-sovits-v2",
            preset_id="default",
        )
    )

    assert resolved["workspace"].workspace_id == "ws_legacy_gpt_sovits"
    assert resolved["main_model"].main_model_id == "demo_voice"
    assert resolved["voice_id"] == "demo_voice"
