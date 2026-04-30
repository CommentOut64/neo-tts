from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from backend.app.inference.block_adapter_types import AdapterCapabilities


RuntimeKind = Literal["local_in_process", "local_http", "external_http"]


class AdapterBlockLimits(BaseModel):
    max_block_seconds: int | None = Field(default=None, ge=1, description="adapter 可接受最大 block 时长。")
    max_block_chars: int | None = Field(default=None, ge=1, description="adapter 可接受最大字符数。")
    max_segment_count: int | None = Field(default=None, ge=1, description="adapter 可接受最大段数。")
    max_payload_bytes: int | None = Field(default=None, ge=1, description="adapter 可接受最大 payload。")


class AssetTopology(BaseModel):
    instance_assets: list[str] = Field(default_factory=list, description="属于 ModelInstance 的资产键。")
    preset_assets: list[str] = Field(default_factory=list, description="属于 ModelPreset 的资产键。")


class OverridePolicy(BaseModel):
    overridable_assets: list[str] = Field(default_factory=list, description="允许覆盖的资产键。")
    overridable_fields: list[str] = Field(default_factory=list, description="允许覆盖的字段路径。")


class AdapterDefinition(BaseModel):
    adapter_id: str = Field(description="adapter 唯一标识。")
    display_name: str = Field(description="adapter 展示名。")
    adapter_family: str = Field(description="adapter family。")
    runtime_kind: RuntimeKind = Field(description="adapter runtime 类型。")
    capabilities: AdapterCapabilities = Field(description="adapter 能力声明。")
    block_limits: AdapterBlockLimits = Field(default_factory=AdapterBlockLimits, description="block 输入限制。")
    option_schema: dict[str, Any] = Field(default_factory=dict, description="adapter options schema。")
    manifest_schema: dict[str, Any] = Field(default_factory=dict, description="模型包 manifest schema。")
    asset_topology: AssetTopology = Field(default_factory=AssetTopology, description="instance/preset 资产边界。")
    preset_schema: dict[str, Any] = Field(default_factory=dict, description="preset schema。")
    override_policy: OverridePolicy = Field(default_factory=OverridePolicy, description="用户可覆盖范围。")
    max_concurrent_renders: int | None = Field(default=None, ge=1, description="adapter 最大并发渲染数。")

    @model_validator(mode="after")
    def _validate_concurrency_contract(self) -> "AdapterDefinition":
        if self.capabilities.bounded_concurrency and self.max_concurrent_renders is None:
            raise ValueError("bounded_concurrency adapter must declare max_concurrent_renders.")
        return self
