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
from backend.app.tts_registry.adapter_definition_store import AdapterDefinitionStore, build_default_adapter_definition_store
from backend.app.tts_registry.model_manifest import load_model_manifest_from_package


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
    return AdapterDefinitionStore(registry)


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _valid_manifest() -> dict:
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


def test_manifest_requires_neo_tts_model_json(tmp_path: Path):
    package_root = tmp_path / "package"
    _write_text(package_root / "weights" / "demo.ckpt", "fake weight")

    with pytest.raises(BlockAdapterError) as exc_info:
        load_model_manifest_from_package(package_root, _store())

    assert exc_info.value.error_code == "manifest_missing"
    assert exc_info.value.details["manifest_name"] == "neo-tts-model.json"


def test_manifest_rejects_bare_weight_directory_without_manifest(tmp_path: Path):
    package_root = tmp_path / "package"
    _write_text(package_root / "weights" / "demo.ckpt", "fake ckpt")
    _write_text(package_root / "weights" / "demo.pth", "fake pth")

    with pytest.raises(BlockAdapterError) as exc_info:
        load_model_manifest_from_package(package_root, _store())

    assert exc_info.value.error_code == "manifest_missing"
    assert sorted(exc_info.value.details["detected_weight_files"]) == ["weights/demo.ckpt", "weights/demo.pth"]


def test_manifest_requires_installed_adapter(tmp_path: Path):
    package_root = tmp_path / "package"
    manifest = _valid_manifest()
    manifest["adapter_id"] = "missing_adapter"
    _write_json(package_root / "neo-tts-model.json", manifest)

    with pytest.raises(BlockAdapterError) as exc_info:
        load_model_manifest_from_package(package_root, _store())

    assert exc_info.value.error_code == "adapter_not_installed"
    assert exc_info.value.details["adapter_id"] == "missing_adapter"


def test_manifest_returns_adapter_not_installed_when_gpt_sovits_family_is_missing(tmp_path: Path):
    package_root = tmp_path / "package"
    _write_json(package_root / "neo-tts-model.json", _valid_manifest())

    with pytest.raises(BlockAdapterError) as exc_info:
        load_model_manifest_from_package(
            package_root,
            build_default_adapter_definition_store(enable_gpt_sovits_local=False),
        )

    assert exc_info.value.error_code == "adapter_not_installed"
    assert exc_info.value.details["adapter_id"] == "gpt_sovits_local"


def test_manifest_validates_schema_and_asset_topology(tmp_path: Path):
    package_root = tmp_path / "package"
    manifest = _valid_manifest()
    manifest["instance"]["assets"] = {"unsupported_asset": "base"}
    _write_json(package_root / "neo-tts-model.json", manifest)

    with pytest.raises(BlockAdapterError) as exc_info:
        load_model_manifest_from_package(package_root, _store())

    assert exc_info.value.error_code == "manifest_schema_invalid"
    assert exc_info.value.details["field"] == "instance.assets"
    assert exc_info.value.details["asset_key"] == "unsupported_asset"


def test_manifest_rejects_missing_asset_files(tmp_path: Path):
    package_root = tmp_path / "package"
    _write_json(package_root / "neo-tts-model.json", _valid_manifest())
    _write_text(package_root / "pretrained" / "bert.bin", "bert")
    _write_text(package_root / "weights" / "demo.ckpt", "ckpt")
    _write_text(package_root / "weights" / "demo.pth", "pth")
    # 故意不写 base 和 refs/demo.wav

    with pytest.raises(BlockAdapterError) as exc_info:
        load_model_manifest_from_package(package_root, _store())

    assert exc_info.value.error_code == "asset_missing"
    assert exc_info.value.details["asset_key"] in {"pretrained_base", "reference_audio"}


def test_manifest_parses_model_instance_presets_and_fingerprint(tmp_path: Path):
    package_root = tmp_path / "package"
    _write_json(package_root / "neo-tts-model.json", _valid_manifest())
    _write_text(package_root / "base" / "README.txt", "base data")
    _write_text(package_root / "pretrained" / "bert.bin", "bert")
    _write_text(package_root / "weights" / "demo.ckpt", "ckpt")
    _write_text(package_root / "weights" / "demo.pth", "pth")
    _write_text(package_root / "refs" / "demo.wav", "wav")

    parsed = load_model_manifest_from_package(package_root, _store())
    second = load_model_manifest_from_package(package_root, _store())

    assert parsed.package_id == "demo-gpt-sovits"
    assert parsed.model_instance.adapter_id == "gpt_sovits_local"
    assert parsed.model_instance.instance_assets["bert"]["relative_path"] == "pretrained/bert.bin"
    assert parsed.model_instance.presets[0].preset_assets["gpt_weight"]["relative_path"] == "weights/demo.ckpt"
    assert parsed.fingerprint == second.fingerprint


def test_manifest_fingerprint_changes_when_key_fields_change(tmp_path: Path):
    package_root = tmp_path / "package"
    manifest = _valid_manifest()
    _write_json(package_root / "neo-tts-model.json", manifest)
    _write_text(package_root / "base" / "README.txt", "base data")
    _write_text(package_root / "pretrained" / "bert.bin", "bert")
    _write_text(package_root / "weights" / "demo.ckpt", "ckpt")
    _write_text(package_root / "weights" / "demo.pth", "pth")
    _write_text(package_root / "refs" / "demo.wav", "wav")

    before = load_model_manifest_from_package(package_root, _store()).fingerprint
    manifest["presets"][0]["defaults"]["reference_text"] = "新的参考文本"
    _write_json(package_root / "neo-tts-model.json", manifest)
    after = load_model_manifest_from_package(package_root, _store()).fingerprint

    assert before != after
