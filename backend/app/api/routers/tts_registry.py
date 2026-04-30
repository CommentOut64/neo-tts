from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Body, Request, status
from pydantic import BaseModel, Field

from backend.app.inference.block_adapter_errors import BlockAdapterError
from backend.app.services.voice_service import VoiceService
from backend.app.tts_registry.adapter_definition_store import AdapterDefinitionStore, build_default_adapter_definition_store
from backend.app.tts_registry.model_import_service import ModelImportService
from backend.app.tts_registry.model_registry import ModelRegistry
from backend.app.tts_registry.secret_store import SecretStore
from backend.app.tts_registry.types import ModelInstance, ModelPreset


router = APIRouter(prefix="/v1/tts-registry", tags=["tts-registry"])


class ImportModelRequest(BaseModel):
    package_path: str = Field(description="待导入模型包路径。")
    storage_mode: Literal["managed", "external"] = Field(default="managed", description="导入后的存储模式。")


class UpdateModelRequest(BaseModel):
    display_name: str | None = None
    status: Literal["ready", "needs_secret", "invalid", "disabled", "pending_delete"] | None = None


class CreatePresetRequest(BaseModel):
    preset_id: str
    display_name: str
    kind: Literal["builtin", "imported", "remote", "user"] = "user"
    status: Literal["ready", "invalid", "disabled", "pending_delete"] = "ready"
    base_preset_id: str | None = None
    fixed_fields: dict[str, Any] = Field(default_factory=dict)
    defaults: dict[str, Any] = Field(default_factory=dict)
    preset_assets: dict[str, Any] = Field(default_factory=dict)


class UpdatePresetRequest(BaseModel):
    display_name: str | None = None
    status: Literal["ready", "invalid", "disabled", "pending_delete"] | None = None
    fixed_fields: dict[str, Any] | None = None
    defaults: dict[str, Any] | None = None


class PutSecretsRequest(BaseModel):
    secrets: dict[str, str] = Field(default_factory=dict)


def _resolve_registry_root(request: Request):
    settings = request.app.state.settings
    return (settings.tts_registry_root or (settings.user_data_root / "tts-registry")).resolve()


def _build_adapter_store(request: Request) -> AdapterDefinitionStore:
    return build_default_adapter_definition_store(
        enable_gpt_sovits_local=getattr(request.app.state.settings, "gpt_sovits_adapter_installed", True),
    )


def _build_model_registry(request: Request) -> ModelRegistry:
    return ModelRegistry(_resolve_registry_root(request))


def _build_secret_store(request: Request) -> SecretStore:
    return SecretStore(_resolve_registry_root(request))


def _build_import_service(request: Request) -> ModelImportService:
    return ModelImportService(
        adapter_store=_build_adapter_store(request),
        model_registry=_build_model_registry(request),
        secret_store=_build_secret_store(request),
    )


def _collect_active_voice_ids(request: Request) -> tuple[str | None, set[str]]:
    repository = getattr(request.app.state, "edit_session_repository", None)
    if repository is None:
        return None, set()
    active_session = repository.get_active_session()
    if active_session is None or active_session.active_job_id is None:
        return None, set()

    active_voice_ids: set[str] = set()
    if active_session.initialize_request is not None and active_session.initialize_request.voice_id:
        active_voice_ids.add(active_session.initialize_request.voice_id)
    if active_session.head_snapshot_id is not None:
        snapshot = repository.get_snapshot(active_session.head_snapshot_id)
        if snapshot is not None:
            active_voice_ids.update(
                binding.voice_id
                for binding in snapshot.voice_bindings
                if binding.voice_id
            )
    return active_session.active_job_id, active_voice_ids


def _projected_voice_name(*, model_instance_id: str, preset_id: str) -> str:
    if preset_id == "default":
        return model_instance_id
    return f"{model_instance_id}__{preset_id}"


def _assert_model_not_in_use(request: Request, model: ModelInstance) -> None:
    active_job_id, active_voice_ids = _collect_active_voice_ids(request)
    if active_job_id is None:
        return
    projected_voice_ids = {
        _projected_voice_name(
            model_instance_id=model.model_instance_id,
            preset_id=preset.preset_id,
        )
        for preset in model.presets
    }
    used_voice_ids = sorted(projected_voice_ids & active_voice_ids)
    if not used_voice_ids:
        return
    raise BlockAdapterError(
        error_code="model_in_use",
        message=f"模型实例 '{model.model_instance_id}' 正被活动作业使用，暂时不能删除。",
        details={
            "model_instance_id": model.model_instance_id,
            "active_job_id": active_job_id,
            "voice_ids": used_voice_ids,
        },
    )


def _assert_preset_not_in_use(request: Request, *, model_instance_id: str, preset_id: str) -> None:
    active_job_id, active_voice_ids = _collect_active_voice_ids(request)
    if active_job_id is None:
        return
    projected_voice_id = _projected_voice_name(
        model_instance_id=model_instance_id,
        preset_id=preset_id,
    )
    if projected_voice_id not in active_voice_ids:
        return
    raise BlockAdapterError(
        error_code="preset_in_use",
        message=f"预设 '{preset_id}' 正被活动作业使用，暂时不能删除。",
        details={
            "model_instance_id": model_instance_id,
            "preset_id": preset_id,
            "active_job_id": active_job_id,
            "voice_ids": [projected_voice_id],
        },
    )


@router.get("/adapters")
def list_adapters(request: Request) -> list[dict[str, Any]]:
    return [
        definition.model_dump(mode="json")
        for definition in _build_adapter_store(request).list_definitions()
    ]


@router.get("/models", response_model=list[ModelInstance])
def list_models(request: Request) -> list[ModelInstance]:
    return _build_model_registry(request).list_models()


@router.post("/models/import", response_model=ModelInstance, status_code=status.HTTP_201_CREATED)
def import_model(request: Request, body: ImportModelRequest) -> ModelInstance:
    return _build_import_service(request).import_model_package(
        body.package_path,
        storage_mode=body.storage_mode,
    )


@router.get("/models/{model_instance_id}", response_model=ModelInstance)
def get_model(request: Request, model_instance_id: str) -> ModelInstance:
    model = _build_model_registry(request).get_model(model_instance_id)
    if model is None:
        raise LookupError(f"Model '{model_instance_id}' not found.")
    return model


@router.patch("/models/{model_instance_id}", response_model=ModelInstance)
def patch_model(request: Request, model_instance_id: str, body: UpdateModelRequest) -> ModelInstance:
    registry = _build_model_registry(request)
    model = registry.get_model(model_instance_id)
    if model is None:
        raise LookupError(f"Model '{model_instance_id}' not found.")
    updates = body.model_dump(exclude_none=True)
    return registry.replace_model(model.model_copy(update=updates))


@router.delete("/models/{model_instance_id}")
def delete_model(request: Request, model_instance_id: str) -> dict[str, str]:
    registry = _build_model_registry(request)
    model = registry.get_model(model_instance_id)
    if model is None:
        raise LookupError(f"Model '{model_instance_id}' not found.")
    _assert_model_not_in_use(request, model)
    registry.delete_model(model_instance_id)
    return {"status": "deleted", "model_instance_id": model_instance_id}


@router.get("/models/{model_instance_id}/presets", response_model=list[ModelPreset])
def list_presets(request: Request, model_instance_id: str) -> list[ModelPreset]:
    model = _build_model_registry(request).get_model(model_instance_id)
    if model is None:
        raise LookupError(f"Model '{model_instance_id}' not found.")
    return model.presets


@router.post("/models/{model_instance_id}/presets", response_model=ModelPreset, status_code=status.HTTP_201_CREATED)
def create_preset(request: Request, model_instance_id: str, body: CreatePresetRequest) -> ModelPreset:
    registry = _build_model_registry(request)
    model = registry.get_model(model_instance_id)
    if model is None:
        raise LookupError(f"Model '{model_instance_id}' not found.")
    if any(preset.preset_id == body.preset_id for preset in model.presets):
        raise ValueError(f"Preset '{body.preset_id}' already exists.")
    template_store = _build_adapter_store(request)
    definition = template_store.require(model.adapter_id)
    preset = ModelPreset(
        preset_id=body.preset_id,
        display_name=body.display_name,
        kind=body.kind,
        status=body.status,
        base_preset_id=body.base_preset_id,
        fixed_fields=body.fixed_fields,
        defaults=body.defaults,
        preset_assets=body.preset_assets,
        override_policy=definition.override_policy,
        fingerprint="pending",
    )
    updated_model = registry.replace_model(model.model_copy(update={"presets": [*model.presets, preset]}))
    return next(item for item in updated_model.presets if item.preset_id == body.preset_id)


@router.patch("/models/{model_instance_id}/presets/{preset_id}", response_model=ModelPreset)
def patch_preset(request: Request, model_instance_id: str, preset_id: str, body: UpdatePresetRequest) -> ModelPreset:
    registry = _build_model_registry(request)
    model = registry.get_model(model_instance_id)
    if model is None:
        raise LookupError(f"Model '{model_instance_id}' not found.")
    updates = body.model_dump(exclude_none=True)
    presets: list[ModelPreset] = []
    found = False
    for preset in model.presets:
        if preset.preset_id == preset_id:
            presets.append(preset.model_copy(update=updates))
            found = True
        else:
            presets.append(preset)
    if not found:
        raise LookupError(f"Preset '{preset_id}' not found.")
    updated_model = registry.replace_model(model.model_copy(update={"presets": presets}))
    return next(item for item in updated_model.presets if item.preset_id == preset_id)


@router.delete("/models/{model_instance_id}/presets/{preset_id}")
def delete_preset(request: Request, model_instance_id: str, preset_id: str) -> dict[str, str]:
    registry = _build_model_registry(request)
    model = registry.get_model(model_instance_id)
    if model is None:
        raise LookupError(f"Model '{model_instance_id}' not found.")
    if not any(preset.preset_id == preset_id for preset in model.presets):
        raise LookupError(f"Preset '{preset_id}' not found.")
    _assert_preset_not_in_use(request, model_instance_id=model_instance_id, preset_id=preset_id)
    updated_model = registry.replace_model(
        model.model_copy(update={"presets": [preset for preset in model.presets if preset.preset_id != preset_id]})
    )
    return {"status": "deleted", "model_instance_id": updated_model.model_instance_id, "preset_id": preset_id}


@router.put("/models/{model_instance_id}/secrets", response_model=ModelInstance)
def put_model_secrets(request: Request, model_instance_id: str, body: PutSecretsRequest) -> ModelInstance:
    return _build_import_service(request).put_model_secrets(model_instance_id, body.secrets)


@router.post("/reload")
def reload_registry(request: Request) -> dict[str, int | str]:
    registry = _build_model_registry(request)
    registry.reload()
    return {"status": "success", "count": len(registry.list_models())}
