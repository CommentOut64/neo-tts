import json
from pathlib import Path

from backend.app.inference.adapter_definition import (
    AdapterBlockLimits,
    AdapterDefinition,
    AssetTopology,
    OverridePolicy,
)
from backend.app.inference.block_adapter_registry import AdapterRegistry
from backend.app.inference.block_adapter_types import AdapterCapabilities
from backend.app.tts_registry.adapter_definition_store import AdapterDefinitionStore
from backend.app.tts_registry.model_import_service import ModelImportService
from backend.app.tts_registry.model_registry import ModelRegistry
from backend.app.tts_registry.secret_store import SecretStore


def _definition(adapter_id: str = "external_http_tts") -> AdapterDefinition:
    return AdapterDefinition(
        adapter_id=adapter_id,
        display_name="External HTTP TTS",
        adapter_family="external_http",
        runtime_kind="external_http",
        capabilities=AdapterCapabilities(
            block_render=True,
            external_http_api=True,
        ),
        block_limits=AdapterBlockLimits(max_payload_bytes=1024 * 1024),
        option_schema={},
        manifest_schema={
            "type": "object",
            "required": [
                "schema_version",
                "package_id",
                "display_name",
                "adapter_id",
                "source_type",
                "instance",
                "presets",
            ],
            "properties": {
                "schema_version": {"type": "integer"},
                "package_id": {"type": "string"},
                "display_name": {"type": "string"},
                "adapter_id": {"type": "string"},
                "source_type": {"type": "string"},
                "instance": {"type": "object"},
                "presets": {"type": "array"},
            },
        },
        asset_topology=AssetTopology(instance_assets=[], preset_assets=[]),
        preset_schema={
            "type": "object",
            "required": ["preset_id", "display_name"],
            "properties": {
                "preset_id": {"type": "string"},
                "display_name": {"type": "string"},
                "fixed_fields": {"type": "object"},
            },
        },
        override_policy=OverridePolicy(),
        max_concurrent_renders=1,
    )


def _store() -> AdapterDefinitionStore:
    registry = AdapterRegistry()
    registry.register(_definition())
    return AdapterDefinitionStore(registry)


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _external_manifest() -> dict:
    return {
        "schema_version": 1,
        "package_id": "remote-provider-a",
        "display_name": "Remote Provider A",
        "adapter_id": "external_http_tts",
        "source_type": "external_api",
        "instance": {
            "endpoint_url": "https://api.example.com/tts",
            "account_binding": {
                "provider": "example",
                "account_id": "acct-1",
            },
            "auth": {
                "required_secrets": ["api_key"],
            },
        },
        "presets": [
            {
                "preset_id": "voice-a",
                "display_name": "Voice A",
                "fixed_fields": {
                    "remote_voice_id": "voice_a",
                },
            }
        ],
    }


def test_secret_store_persists_handles_and_can_resolve_plaintext(tmp_path: Path):
    secret_store = SecretStore(tmp_path / "tts-registry")

    handles = secret_store.put_model_secrets("model-1", {"api_key": "top-secret"})

    assert handles == {"api_key": "secret://model-1/api_key"}
    assert secret_store.resolve_handle(handles["api_key"]) == "top-secret"


def test_external_api_secret_flow_keeps_plaintext_out_of_registry_and_marks_ready_after_fill(tmp_path: Path):
    registry_root = tmp_path / "tts-registry"
    registry = ModelRegistry(registry_root)
    secret_store = SecretStore(registry_root)
    service = ModelImportService(
        adapter_store=_store(),
        model_registry=registry,
        secret_store=secret_store,
    )
    package_root = tmp_path / "remote-package"
    _write_json(package_root / "neo-tts-model.json", _external_manifest())

    imported = service.import_model_package(package_root)

    assert imported.status == "needs_secret"
    assert imported.endpoint == {"url": "https://api.example.com/tts"}
    assert imported.account_binding == {
        "provider": "example",
        "account_id": "acct-1",
        "required_secrets": ["api_key"],
        "secret_handles": {},
    }
    assert imported.presets[0].kind == "remote"
    assert imported.presets[0].fixed_fields == {"remote_voice_id": "voice_a"}
    assert "top-secret" not in (registry_root / "registry.json").read_text(encoding="utf-8")

    updated = service.put_model_secrets("remote-provider-a", {"api_key": "top-secret"})

    assert updated.status == "ready"
    assert updated.account_binding == {
        "provider": "example",
        "account_id": "acct-1",
        "required_secrets": ["api_key"],
        "secret_handles": {"api_key": "secret://remote-provider-a/api_key"},
    }
    assert "top-secret" not in (registry_root / "registry.json").read_text(encoding="utf-8")
    assert secret_store.resolve_handle("secret://remote-provider-a/api_key") == "top-secret"
