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
from backend.app.tts_registry.family_definition import FamilyDefinition, RegistryFieldDefinition


class AdapterDefinitionStore:
    def __init__(
        self,
        registry: AdapterRegistry | None = None,
        families_by_adapter: dict[str, list[FamilyDefinition]] | None = None,
    ) -> None:
        self._registry = registry or AdapterRegistry()
        self._families_by_adapter = families_by_adapter or {}

    def get(self, adapter_id: str) -> AdapterDefinition | None:
        return self._registry.get(adapter_id)

    def require(self, adapter_id: str) -> AdapterDefinition:
        return self._registry.require(adapter_id)

    def list_definitions(self) -> list[AdapterDefinition]:
        return self._registry.list_adapters()

    def list_families(self, adapter_id: str) -> list[FamilyDefinition]:
        self.require(adapter_id)
        return list(self._families_by_adapter.get(adapter_id, []))

    def require_family(self, adapter_id: str, family_id: str) -> FamilyDefinition:
        for family in self.list_families(adapter_id):
            if family.family_id == family_id:
                return family
        raise LookupError(f"Family '{family_id}' not found for adapter '{adapter_id}'.")


def build_default_adapter_definition_store(
    *,
    enable_gpt_sovits_local: bool | None = None,
) -> AdapterDefinitionStore:
    registry = AdapterRegistry()
    families_by_adapter: dict[str, list[FamilyDefinition]] = {}
    if _should_enable_gpt_sovits_local(enable_gpt_sovits_local):
        families_by_adapter["gpt_sovits_local"] = [
            FamilyDefinition(
                family_id="gpt_sovits_local_default",
                adapter_id="gpt_sovits_local",
                display_name="GPT-SoVITS Local",
                route_slug="gpt-sovits-local",
                supports_main_models=True,
                supports_submodels=False,
                supports_presets=True,
                auto_singleton_submodel=True,
                auto_singleton_preset=False,
                workspace_form_schema=[],
                main_model_form_schema=[
                    RegistryFieldDefinition(
                        field_key="display_name",
                        label="主模型名称",
                        scope="main_model",
                        visibility="required",
                        input_kind="text",
                        required=True,
                    )
                ],
                submodel_form_schema=[],
                preset_form_schema=[
                    RegistryFieldDefinition(
                        field_key="reference_text",
                        label="参考文本",
                        scope="preset",
                        visibility="optional",
                        input_kind="textarea",
                    )
                ],
            )
        ]
        registry.register(
            AdapterDefinition(
                adapter_id="gpt_sovits_local",
                display_name="GPT-SoVITS Local",
                adapter_family="gpt_sovits",
                supported_families=["gpt_sovits_local_default"],
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
            supported_families=["external_http_tts_default"],
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
    families_by_adapter["external_http_tts"] = [
        FamilyDefinition(
            family_id="external_http_tts_default",
            adapter_id="external_http_tts",
            display_name="External HTTP TTS",
            route_slug="external-http-tts",
            supports_main_models=True,
            supports_submodels=False,
            supports_presets=False,
            auto_singleton_submodel=True,
            auto_singleton_preset=True,
            workspace_form_schema=[
                RegistryFieldDefinition(
                    field_key="display_name",
                    label="工作区名称",
                    scope="workspace",
                    visibility="required",
                    input_kind="text",
                    required=True,
                ),
                RegistryFieldDefinition(
                    field_key="slug",
                    label="工作区标识",
                    scope="workspace",
                    visibility="optional",
                    input_kind="text",
                ),
            ],
            main_model_form_schema=[
                RegistryFieldDefinition(
                    field_key="display_name",
                    label="主模型名称",
                    scope="main_model",
                    visibility="required",
                    input_kind="text",
                    required=True,
                )
            ],
            submodel_form_schema=[
                RegistryFieldDefinition(
                    field_key="endpoint.url",
                    label="Endpoint URL",
                    scope="submodel",
                    visibility="required",
                    input_kind="text",
                    required=True,
                ),
                RegistryFieldDefinition(
                    field_key="api_key",
                    label="API Key",
                    scope="submodel",
                    visibility="hidden",
                    input_kind="password",
                    secret_name="api_key",
                ),
            ],
            preset_form_schema=[],
        )
    ]
    return AdapterDefinitionStore(registry, families_by_adapter)


def _should_enable_gpt_sovits_local(explicit: bool | None) -> bool:
    if explicit is not None:
        return explicit
    gpt_sovits_root_env = os.environ.get("NEO_TTS_GPT_SOVITS_ROOT")
    if gpt_sovits_root_env:
        return Path(gpt_sovits_root_env).resolve().is_dir()
    resources_root_env = os.environ.get("NEO_TTS_APP_CORE_ROOT") or os.environ.get("NEO_TTS_RESOURCES_ROOT")
    base_root = Path(resources_root_env).resolve() if resources_root_env else Path(__file__).resolve().parents[3]
    return (base_root / "GPT_SoVITS").resolve().is_dir()
