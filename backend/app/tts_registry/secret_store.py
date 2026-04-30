from __future__ import annotations

import json
import os
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
        existing = self._read_secret_payload(model_instance_id)
        existing.update(secrets)
        self._write_secret_payload(model_instance_id, existing)
        return {key: self.build_handle(model_instance_id, key) for key in secrets}

    def resolve_handle(self, handle: str) -> str:
        model_instance_id, secret_name = self._parse_handle(handle)
        payload = self._read_secret_payload(model_instance_id)
        return payload[secret_name]

    def has_all_secrets(self, model_instance_id: str, required_secret_names: list[str]) -> bool:
        if not required_secret_names:
            return True
        payload = self._read_secret_payload(model_instance_id)
        return all(bool(payload.get(secret_name)) for secret_name in required_secret_names)

    @staticmethod
    def build_handle(model_instance_id: str, secret_name: str) -> str:
        return f"secret://{model_instance_id}/{secret_name}"

    def _secret_file(self, model_instance_id: str) -> Path:
        return self.secrets_root / model_instance_id / "secrets.json"

    def _read_secret_payload(self, model_instance_id: str) -> dict[str, str]:
        secret_file = self._secret_file(model_instance_id)
        if not secret_file.exists():
            return {}
        payload = json.loads(secret_file.read_text(encoding="utf-8"))
        return {str(key): str(value) for key, value in payload.items()}

    def _write_secret_payload(self, model_instance_id: str, payload: dict[str, str]) -> None:
        secret_file = self._secret_file(model_instance_id)
        secret_file.parent.mkdir(parents=True, exist_ok=True)
        temp_path = secret_file.with_name(f"{secret_file.name}.tmp-{uuid4().hex}")
        temp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temp_path, secret_file)

    @staticmethod
    def _parse_handle(handle: str) -> tuple[str, str]:
        prefix = "secret://"
        if not handle.startswith(prefix):
            raise ValueError(f"Invalid secret handle '{handle}'.")
        model_and_name = handle.removeprefix(prefix)
        model_instance_id, separator, secret_name = model_and_name.partition("/")
        if not model_instance_id or not separator or not secret_name:
            raise ValueError(f"Invalid secret handle '{handle}'.")
        return model_instance_id, secret_name
