import json
from pathlib import Path

import pytest

from backend.app.inference.adapter_definition import (
    AdapterBlockLimits,
    AdapterDefinition,
    AssetTopology,
    OverridePolicy,
)
from backend.app.inference.block_adapter_errors import BlockAdapterError
from backend.app.inference.block_adapter_registry import AdapterRegistry
from backend.app.inference.block_adapter_types import AdapterCapabilities
from backend.app.tts_registry.adapter_definition_store import AdapterDefinitionStore
from backend.app.tts_registry.model_import_service import ModelImportService
from backend.app.tts_registry.model_registry import ModelRegistry
from backend.app.tts_registry.secret_store import SecretStore


def _definition(adapter_id: str = "gpt_sovits_local") -> AdapterDefinition:
    return AdapterDefinition(
        adapter_id=adapter_id,
        display_name="GPT-SoVITS Local",
        adapter_family="gpt_sovits",
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
        asset_topology=AssetTopology(
            instance_assets=["pretrained_base", "bert"],
            preset_assets=["gpt_weight", "sovits_weight", "reference_audio"],
        ),
        preset_schema={
            "type": "object",
            "required": ["preset_id", "display_name"],
            "properties": {
                "preset_id": {"type": "string"},
                "display_name": {"type": "string"},
                "defaults": {"type": "object"},
                "fixed_fields": {"type": "object"},
                "assets": {"type": "object"},
            },
        },
        override_policy=OverridePolicy(
            overridable_assets=["reference_audio"],
            overridable_fields=["reference_text", "reference_language", "synthesis.*"],
        ),
        max_concurrent_renders=1,
    )


def _store() -> AdapterDefinitionStore:
    registry = AdapterRegistry()
    registry.register(_definition())
    registry.register(
        _definition("external_http_tts").model_copy(
            update={
                "display_name": "External HTTP TTS",
                "adapter_family": "external_http",
                "runtime_kind": "external_http",
                "asset_topology": AssetTopology(instance_assets=[], preset_assets=[]),
            }
        )
    )
    return AdapterDefinitionStore(registry)


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _local_manifest() -> dict:
    return {
        "schema_version": 1,
        "package_id": "demo-gpt-sovits",
        "display_name": "Demo Voice",
        "adapter_id": "gpt_sovits_local",
        "source_type": "local_package",
        "instance": {
            "assets": {
                "pretrained_base": "base",
                "bert": "pretrained/bert.bin",
            }
        },
        "presets": [
            {
                "preset_id": "default",
                "display_name": "Default",
                "assets": {
                    "gpt_weight": "weights/demo.ckpt",
                    "sovits_weight": "weights/demo.pth",
                    "reference_audio": "refs/demo.wav",
                },
                "defaults": {
                    "reference_text": "测试参考文本",
                    "reference_language": "zh",
                },
            }
        ],
    }


def _build_local_package(package_root: Path) -> Path:
    _write_json(package_root / "neo-tts-model.json", _local_manifest())
    _write_text(package_root / "base" / "README.txt", "base data")
    _write_text(package_root / "pretrained" / "bert.bin", "bert")
    _write_text(package_root / "weights" / "demo.ckpt", "ckpt")
    _write_text(package_root / "weights" / "demo.pth", "pth")
    _write_text(package_root / "refs" / "demo.wav", "wav")
    return package_root


def test_model_import_service_imports_into_managed_storage_and_supports_hot_reload(tmp_path: Path):
    registry_root = tmp_path / "tts-registry"
    registry = ModelRegistry(registry_root)
    service = ModelImportService(
        adapter_store=_store(),
        model_registry=registry,
        secret_store=SecretStore(registry_root),
    )
    source_package = _build_local_package(tmp_path / "source-package")

    imported = service.import_model_package(source_package)

    assert imported.storage_mode == "managed"
    assert imported.model_instance_id == "demo-gpt-sovits"
    assert Path(imported.instance_assets["bert"]["source_path"]).is_file()
    assert Path(imported.instance_assets["bert"]["source_path"]).resolve().is_relative_to((registry_root / "models").resolve())
    assert registry.get_model("demo-gpt-sovits") is not None
    assert (registry_root / "registry.json").is_file()
    assert not any((registry_root / "staging" / "model-import").glob("*"))

    reloaded_registry = ModelRegistry(registry_root)
    reloaded = reloaded_registry.get_model("demo-gpt-sovits")

    assert reloaded is not None
    assert reloaded.presets[0].preset_id == "default"


def test_model_import_service_supports_external_storage_mode(tmp_path: Path):
    registry_root = tmp_path / "tts-registry"
    registry = ModelRegistry(registry_root)
    service = ModelImportService(
        adapter_store=_store(),
        model_registry=registry,
        secret_store=SecretStore(registry_root),
    )
    source_package = _build_local_package(tmp_path / "source-package")

    imported = service.import_model_package(source_package, storage_mode="external")

    assert imported.storage_mode == "external"
    assert Path(imported.instance_assets["bert"]["source_path"]).resolve() == (source_package / "pretrained" / "bert.bin").resolve()
    assert registry.get_model("demo-gpt-sovits").storage_mode == "external"


def test_model_import_service_cleans_staging_and_registry_on_failure(tmp_path: Path):
    registry_root = tmp_path / "tts-registry"
    registry = ModelRegistry(registry_root)
    service = ModelImportService(
        adapter_store=_store(),
        model_registry=registry,
        secret_store=SecretStore(registry_root),
    )
    broken_package = _build_local_package(tmp_path / "broken-package")
    (broken_package / "refs" / "demo.wav").unlink()

    with pytest.raises(BlockAdapterError) as exc_info:
        service.import_model_package(broken_package)

    assert exc_info.value.error_code == "asset_missing"
    assert registry.list_models() == []
    assert not any((registry_root / "staging" / "model-import").glob("*"))
    assert not (registry_root / "registry.json").exists()
