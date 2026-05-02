from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from uuid import uuid4

from pydantic import BaseModel, Field

from backend.app.tts_registry.types import (
    FamilyWorkspaceRecord,
    MainModelNode,
    MainModelRecord,
    PresetNode,
    PresetRecord,
    SubmodelNode,
    SubmodelRecord,
    WorkspaceTree,
)


class WorkspaceIndexSnapshot(BaseModel):
    schema_version: int = Field(default=1, description="workspace index schema 版本。")
    workspace_summaries: list[FamilyWorkspaceRecord] = Field(default_factory=list, description="workspace 摘要。")
    last_migrated_at: str | None = Field(default=None, description="最近迁移时间。")
    migration_source_version: str | None = Field(default=None, description="迁移源版本。")


class WorkspaceStore:
    def __init__(self, root_dir: str | Path) -> None:
        self.root_dir = Path(root_dir).resolve()
        self._index = self._load_index()

    @property
    def index_file(self) -> Path:
        return self.root_dir / "index.json"

    @property
    def workspaces_root(self) -> Path:
        return self.root_dir / "workspaces"

    def list_workspaces(self) -> list[FamilyWorkspaceRecord]:
        return list(self._index.workspace_summaries)

    def create_workspace(self, workspace: FamilyWorkspaceRecord) -> FamilyWorkspaceRecord:
        if self.get_workspace(workspace.workspace_id) is not None:
            raise ValueError(f"Workspace '{workspace.workspace_id}' already exists.")
        self._write_workspace_record(workspace)
        summaries = [*self._index.workspace_summaries, workspace]
        summaries.sort(key=lambda item: (item.ui_order, item.workspace_id))
        self._index = self._index.model_copy(update={"workspace_summaries": summaries})
        self._write_index_atomic()
        return workspace

    def update_workspace(self, workspace: FamilyWorkspaceRecord) -> FamilyWorkspaceRecord:
        current = self.get_workspace(workspace.workspace_id)
        if current is None:
            raise LookupError(f"Workspace '{workspace.workspace_id}' not found.")
        summaries = [
            workspace if item.workspace_id == workspace.workspace_id else item
            for item in self._index.workspace_summaries
        ]
        summaries.sort(key=lambda item: (item.ui_order, item.workspace_id))
        self._index = self._index.model_copy(update={"workspace_summaries": summaries})
        self._write_workspace_record(workspace)
        self._write_index_atomic()
        return workspace

    def delete_workspace(self, workspace_id: str) -> None:
        workspace = self.get_workspace(workspace_id)
        if workspace is None:
            raise LookupError(f"Workspace '{workspace_id}' not found.")
        summaries = [item for item in self._index.workspace_summaries if item.workspace_id != workspace_id]
        self._index = self._index.model_copy(update={"workspace_summaries": summaries})
        self._write_index_atomic()
        target = self._workspace_dir(workspace_id)
        if target.exists():
            shutil.rmtree(target)

    def get_workspace(self, workspace_id: str) -> FamilyWorkspaceRecord | None:
        for workspace in self._index.workspace_summaries:
            if workspace.workspace_id == workspace_id:
                return workspace
        return None

    def list_main_models(self, workspace_id: str) -> list[MainModelRecord]:
        if self.get_workspace(workspace_id) is None:
            raise LookupError(f"Workspace '{workspace_id}' not found.")
        records: list[MainModelRecord] = []
        root = self._main_models_root(workspace_id)
        if not root.exists():
            return records
        for main_model_dir in sorted(root.glob("*")):
            main_model_file = main_model_dir / "main-model.json"
            if not main_model_file.exists():
                continue
            records.append(MainModelRecord.model_validate_json(main_model_file.read_text(encoding="utf-8")))
        return records

    def create_main_model(self, record: MainModelRecord) -> MainModelRecord:
        if self.get_workspace(record.workspace_id) is None:
            raise LookupError(f"Workspace '{record.workspace_id}' not found.")
        if self.get_main_model(record.workspace_id, record.main_model_id) is not None:
            raise ValueError(f"Main model '{record.main_model_id}' already exists.")
        self._write_main_model_record(record)
        return record

    def update_main_model(self, record: MainModelRecord) -> MainModelRecord:
        if self.get_main_model(record.workspace_id, record.main_model_id) is None:
            raise LookupError(f"Main model '{record.main_model_id}' not found.")
        self._write_main_model_record(record)
        return record

    def delete_main_model(self, workspace_id: str, main_model_id: str) -> None:
        target = self._main_model_dir(workspace_id, main_model_id)
        if not target.exists():
            raise LookupError(f"Main model '{main_model_id}' not found.")
        shutil.rmtree(target)

    def get_main_model(self, workspace_id: str, main_model_id: str) -> MainModelRecord | None:
        target = self._main_model_file(workspace_id, main_model_id)
        if not target.exists():
            return None
        return MainModelRecord.model_validate_json(target.read_text(encoding="utf-8"))

    def list_submodels(self, workspace_id: str, main_model_id: str) -> list[SubmodelRecord]:
        if self.get_main_model(workspace_id, main_model_id) is None:
            raise LookupError(f"Main model '{main_model_id}' not found.")
        records: list[SubmodelRecord] = []
        root = self._submodels_root(workspace_id, main_model_id)
        if not root.exists():
            return records
        for submodel_dir in sorted(root.glob("*")):
            submodel_file = submodel_dir / "submodel.json"
            if not submodel_file.exists():
                continue
            records.append(SubmodelRecord.model_validate_json(submodel_file.read_text(encoding="utf-8")))
        return records

    def put_submodel(self, record: SubmodelRecord) -> SubmodelRecord:
        if self.get_main_model(record.workspace_id, record.main_model_id) is None:
            raise LookupError(f"Main model '{record.main_model_id}' not found.")
        self._write_submodel_record(record)
        return record

    def get_submodel(self, workspace_id: str, main_model_id: str, submodel_id: str) -> SubmodelRecord | None:
        target = self._submodel_file(workspace_id, main_model_id, submodel_id)
        if not target.exists():
            return None
        return SubmodelRecord.model_validate_json(target.read_text(encoding="utf-8"))

    def delete_submodel(self, workspace_id: str, main_model_id: str, submodel_id: str) -> None:
        target = self._submodel_dir(workspace_id, main_model_id, submodel_id)
        if not target.exists():
            raise LookupError(f"Submodel '{submodel_id}' not found.")
        shutil.rmtree(target)

    def list_presets(self, workspace_id: str, main_model_id: str, submodel_id: str) -> list[PresetRecord]:
        if self.get_submodel(workspace_id, main_model_id, submodel_id) is None:
            raise LookupError(f"Submodel '{submodel_id}' not found.")
        records: list[PresetRecord] = []
        root = self._submodel_dir(workspace_id, main_model_id, submodel_id) / "presets"
        if not root.exists():
            return records
        for preset_file in sorted(root.glob("*.json")):
            records.append(PresetRecord.model_validate_json(preset_file.read_text(encoding="utf-8")))
        return records

    def put_preset(self, record: PresetRecord) -> PresetRecord:
        if self.get_submodel(record.workspace_id, record.main_model_id, record.submodel_id) is None:
            raise LookupError(f"Submodel '{record.submodel_id}' not found.")
        self._write_preset_record(record)
        return record

    def get_preset(
        self,
        workspace_id: str,
        main_model_id: str,
        submodel_id: str,
        preset_id: str,
    ) -> PresetRecord | None:
        target = self._preset_file(workspace_id, main_model_id, submodel_id, preset_id)
        if not target.exists():
            return None
        return PresetRecord.model_validate_json(target.read_text(encoding="utf-8"))

    def delete_preset(self, workspace_id: str, main_model_id: str, submodel_id: str, preset_id: str) -> None:
        target = self._preset_file(workspace_id, main_model_id, submodel_id, preset_id)
        if not target.exists():
            raise LookupError(f"Preset '{preset_id}' not found.")
        target.unlink()

    def list_workspace_trees(self) -> list[WorkspaceTree]:
        return [self.get_workspace_tree(workspace.workspace_id) for workspace in self.list_workspaces()]

    def get_workspace_tree(self, workspace_id: str) -> WorkspaceTree:
        workspace = self.get_workspace(workspace_id)
        if workspace is None:
            raise LookupError(f"Workspace '{workspace_id}' not found.")
        main_models = [
            self._build_main_model_node(workspace_id=workspace_id, main_model=main_model)
            for main_model in self.list_main_models(workspace_id)
        ]
        return WorkspaceTree(workspace=workspace, main_models=main_models)

    def _build_main_model_node(self, *, workspace_id: str, main_model: MainModelRecord) -> MainModelNode:
        submodels = [
            self._build_submodel_node(
                workspace_id=workspace_id,
                main_model_id=main_model.main_model_id,
                submodel=submodel,
            )
            for submodel in self.list_submodels(workspace_id, main_model.main_model_id)
        ]
        return MainModelNode(**main_model.model_dump(mode="json"), submodels=submodels)

    def _build_submodel_node(
        self,
        *,
        workspace_id: str,
        main_model_id: str,
        submodel: SubmodelRecord,
    ) -> SubmodelNode:
        presets = [
            PresetNode(**preset.model_dump(mode="json"))
            for preset in self.list_presets(workspace_id, main_model_id, submodel.submodel_id)
        ]
        return SubmodelNode(**submodel.model_dump(mode="json"), presets=presets)

    def _load_index(self) -> WorkspaceIndexSnapshot:
        if not self.index_file.exists():
            return WorkspaceIndexSnapshot()
        payload = json.loads(self.index_file.read_text(encoding="utf-8"))
        return WorkspaceIndexSnapshot.model_validate(payload)

    def _write_index_atomic(self) -> None:
        self.root_dir.mkdir(parents=True, exist_ok=True)
        self.workspaces_root.mkdir(parents=True, exist_ok=True)
        temp_path = self.index_file.with_name(f"{self.index_file.name}.tmp-{uuid4().hex}")
        temp_path.write_text(
            json.dumps(self._index.model_dump(mode="json"), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(temp_path, self.index_file)

    def _workspace_dir(self, workspace_id: str) -> Path:
        return self.workspaces_root / workspace_id

    def _workspace_file(self, workspace_id: str) -> Path:
        return self._workspace_dir(workspace_id) / "workspace.json"

    def _main_models_root(self, workspace_id: str) -> Path:
        return self._workspace_dir(workspace_id) / "main-models"

    def _main_model_dir(self, workspace_id: str, main_model_id: str) -> Path:
        return self._main_models_root(workspace_id) / main_model_id

    def _main_model_file(self, workspace_id: str, main_model_id: str) -> Path:
        return self._main_model_dir(workspace_id, main_model_id) / "main-model.json"

    def _submodels_root(self, workspace_id: str, main_model_id: str) -> Path:
        return self._main_model_dir(workspace_id, main_model_id) / "submodels"

    def _submodel_dir(self, workspace_id: str, main_model_id: str, submodel_id: str) -> Path:
        return self._submodels_root(workspace_id, main_model_id) / submodel_id

    def _submodel_file(self, workspace_id: str, main_model_id: str, submodel_id: str) -> Path:
        return self._submodel_dir(workspace_id, main_model_id, submodel_id) / "submodel.json"

    def _preset_file(self, workspace_id: str, main_model_id: str, submodel_id: str, preset_id: str) -> Path:
        return self._submodel_dir(workspace_id, main_model_id, submodel_id) / "presets" / f"{preset_id}.json"

    def _write_workspace_record(self, workspace: FamilyWorkspaceRecord) -> None:
        target = self._workspace_file(workspace.workspace_id)
        target.parent.mkdir(parents=True, exist_ok=True)
        self._write_json_atomic(target, workspace.model_dump(mode="json"))

    def _write_main_model_record(self, record: MainModelRecord) -> None:
        target = self._main_model_file(record.workspace_id, record.main_model_id)
        target.parent.mkdir(parents=True, exist_ok=True)
        self._write_json_atomic(target, record.model_dump(mode="json"))

    def _write_submodel_record(self, record: SubmodelRecord) -> None:
        target = self._submodel_file(record.workspace_id, record.main_model_id, record.submodel_id)
        target.parent.mkdir(parents=True, exist_ok=True)
        self._write_json_atomic(target, record.model_dump(mode="json"))

    def _write_preset_record(self, record: PresetRecord) -> None:
        target = self._preset_file(record.workspace_id, record.main_model_id, record.submodel_id, record.preset_id)
        target.parent.mkdir(parents=True, exist_ok=True)
        self._write_json_atomic(target, record.model_dump(mode="json"))

    @staticmethod
    def _write_json_atomic(target: Path, payload: dict) -> None:
        temp_path = target.with_name(f"{target.name}.tmp-{uuid4().hex}")
        temp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temp_path, target)
