from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from backend.app.core.settings import AppSettings
from backend.app.schemas.edit_session import BindingReference
from backend.app.tts_registry.adapter_definition_store import build_default_adapter_definition_store
from backend.app.tts_registry.gpt_sovits_facade import GPTSoVITSRegistryFacade
from backend.app.tts_registry.model_import_service import ModelImportService
from backend.app.tts_registry.model_registry import ModelRegistry
from backend.app.tts_registry.secret_store import SecretStore
from backend.app.tts_registry.workspace_service import WorkspaceService
from backend.app.tts_registry.workspace_store import WorkspaceStore

GPT_SOVITS_ADAPTER_ID = "gpt_sovits_local"
GPT_SOVITS_FAMILY_ID = "gpt_sovits_local_default"


def _normalize_identifier(value: str) -> str:
    return value.strip().lower().replace("-", "_").replace(" ", "_")


def build_workspace_service_from_settings(settings: AppSettings) -> WorkspaceService:
    registry_root = settings.tts_registry_root or (settings.user_data_root / "tts-registry")
    return WorkspaceService(
        adapter_store=build_default_adapter_definition_store(
            enable_gpt_sovits_local=getattr(settings, "gpt_sovits_adapter_installed", True),
        ),
        workspace_store=WorkspaceStore(registry_root),
        secret_store=SecretStore(registry_root),
    )


def ensure_gpt_sovits_binding_for_voice(
    *,
    settings: AppSettings,
    workspace_slug: str,
    workspace_display_name: str,
    voice_id: str,
    allow_legacy_bootstrap: bool = False,
) -> tuple[WorkspaceService, BindingReference, dict[str, object]]:
    workspace_service = build_workspace_service_from_settings(settings)
    workspace = _ensure_formal_workspace(
        workspace_service=workspace_service,
        workspace_slug=workspace_slug,
        workspace_display_name=workspace_display_name,
    )
    binding_ref = BindingReference(
        workspace_id=workspace.workspace_id,
        main_model_id=_normalize_identifier(voice_id),
        submodel_id="default",
        preset_id="default",
    )
    try:
        resolved = workspace_service.resolve_binding_reference(binding_ref)
        return workspace_service, binding_ref, resolved
    except LookupError:
        if not allow_legacy_bootstrap:
            raise LookupError(
                f"缺少正式 binding_ref '{binding_ref.workspace_id}:{binding_ref.main_model_id}:{binding_ref.submodel_id}:{binding_ref.preset_id}'。"
                " 如需从 legacy voices.json 兼容导入，请显式打开 allow_legacy_bootstrap。"
            ) from None

    raw_config = _find_legacy_voice_config(
        voices_config_path=settings.voices_config_path,
        voice_id=voice_id,
    )
    if raw_config is None:
        raise LookupError(f"缺少 legacy voice '{voice_id}'。")

    facade = GPTSoVITSRegistryFacade(
        workspace_service=workspace_service,
        model_import_service=ModelImportService(
            adapter_store=build_default_adapter_definition_store(
                enable_gpt_sovits_local=getattr(settings, "gpt_sovits_adapter_installed", True),
            ),
            model_registry=ModelRegistry(settings.tts_registry_root or (settings.user_data_root / "tts-registry")),
            secret_store=SecretStore(settings.tts_registry_root or (settings.user_data_root / "tts-registry")),
        ),
    )
    facade.import_legacy_voice_to_workspace(
        workspace_id=workspace.workspace_id,
        voice_name=voice_id,
        raw_config=raw_config,
    )
    resolved = workspace_service.resolve_binding_reference(binding_ref)
    return workspace_service, binding_ref, resolved


def _ensure_formal_workspace(
    *,
    workspace_service: WorkspaceService,
    workspace_slug: str,
    workspace_display_name: str,
):
    for workspace in workspace_service.list_workspaces():
        if workspace.slug == workspace_slug:
            return workspace
    return workspace_service.create_workspace(
        adapter_id=GPT_SOVITS_ADAPTER_ID,
        family_id=GPT_SOVITS_FAMILY_ID,
        display_name=workspace_display_name,
        slug=workspace_slug,
    )


def _find_legacy_voice_config(*, voices_config_path: str | Path, voice_id: str) -> dict[str, Any] | None:
    source = Path(voices_config_path).resolve()
    if not source.exists():
        return None
    payload = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        return None
    exact = payload.get(voice_id)
    if isinstance(exact, dict):
        return exact
    normalized_voice_id = _normalize_identifier(voice_id)
    for raw_voice_id, raw_config in payload.items():
        if _normalize_identifier(str(raw_voice_id)) == normalized_voice_id and isinstance(raw_config, dict):
            return raw_config
    return None
