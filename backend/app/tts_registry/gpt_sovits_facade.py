from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from backend.app.tts_registry.model_import_service import ModelImportService
from backend.app.tts_registry.types import MainModelRecord, PresetRecord, SubmodelRecord
from backend.app.tts_registry.workspace_service import WorkspaceService


def _normalize_identifier(value: str) -> str:
    return value.strip().lower().replace("-", "_").replace(" ", "_")


class GPTSoVITSWorkspaceImportResult(BaseModel):
    main_model: MainModelRecord = Field(description="导入产生的主模型。")
    submodels: list[SubmodelRecord] = Field(default_factory=list, description="导入产生的子模型。")
    presets: list[PresetRecord] = Field(default_factory=list, description="导入产生的预设。")


class GPTSoVITSRegistryFacade:
    DEFAULT_MAIN_MODEL_ID = "gpt_sovits"
    DEFAULT_MAIN_MODEL_DISPLAY_NAME = "GPT-SoVITS"

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
        main_model_id: str = DEFAULT_MAIN_MODEL_ID,
        main_model_display_name: str = DEFAULT_MAIN_MODEL_DISPLAY_NAME,
    ) -> GPTSoVITSWorkspaceImportResult:
        imported_model = self._model_import_service.import_model_package(
            source_path=source_path,
            storage_mode=storage_mode,
        )
        normalized_main_model_id = _normalize_identifier(main_model_id)
        main_model = self._upsert_main_model(
            workspace_id=workspace_id,
            main_model_id=normalized_main_model_id,
            display_name=main_model_display_name,
            source_type=imported_model.source_type,
            main_model_metadata={
                "package_id": imported_model.model_instance_id,
                "storage_mode": imported_model.storage_mode,
            },
            shared_assets=imported_model.instance_assets,
        )

        submodels: list[SubmodelRecord] = []
        presets: list[PresetRecord] = []
        for preset in imported_model.presets:
            submodel_id = _normalize_identifier(preset.preset_id)
            submodel_assets = {
                asset_key: asset_payload
                for asset_key, asset_payload in preset.preset_assets.items()
                if asset_key in {"gpt_weight", "sovits_weight"}
            }
            preset_assets = {
                asset_key: asset_payload
                for asset_key, asset_payload in preset.preset_assets.items()
                if asset_key not in {"gpt_weight", "sovits_weight"}
            }
            submodel = self._upsert_submodel(
                workspace_id=workspace_id,
                main_model_id=normalized_main_model_id,
                submodel_id=submodel_id,
                display_name=preset.display_name,
                instance_assets=submodel_assets,
            )
            actual_preset = self._upsert_preset(
                workspace_id=workspace_id,
                main_model_id=normalized_main_model_id,
                submodel_id=submodel_id,
                preset_id="default",
                display_name="default",
                defaults=preset.defaults,
                fixed_fields=preset.fixed_fields,
                preset_assets=preset_assets,
            )
            submodels.append(submodel)
            presets.append(actual_preset)

        return GPTSoVITSWorkspaceImportResult(
            main_model=main_model,
            submodels=submodels,
            presets=presets,
        )

    def import_legacy_voice_to_workspace(
        self,
        *,
        workspace_id: str,
        voice_name: str,
        raw_config: dict[str, Any],
    ) -> GPTSoVITSWorkspaceImportResult:
        main_model_id = _normalize_identifier(voice_name)
        defaults = raw_config.get("defaults")
        preset_defaults = dict(defaults) if isinstance(defaults, dict) else {}
        if "reference_text" not in preset_defaults and raw_config.get("ref_text") is not None:
            preset_defaults["reference_text"] = raw_config.get("ref_text")
        if "reference_language" not in preset_defaults and raw_config.get("ref_lang") is not None:
            preset_defaults["reference_language"] = raw_config.get("ref_lang")

        preset_assets: dict[str, Any] = {}
        if raw_config.get("ref_audio"):
            preset_assets["reference_audio"] = {"path": str(raw_config.get("ref_audio"))}

        main_model = self._upsert_main_model(
            workspace_id=workspace_id,
            main_model_id=main_model_id,
            display_name=voice_name,
            source_type="local_package",
            main_model_metadata={
                "migration_source": "voices.json",
                "legacy_voice_id": voice_name,
            },
            shared_assets={},
        )
        submodel = self._upsert_submodel(
            workspace_id=workspace_id,
            main_model_id=main_model_id,
            submodel_id="default",
            display_name="default",
            instance_assets={
                "gpt_weight": {"path": str(raw_config.get("gpt_path") or "")},
                "sovits_weight": {"path": str(raw_config.get("sovits_path") or "")},
            },
        )
        preset = self._upsert_preset(
            workspace_id=workspace_id,
            main_model_id=main_model_id,
            submodel_id="default",
            preset_id="default",
            display_name="default",
            defaults=preset_defaults,
            fixed_fields={},
            preset_assets=preset_assets,
        )
        return GPTSoVITSWorkspaceImportResult(
            main_model=main_model,
            submodels=[submodel],
            presets=[preset],
        )

    def import_legacy_voices_to_workspace(
        self,
        *,
        workspace_id: str,
        voices_by_name: dict[str, Any],
    ) -> list[GPTSoVITSWorkspaceImportResult]:
        imported: list[GPTSoVITSWorkspaceImportResult] = []
        for voice_name, raw_config in voices_by_name.items():
            if not isinstance(raw_config, dict):
                continue
            imported.append(
                self.import_legacy_voice_to_workspace(
                    workspace_id=workspace_id,
                    voice_name=str(voice_name),
                    raw_config=raw_config,
                )
            )
        return imported

    def import_legacy_voices_as_submodels_to_workspace(
        self,
        *,
        workspace_id: str,
        main_model_id: str,
        main_model_display_name: str,
        voices_by_name: dict[str, Any],
    ) -> GPTSoVITSWorkspaceImportResult:
        main_model = self._upsert_main_model(
            workspace_id=workspace_id,
            main_model_id=main_model_id,
            display_name=main_model_display_name,
            source_type="local_package",
            main_model_metadata={
                "migration_source": "voices.json",
                "legacy_layout": "single_main_model_many_submodels",
            },
            shared_assets={},
        )

        submodels: list[SubmodelRecord] = []
        presets: list[PresetRecord] = []
        for voice_name, raw_config in voices_by_name.items():
            if not isinstance(raw_config, dict):
                continue
            defaults = raw_config.get("defaults")
            preset_defaults = dict(defaults) if isinstance(defaults, dict) else {}
            if "reference_text" not in preset_defaults and raw_config.get("ref_text") is not None:
                preset_defaults["reference_text"] = raw_config.get("ref_text")
            if "reference_language" not in preset_defaults and raw_config.get("ref_lang") is not None:
                preset_defaults["reference_language"] = raw_config.get("ref_lang")

            preset_assets: dict[str, Any] = {}
            if raw_config.get("ref_audio"):
                preset_assets["reference_audio"] = {"path": str(raw_config.get("ref_audio"))}

            submodel_id = _normalize_identifier(str(voice_name))
            submodel = self._upsert_submodel(
                workspace_id=workspace_id,
                main_model_id=main_model.main_model_id,
                submodel_id=submodel_id,
                display_name=str(voice_name),
                instance_assets={
                    "gpt_weight": {"path": str(raw_config.get("gpt_path") or "")},
                    "sovits_weight": {"path": str(raw_config.get("sovits_path") or "")},
                },
            )
            preset = self._upsert_preset(
                workspace_id=workspace_id,
                main_model_id=main_model.main_model_id,
                submodel_id=submodel_id,
                preset_id="default",
                display_name="default",
                defaults=preset_defaults,
                fixed_fields={},
                preset_assets=preset_assets,
            )
            submodels.append(submodel)
            presets.append(preset)

        return GPTSoVITSWorkspaceImportResult(
            main_model=main_model,
            submodels=submodels,
            presets=presets,
        )

    def restructure_workspace_to_single_main_model(
        self,
        *,
        workspace_id: str,
        target_main_model_id: str,
        target_main_model_display_name: str,
    ) -> GPTSoVITSWorkspaceImportResult:
        tree = self._workspace_service.get_workspace_tree(workspace_id)
        existing_target = next(
            (item for item in tree.main_models if item.main_model_id == target_main_model_id),
            None,
        )
        target_main_model = self._upsert_main_model(
            workspace_id=workspace_id,
            main_model_id=target_main_model_id,
            display_name=target_main_model_display_name,
            source_type="local_package",
            main_model_metadata=(
                dict(existing_target.main_model_metadata)
                if existing_target is not None
                else {
                    "migration_source": "workspace_restructure",
                    "legacy_layout": "single_main_model_many_submodels",
                }
            ),
            shared_assets=dict(existing_target.shared_assets) if existing_target is not None else {},
        )

        submodels: list[SubmodelRecord] = []
        presets: list[PresetRecord] = []
        for main_model in tree.main_models:
            if main_model.main_model_id == target_main_model_id:
                for submodel in main_model.submodels:
                    actual_submodel = self._upsert_submodel(
                        workspace_id=workspace_id,
                        main_model_id=target_main_model.main_model_id,
                        submodel_id=submodel.submodel_id,
                        display_name=submodel.display_name,
                        instance_assets=dict(submodel.instance_assets),
                    )
                    submodels.append(actual_submodel)
                    for preset in submodel.presets:
                        presets.append(
                            self._upsert_preset(
                                workspace_id=workspace_id,
                                main_model_id=target_main_model.main_model_id,
                                submodel_id=actual_submodel.submodel_id,
                                preset_id=preset.preset_id,
                                display_name=preset.display_name,
                                defaults=dict(preset.defaults),
                                fixed_fields=dict(preset.fixed_fields),
                                preset_assets=dict(preset.preset_assets),
                            )
                        )
                continue

            if len(main_model.submodels) == 1 and main_model.submodels[0].submodel_id == "default":
                source_submodel = main_model.submodels[0]
                actual_submodel = self._upsert_submodel(
                    workspace_id=workspace_id,
                    main_model_id=target_main_model.main_model_id,
                    submodel_id=main_model.main_model_id,
                    display_name=main_model.display_name,
                    instance_assets=dict(source_submodel.instance_assets),
                )
                submodels.append(actual_submodel)
                for preset in source_submodel.presets:
                    presets.append(
                        self._upsert_preset(
                            workspace_id=workspace_id,
                            main_model_id=target_main_model.main_model_id,
                            submodel_id=actual_submodel.submodel_id,
                            preset_id=preset.preset_id,
                            display_name=preset.display_name,
                            defaults=dict(preset.defaults),
                            fixed_fields=dict(preset.fixed_fields),
                            preset_assets=dict(preset.preset_assets),
                        )
                    )
                continue

            for submodel in main_model.submodels:
                actual_submodel = self._upsert_submodel(
                    workspace_id=workspace_id,
                    main_model_id=target_main_model.main_model_id,
                    submodel_id=submodel.submodel_id,
                    display_name=submodel.display_name,
                    instance_assets=dict(submodel.instance_assets),
                )
                submodels.append(actual_submodel)
                for preset in submodel.presets:
                    presets.append(
                        self._upsert_preset(
                            workspace_id=workspace_id,
                            main_model_id=target_main_model.main_model_id,
                            submodel_id=actual_submodel.submodel_id,
                            preset_id=preset.preset_id,
                            display_name=preset.display_name,
                            defaults=dict(preset.defaults),
                            fixed_fields=dict(preset.fixed_fields),
                            preset_assets=dict(preset.preset_assets),
                        )
                    )

        for main_model in tree.main_models:
            if main_model.main_model_id == target_main_model.main_model_id:
                continue
            self._workspace_service.delete_main_model(workspace_id, main_model.main_model_id)

        return GPTSoVITSWorkspaceImportResult(
            main_model=target_main_model,
            submodels=submodels,
            presets=presets,
        )

    def _upsert_main_model(
        self,
        *,
        workspace_id: str,
        main_model_id: str,
        display_name: str,
        source_type: str,
        main_model_metadata: dict[str, Any],
        shared_assets: dict[str, Any],
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
        instance_assets: dict[str, Any],
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
                instance_assets=instance_assets,
            )
        return self._workspace_service.update_submodel(
            workspace_id=workspace_id,
            main_model_id=main_model_id,
            submodel_id=submodel_id,
            display_name=display_name,
            instance_assets=instance_assets,
        )

    def _upsert_preset(
        self,
        *,
        workspace_id: str,
        main_model_id: str,
        submodel_id: str,
        preset_id: str,
        display_name: str,
        defaults: dict[str, Any],
        fixed_fields: dict[str, Any],
        preset_assets: dict[str, Any],
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
                kind="imported",
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
