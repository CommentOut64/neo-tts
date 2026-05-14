from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field

from backend.app.tts_registry.model_import_service import ModelImportService
from backend.app.tts_registry.types import MainModelRecord, PresetRecord, SubmodelRecord
from backend.app.tts_registry.workspace_service import WorkspaceService


def _normalize_identifier(value: str) -> str:
    return value.strip().lower().replace("-", "_").replace(" ", "_")


class Qwen3TTSWorkspaceImportResult(BaseModel):
    main_model: MainModelRecord = Field(description="导入产生的主模型。")
    submodels: list[SubmodelRecord] = Field(default_factory=list, description="导入产生的子模型。")
    presets: list[PresetRecord] = Field(default_factory=list, description="导入产生的预设。")


class Qwen3TTSRegistryFacade:
    DEFAULT_SUBMODEL_ID = "default"

    def __init__(
        self,
        *,
        workspace_service: WorkspaceService,
        model_import_service: ModelImportService,
    ) -> None:
        self._workspace_service = workspace_service
        self._model_import_service = model_import_service

    def import_model_package_to_workspace(
        self,
        *,
        workspace_id: str,
        source_path: str | Path,
        storage_mode: str = "managed",
    ) -> Qwen3TTSWorkspaceImportResult:
        imported_model = self._model_import_service.import_model_package(
            source_path=source_path,
            storage_mode=storage_mode,
        )
        main_model_id = _normalize_identifier(imported_model.model_instance_id)
        main_model = self._upsert_main_model(
            workspace_id=workspace_id,
            main_model_id=main_model_id,
            display_name=imported_model.display_name,
            source_type=imported_model.source_type,
            main_model_metadata={
                "package_id": imported_model.model_instance_id,
                "storage_mode": imported_model.storage_mode,
            },
            shared_assets=imported_model.instance_assets,
        )
        submodel = self._upsert_submodel(
            workspace_id=workspace_id,
            main_model_id=main_model_id,
            submodel_id=self.DEFAULT_SUBMODEL_ID,
            display_name=self.DEFAULT_SUBMODEL_ID,
        )
        main_model = self._workspace_service.update_main_model(
            workspace_id=workspace_id,
            main_model_id=main_model_id,
            default_submodel_id=self.DEFAULT_SUBMODEL_ID,
        )
        presets = [
            self._upsert_preset(
                workspace_id=workspace_id,
                main_model_id=main_model_id,
                submodel_id=submodel.submodel_id,
                preset_id=preset.preset_id,
                display_name=preset.display_name,
                kind=preset.kind,
                defaults=preset.defaults,
                fixed_fields=preset.fixed_fields,
                preset_assets=preset.preset_assets,
            )
            for preset in imported_model.presets
        ]
        return Qwen3TTSWorkspaceImportResult(
            main_model=main_model,
            submodels=[submodel],
            presets=presets,
        )

    def _upsert_main_model(
        self,
        *,
        workspace_id: str,
        main_model_id: str,
        display_name: str,
        source_type: str,
        main_model_metadata: dict,
        shared_assets: dict,
    ) -> MainModelRecord:
        existing = next(
            (
                item
                for item in self._workspace_service.list_main_models(workspace_id)
                if item.main_model_id == main_model_id
            ),
            None,
        )
        if existing is None:
            return self._workspace_service.create_main_model(
                workspace_id=workspace_id,
                main_model_id=main_model_id,
                display_name=display_name,
                source_type=source_type,
                main_model_metadata=main_model_metadata,
                shared_assets=shared_assets,
            )
        return self._workspace_service.update_main_model(
            workspace_id=workspace_id,
            main_model_id=main_model_id,
            display_name=display_name,
            main_model_metadata=main_model_metadata,
            shared_assets=shared_assets,
        )

    def _upsert_submodel(
        self,
        *,
        workspace_id: str,
        main_model_id: str,
        submodel_id: str,
        display_name: str,
    ) -> SubmodelRecord:
        existing = next(
            (
                item
                for item in self._workspace_service.list_submodels(workspace_id, main_model_id)
                if item.submodel_id == submodel_id
            ),
            None,
        )
        if existing is None:
            return self._workspace_service.create_submodel(
                workspace_id=workspace_id,
                main_model_id=main_model_id,
                submodel_id=submodel_id,
                display_name=display_name,
                instance_assets={},
            )
        return self._workspace_service.update_submodel(
            workspace_id=workspace_id,
            main_model_id=main_model_id,
            submodel_id=submodel_id,
            display_name=display_name,
            instance_assets={},
        )

    def _upsert_preset(
        self,
        *,
        workspace_id: str,
        main_model_id: str,
        submodel_id: str,
        preset_id: str,
        display_name: str,
        kind: str,
        defaults: dict,
        fixed_fields: dict,
        preset_assets: dict,
    ) -> PresetRecord:
        existing = next(
            (
                item
                for item in self._workspace_service.list_presets(workspace_id, main_model_id, submodel_id)
                if item.preset_id == preset_id
            ),
            None,
        )
        if existing is None:
            return self._workspace_service.create_preset(
                workspace_id=workspace_id,
                main_model_id=main_model_id,
                submodel_id=submodel_id,
                preset_id=preset_id,
                display_name=display_name,
                kind=kind,
                defaults=defaults,
                fixed_fields=fixed_fields,
                preset_assets=preset_assets,
            )
        return self._workspace_service.update_preset(
            workspace_id=workspace_id,
            main_model_id=main_model_id,
            submodel_id=submodel_id,
            preset_id=preset_id,
            display_name=display_name,
            defaults=defaults,
            fixed_fields=fixed_fields,
            preset_assets=preset_assets,
        )
