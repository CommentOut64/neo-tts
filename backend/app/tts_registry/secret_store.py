from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from uuid import uuid4


class SecretStore:
    def __init__(self, root_dir: str | Path) -> None:
        self.root_dir = Path(root_dir).resolve()

    @property
    def secrets_root(self) -> Path:
        return self.root_dir / "secrets"

    def put_model_secrets(self, model_instance_id: str, secrets: dict[str, str]) -> dict[str, str]:
        if not secrets:
            return {}
        existing = self._read_secret_payload(self._legacy_secret_file(model_instance_id))
        existing.update(secrets)
        self._write_secret_payload(self._legacy_secret_file(model_instance_id), existing)
        return {key: self.build_handle(model_instance_id, key) for key in secrets}

    def put_submodel_secrets(
        self,
        *,
        workspace_id: str,
        main_model_id: str,
        submodel_id: str,
        secrets: dict[str, str],
    ) -> dict[str, str]:
        if not secrets:
            return {}
        target = self._submodel_secret_file(
            workspace_id=workspace_id,
            main_model_id=main_model_id,
            submodel_id=submodel_id,
        )
        existing = self._read_secret_payload(target)
        existing.update(secrets)
        self._write_secret_payload(target, existing)
        return {
            key: self.build_submodel_handle(
                workspace_id=workspace_id,
                main_model_id=main_model_id,
                submodel_id=submodel_id,
                secret_name=key,
            )
            for key in secrets
        }

    def resolve_handle(self, handle: str) -> str:
        parsed = self._parse_handle(handle)
        payload = self._read_secret_payload(parsed["file"])
        return payload[parsed["secret_name"]]

    def has_all_secrets(self, model_instance_id: str, required_secret_names: list[str]) -> bool:
        if not required_secret_names:
            return True
        payload = self._read_secret_payload(self._legacy_secret_file(model_instance_id))
        return all(bool(payload.get(secret_name)) for secret_name in required_secret_names)

    def has_all_submodel_secrets(
        self,
        *,
        workspace_id: str,
        main_model_id: str,
        submodel_id: str,
        required_secret_names: list[str],
    ) -> bool:
        if not required_secret_names:
            return True
        payload = self._read_secret_payload(
            self._submodel_secret_file(
                workspace_id=workspace_id,
                main_model_id=main_model_id,
                submodel_id=submodel_id,
            )
        )
        return all(bool(payload.get(secret_name)) for secret_name in required_secret_names)

    def delete_submodel_secrets(self, *, workspace_id: str, main_model_id: str, submodel_id: str) -> None:
        target = self._submodel_secret_dir(
            workspace_id=workspace_id,
            main_model_id=main_model_id,
            submodel_id=submodel_id,
        )
        if target.exists():
            shutil.rmtree(target)

    @staticmethod
    def build_handle(model_instance_id: str, secret_name: str) -> str:
        return f"secret://{model_instance_id}/{secret_name}"

    @staticmethod
    def build_submodel_handle(
        *,
        workspace_id: str,
        main_model_id: str,
        submodel_id: str,
        secret_name: str,
    ) -> str:
        return f"secret://{workspace_id}/{main_model_id}/{submodel_id}/{secret_name}"

    def _legacy_secret_dir(self, model_instance_id: str) -> Path:
        return self.secrets_root / model_instance_id

    def _legacy_secret_file(self, model_instance_id: str) -> Path:
        return self._legacy_secret_dir(model_instance_id) / "secrets.json"

    def _submodel_secret_dir(self, *, workspace_id: str, main_model_id: str, submodel_id: str) -> Path:
        return self.secrets_root / workspace_id / main_model_id / submodel_id

    def _submodel_secret_file(self, *, workspace_id: str, main_model_id: str, submodel_id: str) -> Path:
        return self._submodel_secret_dir(
            workspace_id=workspace_id,
            main_model_id=main_model_id,
            submodel_id=submodel_id,
        ) / "secrets.json"

    @staticmethod
    def _read_secret_payload(secret_file: Path) -> dict[str, str]:
        if not secret_file.exists():
            return {}
        payload = json.loads(secret_file.read_text(encoding="utf-8"))
        return {str(key): str(value) for key, value in payload.items()}

    def _write_secret_payload(self, secret_file: Path, payload: dict[str, str]) -> None:
        secret_file.parent.mkdir(parents=True, exist_ok=True)
        temp_path = secret_file.with_name(f"{secret_file.name}.tmp-{uuid4().hex}")
        temp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temp_path, secret_file)

    def _parse_handle(self, handle: str) -> dict[str, str | Path]:
        prefix = "secret://"
        if not handle.startswith(prefix):
            raise ValueError(f"Invalid secret handle '{handle}'.")
        path = handle.removeprefix(prefix)
        parts = [part for part in path.split("/") if part]
        if len(parts) == 2:
            model_instance_id, secret_name = parts
            return {
                "file": self._legacy_secret_file(model_instance_id),
                "secret_name": secret_name,
            }
        if len(parts) == 4:
            workspace_id, main_model_id, submodel_id, secret_name = parts
            return {
                "file": self._submodel_secret_file(
                    workspace_id=workspace_id,
                    main_model_id=main_model_id,
                    submodel_id=submodel_id,
                ),
                "secret_name": secret_name,
            }
        raise ValueError(f"Invalid secret handle '{handle}'.")
