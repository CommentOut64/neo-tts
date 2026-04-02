from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Any


class InferenceParamsCacheStore:
    def __init__(self, *, project_root: Path, cache_file: Path) -> None:
        self._project_root = project_root
        self._cache_file = self._resolve_path(cache_file)
        self._cache_file.parent.mkdir(parents=True, exist_ok=True)

    def load(self) -> tuple[dict[str, Any], datetime] | None:
        if not self._cache_file.exists():
            return None
        payload = json.loads(self._cache_file.read_text(encoding="utf-8"))
        updated_at_raw = payload.get("updated_at")
        if not isinstance(updated_at_raw, str):
            raise ValueError("Invalid params cache format: missing updated_at.")
        updated_at = datetime.fromisoformat(updated_at_raw.replace("Z", "+00:00"))
        data = payload.get("payload")
        if not isinstance(data, dict):
            raise ValueError("Invalid params cache format: payload must be an object.")
        return data, updated_at

    def save(self, payload: dict[str, Any]) -> datetime:
        updated_at = datetime.now(UTC)
        wrapped = {
            "payload": payload,
            "updated_at": updated_at.isoformat().replace("+00:00", "Z"),
        }
        temp_file = self._cache_file.with_suffix(".tmp")
        temp_file.write_text(json.dumps(wrapped, ensure_ascii=False, indent=2), encoding="utf-8")
        temp_file.replace(self._cache_file)
        return updated_at

    def _resolve_path(self, value: Path) -> Path:
        if value.is_absolute():
            return value
        return (self._project_root / value).resolve()
