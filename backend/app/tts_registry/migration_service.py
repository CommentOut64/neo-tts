from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TYPE_CHECKING

from backend.app.schemas.edit_session import BindingReference

if TYPE_CHECKING:
    from backend.app.tts_registry.workspace_service import WorkspaceService


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_identifier(value: str) -> str:
    return value.strip().lower().replace("-", "_").replace(" ", "_")


class TtsRegistryMigrationService:
    def __init__(self, *, workspace_service: "WorkspaceService", registry_root: str | Path) -> None:
        self._workspace_service = workspace_service
        self._registry_root = Path(registry_root).resolve()

    @property
    def backup_root(self) -> Path:
        return self._registry_root / "_migration_backups"

    @property
    def legacy_binding_map_file(self) -> Path:
        return self._registry_root / "legacy-binding-map.json"

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
        workspace = self._ensure_legacy_workspace(adapter_id=adapter_id, family_id=family_id)
        legacy_binding_map = self._load_legacy_binding_map()
        for voice_name, raw_config in payload.items():
            if not isinstance(raw_config, dict):
                continue
            main_model_id = _normalize_identifier(str(voice_name))
            self._upsert_legacy_main_model(
                workspace_id=workspace.workspace_id,
                main_model_id=main_model_id,
                voice_name=str(voice_name),
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
            binding_ref = self._upsert_legacy_default_preset(
                workspace_id=workspace.workspace_id,
                main_model_id=main_model_id,
                preset_defaults=preset_defaults,
                preset_assets=preset_assets,
            )
            binding_payload = binding_ref.model_dump(mode="json")
            legacy_binding_map[str(voice_name)] = binding_payload
            created_bindings.append(
                {
                    "legacy_voice_id": str(voice_name),
                    "binding_ref": binding_payload,
                }
            )
        self._write_legacy_binding_map(legacy_binding_map)
        return created_bindings

    def resolve_legacy_binding_ref(
        self,
        binding_ref: BindingReference | dict[str, Any],
    ) -> BindingReference | None:
        normalized = binding_ref if isinstance(binding_ref, BindingReference) else BindingReference.model_validate(binding_ref)
        legacy_binding_map = self._load_legacy_binding_map()
        resolved = legacy_binding_map.get(normalized.main_model_id)
        if resolved is None:
            return None
        return BindingReference.model_validate(resolved)

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

    def _ensure_legacy_workspace(self, *, adapter_id: str, family_id: str):
        existing = next(
            (
                workspace
                for workspace in self._workspace_service.list_workspaces()
                if workspace.slug == "legacy-gpt-sovits"
            ),
            None,
        )
        if existing is not None:
            return existing
        return self._workspace_service.create_workspace(
            adapter_id=adapter_id,
            family_id=family_id,
            display_name="Legacy GPT-SoVITS",
            slug="legacy-gpt-sovits",
        )

    def _upsert_legacy_main_model(self, *, workspace_id: str, main_model_id: str, voice_name: str) -> None:
        existing = next(
            (
                item
                for item in self._workspace_service.list_main_models(workspace_id)
                if item.main_model_id == main_model_id
            ),
            None,
        )
        if existing is None:
            self._workspace_service.create_main_model(
                workspace_id=workspace_id,
                main_model_id=main_model_id,
                display_name=voice_name,
                source_type="local_package",
                main_model_metadata={"migration_source": "voices.json"},
            )
            return
        self._workspace_service.update_main_model(
            workspace_id=workspace_id,
            main_model_id=main_model_id,
            display_name=voice_name,
            main_model_metadata={"migration_source": "voices.json"},
        )

    def _upsert_legacy_default_preset(
        self,
        *,
        workspace_id: str,
        main_model_id: str,
        preset_defaults: dict[str, Any],
        preset_assets: dict[str, Any],
    ) -> BindingReference:
        existing = next(
            (
                item
                for item in self._workspace_service.list_presets(workspace_id, main_model_id, "default")
                if item.preset_id == "default"
            ),
            None,
        )
        if existing is None:
            self._workspace_service.create_preset(
                workspace_id=workspace_id,
                main_model_id=main_model_id,
                submodel_id="default",
                preset_id="default",
                display_name="default",
                kind="imported",
                defaults=preset_defaults,
                preset_assets=preset_assets,
                is_hidden_singleton=True,
            )
        else:
            self._workspace_service.update_preset(
                workspace_id=workspace_id,
                main_model_id=main_model_id,
                submodel_id="default",
                preset_id="default",
                display_name="default",
                defaults=preset_defaults,
                preset_assets=preset_assets,
            )
        return BindingReference(
            workspace_id=workspace_id,
            main_model_id=main_model_id,
            submodel_id="default",
            preset_id="default",
        )

    def _load_legacy_binding_map(self) -> dict[str, dict[str, Any]]:
        if not self.legacy_binding_map_file.exists():
            return {}
        payload = json.loads(self.legacy_binding_map_file.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            return {}
        return {
            str(key): value
            for key, value in payload.items()
            if isinstance(value, dict)
        }

    def _write_legacy_binding_map(self, payload: dict[str, dict[str, Any]]) -> None:
        self.legacy_binding_map_file.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self.legacy_binding_map_file.with_name(
            f"{self.legacy_binding_map_file.name}.{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')}.tmp"
        )
        temp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temp_path.replace(self.legacy_binding_map_file)
