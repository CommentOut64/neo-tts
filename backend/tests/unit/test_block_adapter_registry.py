import pytest

from backend.app.inference.adapter_definition import (
    AdapterBlockLimits,
    AdapterDefinition,
    AssetTopology,
    OverridePolicy,
)
from backend.app.inference.block_adapter_errors import BlockAdapterError
from backend.app.inference.block_adapter_types import AdapterCapabilities
from backend.app.inference.block_adapter_registry import AdapterRegistry


def _definition(adapter_id: str, *, option_property: str = "temperature") -> AdapterDefinition:
    return AdapterDefinition(
        adapter_id=adapter_id,
        display_name=f"{adapter_id} display",
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
        option_schema={
            "type": "object",
            "properties": {
                option_property: {"type": "number"},
            },
        },
        manifest_schema={
            "type": "object",
            "required": ["adapter_id"],
        },
        asset_topology=AssetTopology(
            instance_assets=["pretrained_base", "bert"],
            preset_assets=["gpt_weight", "sovits_weight", "reference_audio"],
        ),
        preset_schema={
            "type": "object",
            "properties": {
                "speed": {"type": "number"},
            },
        },
        override_policy=OverridePolicy(
            overridable_assets=["reference_audio"],
            overridable_fields=["reference_text", "reference_language", "synthesis.*"],
        ),
        max_concurrent_renders=1,
    )


def test_adapter_registry_registers_gets_and_lists_definitions():
    registry = AdapterRegistry()
    definition = _definition("gpt_sovits_local")

    registry.register(definition)

    assert registry.get("gpt_sovits_local") == definition
    assert registry.list_adapters() == [definition]


def test_adapter_registry_rejects_duplicate_adapter_id():
    registry = AdapterRegistry()
    registry.register(_definition("gpt_sovits_local"))

    with pytest.raises(ValueError, match="gpt_sovits_local"):
        registry.register(_definition("gpt_sovits_local"))


def test_adapter_registry_keeps_option_schema_namespaces_isolated():
    registry = AdapterRegistry()
    local_definition = _definition("gpt_sovits_local", option_property="temperature")
    remote_definition = _definition("external_http_demo", option_property="timeout_seconds")
    registry.register(local_definition)
    registry.register(remote_definition)

    assert registry.get("gpt_sovits_local").option_schema["properties"] == {
        "temperature": {"type": "number"}
    }
    assert registry.get("external_http_demo").option_schema["properties"] == {
        "timeout_seconds": {"type": "number"}
    }


def test_adapter_registry_exposes_manifest_asset_and_override_metadata():
    registry = AdapterRegistry()
    definition = _definition("gpt_sovits_local")
    registry.register(definition)

    loaded = registry.get("gpt_sovits_local")

    assert loaded.manifest_schema["required"] == ["adapter_id"]
    assert loaded.asset_topology.instance_assets == ["pretrained_base", "bert"]
    assert loaded.asset_topology.preset_assets == ["gpt_weight", "sovits_weight", "reference_audio"]
    assert loaded.preset_schema["properties"]["speed"] == {"type": "number"}
    assert loaded.override_policy.overridable_fields == ["reference_text", "reference_language", "synthesis.*"]


def test_adapter_registry_standardizes_missing_adapter_and_model_required_errors():
    registry = AdapterRegistry()

    with pytest.raises(BlockAdapterError) as missing_adapter_error:
        registry.require("missing_adapter")

    assert missing_adapter_error.value.error_code == "adapter_not_installed"
    assert missing_adapter_error.value.to_payload().model_dump(mode="json")["error_code"] == "adapter_not_installed"

    model_required = registry.build_model_required_error(adapter_id="gpt_sovits_local")

    assert model_required.error_code == "model_required"
    assert model_required.to_payload().model_dump(mode="json")["details"] == {"adapter_id": "gpt_sovits_local"}
