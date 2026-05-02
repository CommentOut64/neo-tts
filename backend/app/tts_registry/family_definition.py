from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


FieldVisibility = Literal["required", "optional", "advanced", "hidden"]
FieldInputKind = Literal["text", "textarea", "number", "select", "password", "switch"]
BindingDisplayStrategy = Literal["cascader", "selector_triplet"]


class RegistryFieldDefinition(BaseModel):
    field_key: str = Field(description="字段键。")
    label: str = Field(description="字段展示名。")
    scope: Literal["workspace", "main_model", "submodel", "preset"] = Field(description="字段作用域。")
    visibility: FieldVisibility = Field(description="字段可见性。")
    input_kind: FieldInputKind = Field(description="字段输入类型。")
    required: bool = Field(default=False, description="是否必填。")
    default_value: Any = Field(default=None, description="默认值。")
    validation: dict[str, Any] = Field(default_factory=dict, description="字段校验规则。")
    secret_name: str | None = Field(default=None, description="若为密钥字段，则为对应 secret 名称。")
    help_text: str | None = Field(default=None, description="字段说明。")


class FamilyDefinition(BaseModel):
    family_id: str = Field(description="family 唯一标识。")
    adapter_id: str = Field(description="所属 adapter。")
    display_name: str = Field(description="family 展示名。")
    route_slug: str = Field(description="family 页面路由 slug。")
    supports_main_models: bool = Field(default=True, description="是否显式暴露主模型。")
    supports_submodels: bool = Field(default=True, description="是否显式暴露子模型。")
    supports_presets: bool = Field(default=True, description="是否显式暴露预设。")
    auto_singleton_submodel: bool = Field(default=False, description="是否自动生成隐藏 default 子模型。")
    auto_singleton_preset: bool = Field(default=False, description="是否自动生成隐藏 default 预设。")
    workspace_form_schema: list[RegistryFieldDefinition] = Field(default_factory=list, description="workspace 表单 schema。")
    main_model_form_schema: list[RegistryFieldDefinition] = Field(default_factory=list, description="主模型表单 schema。")
    submodel_form_schema: list[RegistryFieldDefinition] = Field(default_factory=list, description="子模型表单 schema。")
    preset_form_schema: list[RegistryFieldDefinition] = Field(default_factory=list, description="预设表单 schema。")
    binding_display_strategy: BindingDisplayStrategy = Field(
        default="selector_triplet",
        description="工作区内展示 binding 选择器的策略。",
    )
