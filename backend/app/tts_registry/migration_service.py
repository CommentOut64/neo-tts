from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.app.schemas.edit_session import BindingReference
from backend.app.tts_registry.workspace_service import WorkspaceService


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_identifier(value: str) -> str:
    return value.strip().lower().replace("-", "_").replace(" ", "_")


class TtsRegistryMigrationService:
    def __init__(self, *, workspace_service: WorkspaceService, registry_root: str | Path) -> None:
        self._workspace_service = workspace_service
        self._registry_root = Path(registry_root).resolve()

    @property
    def backup_root(self) -> Path:
        return self._registry_root / "_migration_backups"

    def backup_file(self, source: str | Path) -> Path:
        source_path = Path(source).resolve()
        self.backup_root.mkdir(parents=True, exist_ok=True)
        target = self.backup_root / f"{source_path.name}.{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}.bak"
        shutil.copy2(source_path, target)
        return target

    def migrate_legacy_voices_file(
        self,
        *,
        voices_config_path: str | Path,
        adapter_id: str = "gpt_sovits_local",
        family_id: str = "gpt_sovits_local_default",
    ) -> list[dict[str, Any]]:
        source = Path(voices_config_path).resolve()
        if not source.exists():
            return []
        payload = json.loads(source.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or not payload:
            return []
        self.backup_file(source)
        created_bindings: list[dict[str, Any]] = []
        workspace = self._workspace_service.create_workspace(
            adapter_id=adapter_id,
            family_id=family_id,
            display_name="Legacy GPT-SoVITS",
            slug="legacy-gpt-sovits",
        )
        for voice_name, raw_config in payload.items():
            if not isinstance(raw_config, dict):
                continue
            main_model_id = _normalize_identifier(str(voice_name))
            self._workspace_service.create_main_model(
                workspace_id=workspace.workspace_id,
                main_model_id=main_model_id,
                display_name=str(voice_name),
                source_type="local_package",
                main_model_metadata={"migration_source": "voices.json"},
            )
            defaults = raw_config.get("defaults")
            preset_defaults = dict(defaults) if isinstance(defaults, dict) else {}
            if "reference_text" not in preset_defaults and raw_config.get("ref_text") is not None:
                preset_defaults["reference_text"] = raw_config.get("ref_text")
            if "reference_language" not in preset_defaults and raw_config.get("ref_lang") is not None:
                preset_defaults["reference_language"] = raw_config.get("ref_lang")
            preset_assets: dict[str, Any] = {}
            if raw_config.get("ref_audio"):
                preset_assets["reference_audio"] = {"path": str(raw_config.get("ref_audio"))}
            self._workspace_service.update_submodel(
                workspace_id=workspace.workspace_id,
                main_model_id=main_model_id,
                submodel_id="default",
                instance_assets={
                    "gpt_weight": {"path": str(raw_config.get("gpt_path") or "")},
                    "sovits_weight": {"path": str(raw_config.get("sovits_path") or "")},
                },
            )
            self._workspace_service.create_preset(
                workspace_id=workspace.workspace_id,
                main_model_id=main_model_id,
                submodel_id="default",
                preset_id="default",
                display_name="default",
                kind="imported",
                defaults=preset_defaults,
                preset_assets=preset_assets,
                is_hidden_singleton=True,
            )
            created_bindings.append(
                {
                    "legacy_voice_id": str(voice_name),
                    "binding_ref": {
                        "workspace_id": workspace.workspace_id,
                        "main_model_id": main_model_id,
                        "submodel_id": "default",
                        "preset_id": "default",
                    },
                }
            )
        return created_bindings

    def upgrade_snapshot_binding_ref(
        self,
        *,
        voice_id: str | None,
        model_key: str | None,
        model_instance_id: str | None,
        preset_id: str | None,
    ) -> BindingReference:
        if model_key and ":" in model_key and model_instance_id:
            workspace_id, main_model_id, submodel_id = model_key.split(":", 2)
            return BindingReference(
                workspace_id=workspace_id,
                main_model_id=main_model_id or model_instance_id,
                submodel_id=submodel_id or "default",
                preset_id=preset_id or "default",
            )
        return BindingReference(
            workspace_id="legacy",
            main_model_id=str(voice_id or model_instance_id or "legacy"),
            submodel_id=str(model_key or "gpt-sovits-v2"),
            preset_id=str(preset_id or "default"),
        )
