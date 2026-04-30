from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from backend.app.inference.adapter_definition import OverridePolicy
from backend.app.inference.block_adapter_types import ResolvedModelBinding


ModelSourceType = Literal["local_package", "external_api", "builtin"]
ModelInstanceStatus = Literal["ready", "needs_secret", "invalid", "disabled", "pending_delete"]
ModelStorageMode = Literal["managed", "external"]
ModelPresetKind = Literal["builtin", "imported", "remote", "user"]
ModelPresetStatus = Literal["ready", "invalid", "disabled", "pending_delete"]


class ModelPreset(BaseModel):
    preset_id: str = Field(description="预设 ID。")
    display_name: str = Field(description="预设展示名。")
    kind: ModelPresetKind = Field(description="预设来源类别。")
    status: ModelPresetStatus = Field(default="ready", description="预设当前状态。")
    base_preset_id: str | None = Field(default=None, description="派生预设的基础 preset ID。")
    fixed_fields: dict[str, Any] = Field(default_factory=dict, description="不可覆盖的固定字段。")
    defaults: dict[str, Any] = Field(default_factory=dict, description="可覆盖的默认参数。")
    preset_assets: dict[str, Any] = Field(default_factory=dict, description="预设资产映射。")
    override_policy: OverridePolicy = Field(default_factory=OverridePolicy, description="预设覆盖策略。")
    fingerprint: str = Field(description="预设稳定指纹。")


class ModelInstance(BaseModel):
    model_instance_id: str = Field(description="模型实例 ID。")
    adapter_id: str = Field(description="所属 adapter ID。")
    source_type: ModelSourceType = Field(description="实例来源类型。")
    display_name: str = Field(description="实例展示名。")
    status: ModelInstanceStatus = Field(default="ready", description="实例当前状态。")
    storage_mode: ModelStorageMode = Field(default="managed", description="实例存储模式。")
    instance_assets: dict[str, Any] = Field(default_factory=dict, description="实例级资产映射。")
    endpoint: dict[str, Any] | None = Field(default=None, description="外部 API endpoint 定义。")
    account_binding: dict[str, Any] | None = Field(default=None, description="账号绑定信息。")
    presets: list[ModelPreset] = Field(default_factory=list, description="实例下全部预设。")
    fingerprint: str = Field(description="模型实例稳定指纹。")


__all__ = [
    "ModelInstance",
    "ModelPreset",
    "ModelSourceType",
    "ModelInstanceStatus",
    "ModelStorageMode",
    "ModelPresetKind",
    "ModelPresetStatus",
    "ResolvedModelBinding",
]
