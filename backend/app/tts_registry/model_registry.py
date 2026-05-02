from __future__ import annotations

import json
import os
from pathlib import Path
from uuid import uuid4

from pydantic import BaseModel, Field

from backend.app.inference.editable_types import fingerprint_inference_config
from backend.app.tts_registry.types import ModelInstance


class ModelRegistrySnapshot(BaseModel):
    models: list[ModelInstance] = Field(default_factory=list, description="当前全部模型实例。")


class ModelRegistry:
    def __init__(self, root_dir: str | Path) -> None:
        self.root_dir = Path(root_dir).resolve()
        self._snapshot = self._load_snapshot()

    @property
    def registry_file(self) -> Path:
        return self.root_dir / "registry.json"

    @property
    def models_root(self) -> Path:
        return self.root_dir / "models"

    @property
    def secrets_root(self) -> Path:
        return self.root_dir / "secrets"

    @property
    def import_staging_root(self) -> Path:
        return self.root_dir / "staging" / "model-import"

    def list_models(self) -> list[ModelInstance]:
        return list(self._snapshot.models)

    def get_model(self, model_instance_id: str) -> ModelInstance | None:
        for model in self._snapshot.models:
            if model.model_instance_id == model_instance_id:
                return model
        return None

    def reload(self) -> None:
        self._snapshot = self._load_snapshot()

    def replace_model(self, model: ModelInstance) -> ModelInstance:
        updated_model = model.model_copy(update={"fingerprint": _build_model_fingerprint(model)})
        self.upsert_model(updated_model)
        return updated_model

    def replace_models(self, models: list[ModelInstance]) -> None:
        self._snapshot = ModelRegistrySnapshot(models=models)
        self._write_snapshot_atomic()

    def upsert_model(self, model: ModelInstance) -> None:
        models = [item for item in self._snapshot.models if item.model_instance_id != model.model_instance_id]
        models.append(model)
        models.sort(key=lambda item: item.model_instance_id)
        self.replace_models(models)

    def delete_model(self, model_instance_id: str) -> None:
        target = self.get_model(model_instance_id)
        if target is None:
            raise LookupError(f"Model '{model_instance_id}' not found.")
        models = [item for item in self._snapshot.models if item.model_instance_id != model_instance_id]
        self.replace_models(models)
        shutil_target = self.models_root / model_instance_id
        if shutil_target.exists():
            import shutil

            shutil.rmtree(shutil_target, ignore_errors=False)
        secret_dir = self.secrets_root / model_instance_id
        if secret_dir.exists():
            import shutil

            shutil.rmtree(secret_dir, ignore_errors=False)

    def model_package_root(self, model_instance_id: str) -> Path:
        return self.models_root / model_instance_id / "package"

    def new_import_staging_dir(self) -> Path:
        staging_dir = self.import_staging_root / f"import-{uuid4().hex}"
        staging_dir.mkdir(parents=True, exist_ok=False)
        return staging_dir

    def _load_snapshot(self) -> ModelRegistrySnapshot:
        if not self.registry_file.exists():
            return ModelRegistrySnapshot()
        payload = json.loads(self.registry_file.read_text(encoding="utf-8"))
        return ModelRegistrySnapshot.model_validate(payload)

    def _write_snapshot_atomic(self) -> None:
        self.registry_file.parent.mkdir(parents=True, exist_ok=True)
        self.models_root.mkdir(parents=True, exist_ok=True)
        self.secrets_root.mkdir(parents=True, exist_ok=True)
        self.import_staging_root.mkdir(parents=True, exist_ok=True)
        temp_path = self.registry_file.with_name(f"{self.registry_file.name}.tmp-{uuid4().hex}")
        temp_path.write_text(
            json.dumps(self._snapshot.model_dump(mode="json"), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(temp_path, self.registry_file)


def _build_model_fingerprint(model: ModelInstance) -> str:
    return fingerprint_inference_config(
        {
            "model_instance_id": model.model_instance_id,
            "adapter_id": model.adapter_id,
            "source_type": model.source_type,
            "display_name": model.display_name,
            "status": model.status,
            "storage_mode": model.storage_mode,
            "instance_assets": model.instance_assets,
            "endpoint": model.endpoint,
            "account_binding": model.account_binding,
            "adapter_options": model.adapter_options,
            "presets": [preset.model_dump(mode="json") for preset in model.presets],
        }
    )
