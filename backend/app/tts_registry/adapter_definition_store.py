from __future__ import annotations

import os
from pathlib import Path

from backend.app.inference.adapter_definition import (
    AdapterBlockLimits,
    AdapterDefinition,
    AssetTopology,
    OverridePolicy,
)
from backend.app.inference.block_adapter_registry import AdapterRegistry
from backend.app.inference.block_adapter_types import AdapterCapabilities


class AdapterDefinitionStore:
    def __init__(self, registry: AdapterRegistry | None = None) -> None:
        self._registry = registry or AdapterRegistry()

    def get(self, adapter_id: str) -> AdapterDefinition | None:
        return self._registry.get(adapter_id)

    def require(self, adapter_id: str) -> AdapterDefinition:
        return self._registry.require(adapter_id)

    def list_definitions(self) -> list[AdapterDefinition]:
        return self._registry.list_adapters()


def build_default_adapter_definition_store(
    *,
    enable_gpt_sovits_local: bool | None = None,
) -> AdapterDefinitionStore:
    registry = AdapterRegistry()
    if _should_enable_gpt_sovits_local(enable_gpt_sovits_local):
        registry.register(
            AdapterDefinition(
                adapter_id="gpt_sovits_local",
                display_name="GPT-SoVITS Local",
                adapter_family="gpt_sovits",
                runtime_kind="local_in_process",
                capabilities=AdapterCapabilities(
                    block_render=True,
                    exact_segment_output=True,
                    segment_level_voice_binding=True,
                    incremental_render=True,
                    local_gpu_runtime=True,
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
                    instance_assets=["pretrained_base", "bert", "hubert"],
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
                    overridable_assets=["gpt_weight", "sovits_weight", "reference_audio"],
                    overridable_fields=["reference_text", "reference_language", "synthesis.*"],
                ),
                max_concurrent_renders=1,
            )
        )
    registry.register(
        AdapterDefinition(
            adapter_id="external_http_tts",
            display_name="External HTTP TTS",
            adapter_family="external_http",
            runtime_kind="external_http",
            capabilities=AdapterCapabilities(
                block_render=True,
                external_http_api=True,
                remote_runtime=True,
            ),
            block_limits=AdapterBlockLimits(max_payload_bytes=1024 * 1024),
            option_schema={
                "type": "object",
                "properties": {
                    "max_concurrent_requests": {"type": "integer", "minimum": 1},
                    "requests_per_minute": {"type": ["integer", "null"], "minimum": 1},
                    "tokens_per_minute": {"type": ["integer", "null"], "minimum": 1},
                    "retry_on_429": {"type": "boolean"},
                    "max_retry_attempts": {"type": "integer", "minimum": 0},
                    "default_retry_backoff_ms": {"type": "integer", "minimum": 0},
                    "max_retry_backoff_ms": {"type": "integer", "minimum": 0},
                    "acquire_timeout_ms": {"type": "integer", "minimum": 1},
                },
            },
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
                    "defaults": {"type": "object"},
                    "fixed_fields": {"type": "object"},
                },
            },
            override_policy=OverridePolicy(),
            max_concurrent_renders=1,
        )
    )
    return AdapterDefinitionStore(registry)


def _should_enable_gpt_sovits_local(explicit: bool | None) -> bool:
    if explicit is not None:
        return explicit
    gpt_sovits_root_env = os.environ.get("NEO_TTS_GPT_SOVITS_ROOT")
    if gpt_sovits_root_env:
        return Path(gpt_sovits_root_env).resolve().is_dir()
    resources_root_env = os.environ.get("NEO_TTS_APP_CORE_ROOT") or os.environ.get("NEO_TTS_RESOURCES_ROOT")
    base_root = Path(resources_root_env).resolve() if resources_root_env else Path(__file__).resolve().parents[3]
    return (base_root / "GPT_SoVITS").resolve().is_dir()
