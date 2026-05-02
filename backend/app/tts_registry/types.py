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
WorkspaceStatus = Literal["ready", "disabled", "invalid", "pending_delete"]
MainModelStatus = Literal["ready", "disabled", "invalid", "pending_delete"]
SubmodelStatus = Literal["ready", "needs_secret", "invalid", "disabled", "pending_delete"]
PresetStatus = Literal["ready", "invalid", "disabled", "pending_delete"]


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
    adapter_options: dict[str, Any] = Field(default_factory=dict, description="adapter 运行时选项。")
    presets: list[ModelPreset] = Field(default_factory=list, description="实例下全部预设。")
    fingerprint: str = Field(description="模型实例稳定指纹。")


class FamilyWorkspaceRecord(BaseModel):
    workspace_id: str = Field(description="workspace ID。")
    adapter_id: str = Field(description="adapter ID。")
    family_id: str = Field(description="family ID。")
    display_name: str = Field(description="workspace 展示名。")
    slug: str = Field(description="workspace slug。")
    status: WorkspaceStatus = Field(default="ready", description="workspace 状态。")
    ui_order: int = Field(default=0, description="UI 排序。")
    created_at: str = Field(description="创建时间。")
    updated_at: str = Field(description="更新时间。")


class WorkspaceSummaryView(FamilyWorkspaceRecord):
    family_display_name: str = Field(description="family 展示名。")
    family_route_slug: str = Field(description="family 路由 slug。")
    binding_display_strategy: str = Field(description="binding 展示策略。")


class MainModelRecord(BaseModel):
    main_model_id: str = Field(description="主模型 ID。")
    workspace_id: str = Field(description="所属 workspace。")
    display_name: str = Field(description="主模型展示名。")
    status: MainModelStatus = Field(default="ready", description="主模型状态。")
    source_type: ModelSourceType = Field(description="主模型来源。")
    main_model_metadata: dict[str, Any] = Field(default_factory=dict, description="主模型元数据。")
    shared_assets: dict[str, Any] = Field(default_factory=dict, description="主模型共享资产。")
    default_submodel_id: str | None = Field(default=None, description="默认子模型 ID。")
    created_at: str = Field(description="创建时间。")
    updated_at: str = Field(description="更新时间。")


class SubmodelRecord(BaseModel):
    submodel_id: str = Field(description="子模型 ID。")
    workspace_id: str = Field(description="所属 workspace。")
    main_model_id: str = Field(description="所属主模型。")
    display_name: str = Field(description="子模型展示名。")
    status: SubmodelStatus = Field(default="ready", description="子模型状态。")
    instance_assets: dict[str, Any] = Field(default_factory=dict, description="实例资产。")
    endpoint: dict[str, Any] | None = Field(default=None, description="子模型 endpoint。")
    account_binding: dict[str, Any] | None = Field(default=None, description="账号绑定。")
    adapter_options: dict[str, Any] = Field(default_factory=dict, description="adapter 选项。")
    runtime_profile: dict[str, Any] = Field(default_factory=dict, description="运行时配置。")
    is_hidden_singleton: bool = Field(default=False, description="是否隐藏单例节点。")
    created_at: str = Field(description="创建时间。")
    updated_at: str = Field(description="更新时间。")


class PresetRecord(BaseModel):
    preset_id: str = Field(description="预设 ID。")
    workspace_id: str = Field(description="所属 workspace。")
    main_model_id: str = Field(description="所属主模型。")
    submodel_id: str = Field(description="所属子模型。")
    display_name: str = Field(description="预设展示名。")
    status: PresetStatus = Field(default="ready", description="预设状态。")
    kind: ModelPresetKind = Field(description="预设类型。")
    defaults: dict[str, Any] = Field(default_factory=dict, description="默认参数。")
    fixed_fields: dict[str, Any] = Field(default_factory=dict, description="固定字段。")
    preset_assets: dict[str, Any] = Field(default_factory=dict, description="预设资产。")
    is_hidden_singleton: bool = Field(default=False, description="是否隐藏单例节点。")
    created_at: str = Field(description="创建时间。")
    updated_at: str = Field(description="更新时间。")


class PresetNode(PresetRecord):
    pass


class SubmodelNode(SubmodelRecord):
    presets: list[PresetNode] = Field(default_factory=list, description="子模型下的全部预设。")


class MainModelNode(MainModelRecord):
    submodels: list[SubmodelNode] = Field(default_factory=list, description="主模型下的全部子模型。")


class WorkspaceTree(BaseModel):
    workspace: FamilyWorkspaceRecord = Field(description="workspace 摘要。")
    main_models: list[MainModelNode] = Field(default_factory=list, description="树状主模型数据。")


class BindingCatalogPresetOption(BaseModel):
    display_name: str = Field(description="预设展示名。")
    preset_id: str = Field(description="预设 ID。")
    status: PresetStatus = Field(description="预设状态。")
    is_hidden_singleton: bool = Field(default=False, description="是否隐藏单例预设。")
    binding_ref: dict[str, str] = Field(default_factory=dict, description="完整 binding_ref。")
    reference_audio_path: str | None = Field(default=None, description="预设参考音频路径。")
    reference_text: str | None = Field(default=None, description="预设参考文本。")
    reference_language: str | None = Field(default=None, description="预设参考语言。")
    defaults: dict[str, Any] = Field(default_factory=dict, description="预设默认参数。")
    fixed_fields: dict[str, Any] = Field(default_factory=dict, description="预设固定字段。")


class BindingCatalogSubmodelOption(BaseModel):
    display_name: str = Field(description="子模型展示名。")
    submodel_id: str = Field(description="子模型 ID。")
    status: SubmodelStatus = Field(description="子模型状态。")
    is_hidden_singleton: bool = Field(default=False, description="是否隐藏单例子模型。")
    presets: list[BindingCatalogPresetOption] = Field(default_factory=list, description="子模型下可选预设。")


class BindingCatalogMainModelOption(BaseModel):
    display_name: str = Field(description="主模型展示名。")
    main_model_id: str = Field(description="主模型 ID。")
    status: MainModelStatus = Field(description="主模型状态。")
    default_submodel_id: str | None = Field(default=None, description="默认子模型 ID。")
    submodels: list[BindingCatalogSubmodelOption] = Field(default_factory=list, description="主模型下可选子模型。")


class BindingCatalogWorkspaceOption(BaseModel):
    workspace_id: str = Field(description="workspace ID。")
    adapter_id: str = Field(description="adapter ID。")
    family_id: str = Field(description="family ID。")
    display_name: str = Field(description="workspace 展示名。")
    slug: str = Field(description="workspace slug。")
    status: WorkspaceStatus = Field(description="workspace 状态。")
    family_display_name: str = Field(description="family 展示名。")
    family_route_slug: str = Field(description="family 路由 slug。")
    binding_display_strategy: str = Field(description="binding 展示策略。")
    main_models: list[BindingCatalogMainModelOption] = Field(default_factory=list, description="该 workspace 下的主模型选项。")


class BindingCatalogResponse(BaseModel):
    items: list[BindingCatalogWorkspaceOption] = Field(default_factory=list, description="workspace 级 binding 目录。")


__all__ = [
    "ModelInstance",
    "ModelPreset",
    "ModelSourceType",
    "ModelInstanceStatus",
    "ModelStorageMode",
    "ModelPresetKind",
    "ModelPresetStatus",
    "FamilyWorkspaceRecord",
    "WorkspaceSummaryView",
    "MainModelRecord",
    "SubmodelRecord",
    "PresetRecord",
    "PresetNode",
    "SubmodelNode",
    "MainModelNode",
    "WorkspaceTree",
    "BindingCatalogPresetOption",
    "BindingCatalogSubmodelOption",
    "BindingCatalogMainModelOption",
    "BindingCatalogWorkspaceOption",
    "BindingCatalogResponse",
    "ResolvedModelBinding",
]
