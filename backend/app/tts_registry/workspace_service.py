from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from backend.app.schemas.edit_session import BindingReference
from backend.app.tts_registry.adapter_definition_store import AdapterDefinitionStore
from backend.app.tts_registry.secret_store import SecretStore
from backend.app.tts_registry.types import (
    BindingCatalogMainModelOption,
    BindingCatalogPresetOption,
    BindingCatalogResponse,
    BindingCatalogSubmodelOption,
    BindingCatalogWorkspaceOption,
    FamilyWorkspaceRecord,
    MainModelRecord,
    PresetRecord,
    SubmodelRecord,
    WorkspaceSummaryView,
    WorkspaceTree,
)
from backend.app.tts_registry.workspace_store import WorkspaceStore


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_identifier(value: str) -> str:
    return value.strip().lower().replace("-", "_").replace(" ", "_")


class WorkspaceService:
    def __init__(
        self,
        *,
        adapter_store: AdapterDefinitionStore,
        workspace_store: WorkspaceStore,
        secret_store: SecretStore | None = None,
    ) -> None:
        self._adapter_store = adapter_store
        self._workspace_store = workspace_store
        self._secret_store = secret_store

    def list_workspaces(self) -> list[WorkspaceSummaryView]:
        return [self.build_workspace_summary(item) for item in self._workspace_store.list_workspaces()]

    def create_workspace(
        self,
        *,
        adapter_id: str,
        family_id: str,
        display_name: str,
        slug: str,
    ) -> WorkspaceSummaryView:
        family = self._adapter_store.require_family(adapter_id, family_id)
        timestamp = _now_iso()
        workspace = FamilyWorkspaceRecord(
            workspace_id=f"ws_{_normalize_identifier(slug)}",
            adapter_id=adapter_id,
            family_id=family.family_id,
            display_name=display_name,
            slug=slug,
            status="ready",
            ui_order=len(self._workspace_store.list_workspaces()),
            created_at=timestamp,
            updated_at=timestamp,
        )
        created = self._workspace_store.create_workspace(workspace)
        return self.build_workspace_summary(created)

    def update_workspace(
        self,
        *,
        workspace_id: str,
        display_name: str | None = None,
        slug: str | None = None,
        status: str | None = None,
        ui_order: int | None = None,
    ) -> FamilyWorkspaceRecord:
        current = self._require_workspace(workspace_id)
        updated = current.model_copy(
            update={
                "display_name": display_name if display_name is not None else current.display_name,
                "slug": slug if slug is not None else current.slug,
                "status": status if status is not None else current.status,
                "ui_order": ui_order if ui_order is not None else current.ui_order,
                "updated_at": _now_iso(),
            }
        )
        return self._workspace_store.update_workspace(updated)

    def delete_workspace(self, workspace_id: str) -> None:
        if self._secret_store is not None:
            tree = self.get_workspace_tree(workspace_id)
            for main_model in tree.main_models:
                for submodel in main_model.submodels:
                    self._secret_store.delete_submodel_secrets(
                        workspace_id=workspace_id,
                        main_model_id=main_model.main_model_id,
                        submodel_id=submodel.submodel_id,
                    )
        self._workspace_store.delete_workspace(workspace_id)

    def get_workspace_tree(self, workspace_id: str) -> WorkspaceTree:
        return self._workspace_store.get_workspace_tree(workspace_id)

    def list_main_models(self, workspace_id: str) -> list[MainModelRecord]:
        return self._workspace_store.list_main_models(workspace_id)

    def create_main_model(
        self,
        *,
        workspace_id: str,
        main_model_id: str,
        display_name: str,
        source_type: str = "builtin",
        main_model_metadata: dict[str, Any] | None = None,
    ) -> MainModelRecord:
        workspace = self._require_workspace(workspace_id)
        family = self._adapter_store.require_family(workspace.adapter_id, workspace.family_id)
        timestamp = _now_iso()
        default_submodel_id = "default" if family.auto_singleton_submodel else None
        record = MainModelRecord(
            main_model_id=main_model_id,
            workspace_id=workspace_id,
            display_name=display_name,
            status="ready",
            source_type=source_type,  # type: ignore[arg-type]
            main_model_metadata=dict(main_model_metadata or {}),
            default_submodel_id=default_submodel_id,
            created_at=timestamp,
            updated_at=timestamp,
        )
        created = self._workspace_store.create_main_model(record)
        self._ensure_hidden_singletons(workspace=workspace, main_model=created)
        return created

    def update_main_model(
        self,
        *,
        workspace_id: str,
        main_model_id: str,
        display_name: str | None = None,
        status: str | None = None,
        main_model_metadata: dict[str, Any] | None = None,
        default_submodel_id: str | None = None,
    ) -> MainModelRecord:
        current = self._require_main_model(workspace_id, main_model_id)
        updated = current.model_copy(
            update={
                "display_name": display_name if display_name is not None else current.display_name,
                "status": status if status is not None else current.status,
                "main_model_metadata": (
                    dict(main_model_metadata)
                    if main_model_metadata is not None
                    else dict(current.main_model_metadata)
                ),
                "default_submodel_id": default_submodel_id if default_submodel_id is not None else current.default_submodel_id,
                "updated_at": _now_iso(),
            }
        )
        return self._workspace_store.update_main_model(updated)

    def delete_main_model(self, workspace_id: str, main_model_id: str) -> None:
        if self._secret_store is not None:
            for submodel in self._workspace_store.list_submodels(workspace_id, main_model_id):
                self._secret_store.delete_submodel_secrets(
                    workspace_id=workspace_id,
                    main_model_id=main_model_id,
                    submodel_id=submodel.submodel_id,
                )
        self._workspace_store.delete_main_model(workspace_id, main_model_id)

    def list_submodels(self, workspace_id: str, main_model_id: str) -> list[SubmodelRecord]:
        return self._workspace_store.list_submodels(workspace_id, main_model_id)

    def create_submodel(
        self,
        *,
        workspace_id: str,
        main_model_id: str,
        submodel_id: str,
        display_name: str,
        endpoint: dict[str, Any] | None = None,
        account_binding: dict[str, Any] | None = None,
        instance_assets: dict[str, Any] | None = None,
        adapter_options: dict[str, Any] | None = None,
        runtime_profile: dict[str, Any] | None = None,
        status: str = "ready",
        is_hidden_singleton: bool = False,
    ) -> SubmodelRecord:
        self._require_main_model(workspace_id, main_model_id)
        timestamp = _now_iso()
        record = SubmodelRecord(
            submodel_id=submodel_id,
            workspace_id=workspace_id,
            main_model_id=main_model_id,
            display_name=display_name,
            status=status,  # type: ignore[arg-type]
            instance_assets=dict(instance_assets or {}),
            endpoint=dict(endpoint) if endpoint is not None else None,
            account_binding=dict(account_binding) if account_binding is not None else None,
            adapter_options=dict(adapter_options or {}),
            runtime_profile=dict(runtime_profile or {}),
            is_hidden_singleton=is_hidden_singleton,
            created_at=timestamp,
            updated_at=timestamp,
        )
        created = self._workspace_store.put_submodel(record)
        self._ensure_hidden_default_preset(
            workspace_id=workspace_id,
            main_model_id=main_model_id,
            submodel=created,
        )
        return created

    def update_submodel(
        self,
        *,
        workspace_id: str,
        main_model_id: str,
        submodel_id: str,
        display_name: str | None = None,
        status: str | None = None,
        endpoint: dict[str, Any] | None = None,
        account_binding: dict[str, Any] | None = None,
        instance_assets: dict[str, Any] | None = None,
        adapter_options: dict[str, Any] | None = None,
        runtime_profile: dict[str, Any] | None = None,
    ) -> SubmodelRecord:
        current = self._require_submodel(workspace_id, main_model_id, submodel_id)
        updated = current.model_copy(
            update={
                "display_name": display_name if display_name is not None else current.display_name,
                "status": status if status is not None else current.status,
                "endpoint": dict(endpoint) if endpoint is not None else current.endpoint,
                "account_binding": dict(account_binding) if account_binding is not None else current.account_binding,
                "instance_assets": dict(instance_assets) if instance_assets is not None else dict(current.instance_assets),
                "adapter_options": dict(adapter_options) if adapter_options is not None else dict(current.adapter_options),
                "runtime_profile": dict(runtime_profile) if runtime_profile is not None else dict(current.runtime_profile),
                "updated_at": _now_iso(),
            }
        )
        return self._workspace_store.put_submodel(updated)

    def delete_submodel(self, workspace_id: str, main_model_id: str, submodel_id: str) -> None:
        if self._secret_store is not None:
            self._secret_store.delete_submodel_secrets(
                workspace_id=workspace_id,
                main_model_id=main_model_id,
                submodel_id=submodel_id,
            )
        self._workspace_store.delete_submodel(workspace_id, main_model_id, submodel_id)

    def list_presets(self, workspace_id: str, main_model_id: str, submodel_id: str) -> list[PresetRecord]:
        return self._workspace_store.list_presets(workspace_id, main_model_id, submodel_id)

    def create_preset(
        self,
        *,
        workspace_id: str,
        main_model_id: str,
        submodel_id: str,
        preset_id: str,
        display_name: str,
        kind: str = "user",
        status: str = "ready",
        defaults: dict[str, Any] | None = None,
        fixed_fields: dict[str, Any] | None = None,
        preset_assets: dict[str, Any] | None = None,
        is_hidden_singleton: bool = False,
    ) -> PresetRecord:
        self._require_submodel(workspace_id, main_model_id, submodel_id)
        timestamp = _now_iso()
        record = PresetRecord(
            preset_id=preset_id,
            workspace_id=workspace_id,
            main_model_id=main_model_id,
            submodel_id=submodel_id,
            display_name=display_name,
            status=status,  # type: ignore[arg-type]
            kind=kind,  # type: ignore[arg-type]
            defaults=dict(defaults or {}),
            fixed_fields=dict(fixed_fields or {}),
            preset_assets=dict(preset_assets or {}),
            is_hidden_singleton=is_hidden_singleton,
            created_at=timestamp,
            updated_at=timestamp,
        )
        return self._workspace_store.put_preset(record)

    def update_preset(
        self,
        *,
        workspace_id: str,
        main_model_id: str,
        submodel_id: str,
        preset_id: str,
        display_name: str | None = None,
        status: str | None = None,
        defaults: dict[str, Any] | None = None,
        fixed_fields: dict[str, Any] | None = None,
        preset_assets: dict[str, Any] | None = None,
    ) -> PresetRecord:
        current = self._require_preset(workspace_id, main_model_id, submodel_id, preset_id)
        updated = current.model_copy(
            update={
                "display_name": display_name if display_name is not None else current.display_name,
                "status": status if status is not None else current.status,
                "defaults": dict(defaults) if defaults is not None else dict(current.defaults),
                "fixed_fields": dict(fixed_fields) if fixed_fields is not None else dict(current.fixed_fields),
                "preset_assets": dict(preset_assets) if preset_assets is not None else dict(current.preset_assets),
                "updated_at": _now_iso(),
            }
        )
        return self._workspace_store.put_preset(updated)

    def delete_preset(self, workspace_id: str, main_model_id: str, submodel_id: str, preset_id: str) -> None:
        self._workspace_store.delete_preset(workspace_id, main_model_id, submodel_id, preset_id)

    def put_submodel_secrets(
        self,
        *,
        workspace_id: str,
        main_model_id: str,
        submodel_id: str,
        secrets: dict[str, str],
    ) -> SubmodelRecord:
        if self._secret_store is None:
            raise RuntimeError("Secret store is not configured.")
        submodel = self._require_submodel(workspace_id, main_model_id, submodel_id)
        handles = self._secret_store.put_submodel_secrets(
            workspace_id=workspace_id,
            main_model_id=main_model_id,
            submodel_id=submodel_id,
            secrets=secrets,
        )
        account_binding = dict(submodel.account_binding or {})
        existing_handles = dict(account_binding.get("secret_handles") or {})
        existing_handles.update(handles)
        account_binding["secret_handles"] = existing_handles
        required_secret_names = [str(item) for item in account_binding.get("required_secrets") or []]
        status = submodel.status
        if self._secret_store.has_all_submodel_secrets(
            workspace_id=workspace_id,
            main_model_id=main_model_id,
            submodel_id=submodel_id,
            required_secret_names=required_secret_names,
        ):
            status = "ready"
        updated = submodel.model_copy(
            update={
                "account_binding": account_binding,
                "status": status,
                "updated_at": _now_iso(),
            }
        )
        return self._workspace_store.put_submodel(updated)

    def build_binding_catalog(
        self,
        *,
        workspace_id: str | None = None,
        adapter_id: str | None = None,
        family_id: str | None = None,
        include_disabled: bool = False,
    ) -> BindingCatalogResponse:
        items: list[BindingCatalogWorkspaceOption] = []
        for workspace in self._workspace_store.list_workspaces():
            if workspace_id is not None and workspace.workspace_id != workspace_id:
                continue
            if adapter_id is not None and workspace.adapter_id != adapter_id:
                continue
            if family_id is not None and workspace.family_id != family_id:
                continue
            if not include_disabled and workspace.status != "ready":
                continue
            summary = self.build_workspace_summary(workspace)
            tree = self.get_workspace_tree(workspace.workspace_id)
            items.append(
                BindingCatalogWorkspaceOption(
                    workspace_id=summary.workspace_id,
                    adapter_id=summary.adapter_id,
                    family_id=summary.family_id,
                    display_name=summary.display_name,
                    slug=summary.slug,
                    status=summary.status,
                    family_display_name=summary.family_display_name,
                    family_route_slug=summary.family_route_slug,
                    binding_display_strategy=summary.binding_display_strategy,
                    main_models=[
                        BindingCatalogMainModelOption(
                            display_name=main_model.display_name,
                            main_model_id=main_model.main_model_id,
                            status=main_model.status,
                            default_submodel_id=main_model.default_submodel_id,
                            submodels=[
                                BindingCatalogSubmodelOption(
                                    display_name=submodel.display_name,
                                    submodel_id=submodel.submodel_id,
                                    status=submodel.status,
                                    is_hidden_singleton=submodel.is_hidden_singleton,
                                    presets=[
                                        BindingCatalogPresetOption(
                                            display_name=preset.display_name,
                                            preset_id=preset.preset_id,
                                            status=preset.status,
                                            is_hidden_singleton=preset.is_hidden_singleton,
                                            binding_ref={
                                                "workspace_id": workspace.workspace_id,
                                                "main_model_id": main_model.main_model_id,
                                                "submodel_id": submodel.submodel_id,
                                                "preset_id": preset.preset_id,
                                            },
                                            reference_audio_path=self._read_preset_reference_asset_path(preset),
                                            reference_text=self._read_preset_reference_text(preset),
                                            reference_language=self._read_preset_reference_language(preset),
                                            defaults=dict(preset.defaults),
                                            fixed_fields=dict(preset.fixed_fields),
                                        )
                                        for preset in submodel.presets
                                        if include_disabled or preset.status == "ready"
                                    ],
                                )
                                for submodel in main_model.submodels
                                if include_disabled or submodel.status in {"ready", "needs_secret"}
                            ],
                        )
                        for main_model in tree.main_models
                        if include_disabled or main_model.status == "ready"
                    ],
                )
            )
        return BindingCatalogResponse(items=items)

    def build_workspace_summary(self, workspace: FamilyWorkspaceRecord) -> WorkspaceSummaryView:
        family = self._adapter_store.require_family(workspace.adapter_id, workspace.family_id)
        return WorkspaceSummaryView(
            workspace_id=workspace.workspace_id,
            adapter_id=workspace.adapter_id,
            family_id=workspace.family_id,
            display_name=workspace.display_name,
            slug=workspace.slug,
            status=workspace.status,
            ui_order=workspace.ui_order,
            created_at=workspace.created_at,
            updated_at=workspace.updated_at,
            family_display_name=family.display_name,
            family_route_slug=family.route_slug,
            binding_display_strategy=family.binding_display_strategy,
        )

    def resolve_binding_reference(
        self,
        binding_ref: BindingReference | dict[str, Any],
    ) -> dict[str, Any]:
        if isinstance(binding_ref, BindingReference):
            normalized_binding_ref = binding_ref.model_dump(mode="json")
        else:
            normalized_binding_ref = dict(binding_ref)
        workspace_id = str(normalized_binding_ref["workspace_id"])
        main_model_id = str(normalized_binding_ref["main_model_id"])
        submodel_id = str(normalized_binding_ref["submodel_id"])
        preset_id = str(normalized_binding_ref["preset_id"])
        workspace = self._require_workspace(workspace_id)
        main_model = self._require_main_model(workspace_id, main_model_id)
        submodel = self._require_submodel(workspace_id, main_model_id, submodel_id)
        preset = self._require_preset(workspace_id, main_model_id, submodel_id, preset_id)
        resolved_assets = dict(submodel.instance_assets)
        resolved_assets.update(preset.preset_assets)
        voice_id = main_model_id if preset_id == "default" else f"{main_model_id}__{preset_id}"
        model_key = f"{workspace_id}:{main_model_id}:{submodel_id}"
        return {
            "workspace": workspace,
            "main_model": main_model,
            "submodel": submodel,
            "preset": preset,
            "adapter_id": workspace.adapter_id,
            "family_id": workspace.family_id,
            "voice_id": voice_id,
            "model_key": model_key,
            "model_instance_id": model_key,
            "binding_key": f"{workspace_id}:{main_model_id}:{submodel_id}:{preset_id}",
            "reference_audio_path": self._read_preset_reference_asset_path(preset),
            "reference_text": self._read_preset_reference_text(preset),
            "reference_language": self._read_preset_reference_language(preset),
            "resolved_assets": resolved_assets,
            "gpt_path": self._read_asset_path(resolved_assets, "gpt_weight"),
            "sovits_path": self._read_asset_path(resolved_assets, "sovits_weight"),
            "endpoint": dict(submodel.endpoint) if submodel.endpoint is not None else None,
            "account_binding": dict(submodel.account_binding or {}),
            "adapter_options": dict(submodel.adapter_options),
            "preset_defaults": dict(preset.defaults),
            "preset_fixed_fields": dict(preset.fixed_fields),
        }

    def _ensure_hidden_singletons(self, *, workspace: FamilyWorkspaceRecord, main_model: MainModelRecord) -> None:
        family = self._adapter_store.require_family(workspace.adapter_id, workspace.family_id)
        if not family.auto_singleton_submodel:
            return
        if self._workspace_store.get_submodel(main_model.workspace_id, main_model.main_model_id, "default") is None:
            timestamp = _now_iso()
            self._workspace_store.put_submodel(
                SubmodelRecord(
                    submodel_id="default",
                    workspace_id=main_model.workspace_id,
                    main_model_id=main_model.main_model_id,
                    display_name="default",
                    status="ready",
                    instance_assets={},
                    endpoint=None,
                    account_binding=None,
                    adapter_options={},
                    runtime_profile={},
                    is_hidden_singleton=True,
                    created_at=timestamp,
                    updated_at=timestamp,
                )
            )
        if family.auto_singleton_preset:
            self._ensure_hidden_default_preset(
                workspace_id=main_model.workspace_id,
                main_model_id=main_model.main_model_id,
                submodel=self._require_submodel(main_model.workspace_id, main_model.main_model_id, "default"),
            )

    def _ensure_hidden_default_preset(
        self,
        *,
        workspace_id: str,
        main_model_id: str,
        submodel: SubmodelRecord,
    ) -> None:
        workspace = self._require_workspace(workspace_id)
        family = self._adapter_store.require_family(workspace.adapter_id, workspace.family_id)
        if not family.auto_singleton_preset:
            return
        if self._workspace_store.get_preset(workspace_id, main_model_id, submodel.submodel_id, "default") is not None:
            return
        timestamp = _now_iso()
        self._workspace_store.put_preset(
            PresetRecord(
                preset_id="default",
                workspace_id=workspace_id,
                main_model_id=main_model_id,
                submodel_id=submodel.submodel_id,
                display_name="default",
                status="ready",
                kind="builtin",
                defaults={},
                fixed_fields={},
                preset_assets={},
                is_hidden_singleton=True,
                created_at=timestamp,
                updated_at=timestamp,
            )
        )

    def _require_workspace(self, workspace_id: str) -> FamilyWorkspaceRecord:
        workspace = self._workspace_store.get_workspace(workspace_id)
        if workspace is None:
            raise LookupError(f"Workspace '{workspace_id}' not found.")
        return workspace

    def _require_main_model(self, workspace_id: str, main_model_id: str) -> MainModelRecord:
        main_model = self._workspace_store.get_main_model(workspace_id, main_model_id)
        if main_model is None:
            raise LookupError(f"Main model '{main_model_id}' not found.")
        return main_model

    def _require_submodel(self, workspace_id: str, main_model_id: str, submodel_id: str) -> SubmodelRecord:
        submodel = self._workspace_store.get_submodel(workspace_id, main_model_id, submodel_id)
        if submodel is None:
            raise LookupError(f"Submodel '{submodel_id}' not found.")
        return submodel

    def _require_preset(
        self,
        workspace_id: str,
        main_model_id: str,
        submodel_id: str,
        preset_id: str,
    ) -> PresetRecord:
        preset = self._workspace_store.get_preset(workspace_id, main_model_id, submodel_id, preset_id)
        if preset is None:
            raise LookupError(f"Preset '{preset_id}' not found.")
        return preset

    @staticmethod
    def _read_preset_reference_asset_path(preset: PresetRecord) -> str | None:
        reference_audio = preset.preset_assets.get("reference_audio")
        if not isinstance(reference_audio, dict):
            return None
        for key in ("path", "source_path", "relative_path"):
            raw_value = reference_audio.get(key)
            if isinstance(raw_value, str) and raw_value.strip():
                return raw_value
        return None

    @staticmethod
    def _read_preset_reference_text(preset: PresetRecord) -> str | None:
        raw_value = preset.defaults.get("reference_text")
        return str(raw_value) if raw_value is not None else None

    @staticmethod
    def _read_preset_reference_language(preset: PresetRecord) -> str | None:
        raw_value = preset.defaults.get("reference_language")
        return str(raw_value) if raw_value is not None else None

    @staticmethod
    def _read_asset_path(assets: dict[str, Any], asset_key: str) -> str | None:
        raw_asset = assets.get(asset_key)
        if not isinstance(raw_asset, dict):
            return None
        for key in ("path", "source_path", "relative_path"):
            raw_value = raw_asset.get(key)
            if isinstance(raw_value, str) and raw_value.strip():
                return raw_value
        return None
