from __future__ import annotations

import shutil
from pathlib import Path

from backend.app.inference.block_adapter_errors import BlockAdapterError
from backend.app.tts_registry.adapter_definition_store import AdapterDefinitionStore
from backend.app.tts_registry.model_manifest import ParsedModelManifest, load_model_manifest_from_package
from backend.app.tts_registry.model_registry import ModelRegistry
from backend.app.tts_registry.secret_store import SecretStore
from backend.app.tts_registry.types import ModelInstance


class ModelImportService:
    def __init__(
        self,
        *,
        adapter_store: AdapterDefinitionStore,
        model_registry: ModelRegistry,
        secret_store: SecretStore,
    ) -> None:
        self._adapter_store = adapter_store
        self._model_registry = model_registry
        self._secret_store = secret_store

    def import_model_package(
        self,
        source_path: str | Path,
        *,
        storage_mode: str = "managed",
    ) -> ModelInstance:
        if storage_mode not in {"managed", "external"}:
            raise ValueError(f"Unsupported storage_mode '{storage_mode}'.")

        source_path = Path(source_path).resolve()
        staging_dir = self._model_registry.new_import_staging_dir()
        staged_package_root = staging_dir / "package"
        try:
            self._materialize_source_to_staging(source_path=source_path, staging_package_root=staged_package_root)
            staged_manifest = load_model_manifest_from_package(staged_package_root, self._adapter_store)
            if storage_mode == "managed":
                persisted_manifest = self._persist_managed_package(staged_manifest)
            else:
                if source_path.is_file():
                    raise ValueError("Archive source cannot use external storage mode.")
                persisted_manifest = load_model_manifest_from_package(source_path, self._adapter_store)
            imported_model = persisted_manifest.model_instance.model_copy(update={"storage_mode": storage_mode})
            self._model_registry.upsert_model(imported_model)
            return imported_model
        finally:
            shutil.rmtree(staging_dir, ignore_errors=False)

    def put_model_secrets(self, model_instance_id: str, secrets: dict[str, str]) -> ModelInstance:
        model = self._model_registry.get_model(model_instance_id)
        if model is None:
            raise BlockAdapterError(
                error_code="model_required",
                message=f"模型实例 '{model_instance_id}' 不存在。",
                details={"model_instance_id": model_instance_id},
            )

        handles = self._secret_store.put_model_secrets(model_instance_id, secrets)
        account_binding = dict(model.account_binding or {})
        existing_handles = dict(account_binding.get("secret_handles") or {})
        existing_handles.update(handles)
        account_binding["secret_handles"] = existing_handles

        required_secret_names = [str(item) for item in account_binding.get("required_secrets") or []]
        status = model.status
        if self._secret_store.has_all_secrets(model_instance_id, required_secret_names):
            status = "ready"

        updated_model = model.model_copy(
            update={
                "account_binding": account_binding,
                "status": status,
            }
        )
        self._model_registry.upsert_model(updated_model)
        return updated_model

    def _persist_managed_package(self, staged_manifest: ParsedModelManifest) -> ParsedModelManifest:
        target_package_root = self._model_registry.model_package_root(staged_manifest.package_id)
        if target_package_root.parent.exists():
            shutil.rmtree(target_package_root.parent, ignore_errors=False)
        target_package_root.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(staged_manifest.package_root, target_package_root)
        return load_model_manifest_from_package(target_package_root, self._adapter_store)

    @staticmethod
    def _materialize_source_to_staging(*, source_path: Path, staging_package_root: Path) -> None:
        if source_path.is_dir():
            shutil.copytree(source_path, staging_package_root)
            return
        if source_path.is_file():
            staging_package_root.mkdir(parents=True, exist_ok=False)
            shutil.unpack_archive(str(source_path), str(staging_package_root))
            return
        raise FileNotFoundError(f"Model source path not found: {source_path}")
