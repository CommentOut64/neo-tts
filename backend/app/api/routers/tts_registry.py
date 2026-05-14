from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Query, Request, status
from pydantic import BaseModel, Field

from backend.app.tts_registry.adapter_definition_store import AdapterDefinitionStore, build_default_adapter_definition_store
from backend.app.tts_registry.binding_catalog_service import BindingCatalogService
from backend.app.tts_registry.gpt_sovits_facade import GPTSoVITSRegistryFacade
from backend.app.tts_registry.model_import_service import ModelImportService
from backend.app.tts_registry.model_registry import ModelRegistry
from backend.app.tts_registry.qwen3_tts_facade import Qwen3TTSRegistryFacade
from backend.app.tts_registry.secret_store import SecretStore
from backend.app.tts_registry.types import BindingCatalogResponse, WorkspaceSummaryView
from backend.app.tts_registry.workspace_service import WorkspaceService
from backend.app.tts_registry.workspace_store import WorkspaceStore


router = APIRouter(prefix="/v1/tts-registry", tags=["tts-registry"])


class PutSecretsRequest(BaseModel):
    secrets: dict[str, str] = Field(default_factory=dict)


class CreateWorkspaceRequest(BaseModel):
    adapter_id: str
    family_id: str
    display_name: str
    slug: str


class UpdateWorkspaceRequest(BaseModel):
    display_name: str | None = None
    slug: str | None = None
    status: Literal["ready", "disabled", "invalid", "pending_delete"] | None = None
    ui_order: int | None = None


class CreateMainModelRequest(BaseModel):
    main_model_id: str
    display_name: str
    source_type: Literal["local_package", "external_api", "builtin"] = "builtin"
    main_model_metadata: dict[str, Any] = Field(default_factory=dict)
    shared_assets: dict[str, Any] = Field(default_factory=dict)


class UpdateMainModelRequest(BaseModel):
    display_name: str | None = None
    status: Literal["ready", "disabled", "invalid", "pending_delete"] | None = None
    main_model_metadata: dict[str, Any] | None = None
    shared_assets: dict[str, Any] | None = None
    default_submodel_id: str | None = None


class CreateSubmodelRequest(BaseModel):
    submodel_id: str
    display_name: str
    status: Literal["ready", "needs_secret", "invalid", "disabled", "pending_delete"] = "ready"
    instance_assets: dict[str, Any] = Field(default_factory=dict)
    endpoint: dict[str, Any] | None = None
    account_binding: dict[str, Any] | None = None
    adapter_options: dict[str, Any] = Field(default_factory=dict)
    runtime_profile: dict[str, Any] = Field(default_factory=dict)
    is_hidden_singleton: bool = False


class UpdateSubmodelRequest(BaseModel):
    display_name: str | None = None
    status: Literal["ready", "needs_secret", "invalid", "disabled", "pending_delete"] | None = None
    instance_assets: dict[str, Any] | None = None
    endpoint: dict[str, Any] | None = None
    account_binding: dict[str, Any] | None = None
    adapter_options: dict[str, Any] | None = None
    runtime_profile: dict[str, Any] | None = None


class CreateWorkspacePresetRequest(BaseModel):
    preset_id: str
    display_name: str
    kind: Literal["builtin", "imported", "remote", "user"] = "user"
    status: Literal["ready", "invalid", "disabled", "pending_delete"] = "ready"
    defaults: dict[str, Any] = Field(default_factory=dict)
    fixed_fields: dict[str, Any] = Field(default_factory=dict)
    preset_assets: dict[str, Any] = Field(default_factory=dict)
    is_hidden_singleton: bool = False


class UpdateWorkspacePresetRequest(BaseModel):
    display_name: str | None = None
    status: Literal["ready", "invalid", "disabled", "pending_delete"] | None = None
    defaults: dict[str, Any] | None = None
    fixed_fields: dict[str, Any] | None = None
    preset_assets: dict[str, Any] | None = None


class ImportWorkspaceModelPackageRequest(BaseModel):
    source_path: str
    storage_mode: Literal["managed", "external"] = "managed"


def _resolve_registry_root(request: Request):
    settings = request.app.state.settings
    return (settings.tts_registry_root or (settings.user_data_root / "tts-registry")).resolve()


def _build_adapter_store(request: Request) -> AdapterDefinitionStore:
    return build_default_adapter_definition_store(
        enable_gpt_sovits_local=getattr(request.app.state.settings, "gpt_sovits_adapter_installed", True),
        enable_qwen3_tts_local=getattr(request.app.state.settings, "qwen3_tts_adapter_installed", False),
    )


def _build_secret_store(request: Request) -> SecretStore:
    shared = getattr(request.app.state, "secret_store", None)
    if shared is not None:
        return shared
    return SecretStore(_resolve_registry_root(request))


def _build_model_registry(request: Request) -> ModelRegistry:
    shared = getattr(request.app.state, "model_registry", None)
    if shared is not None:
        return shared
    return ModelRegistry(_resolve_registry_root(request))


def _build_workspace_service(request: Request) -> WorkspaceService:
    shared = getattr(request.app.state, "workspace_service", None)
    if shared is not None:
        return shared
    return WorkspaceService(
        adapter_store=_build_adapter_store(request),
        workspace_store=WorkspaceStore(_resolve_registry_root(request)),
        secret_store=_build_secret_store(request),
    )


def _build_binding_catalog_service(request: Request) -> BindingCatalogService:
    return BindingCatalogService(workspace_service=_build_workspace_service(request))


def _build_model_import_service(request: Request) -> ModelImportService:
    return ModelImportService(
        adapter_store=_build_adapter_store(request),
        model_registry=_build_model_registry(request),
        secret_store=_build_secret_store(request),
    )


def _build_gpt_sovits_facade(request: Request) -> GPTSoVITSRegistryFacade:
    return GPTSoVITSRegistryFacade(
        workspace_service=_build_workspace_service(request),
        model_import_service=_build_model_import_service(request),
    )


def _build_qwen3_tts_facade(request: Request) -> Qwen3TTSRegistryFacade:
    return Qwen3TTSRegistryFacade(
        workspace_service=_build_workspace_service(request),
        model_import_service=_build_model_import_service(request),
    )


@router.get("/adapters")
def list_adapters(request: Request) -> list[dict[str, Any]]:
    return [
        definition.model_dump(mode="json")
        for definition in _build_adapter_store(request).list_definitions()
    ]


@router.get("/adapters/{adapter_id}/families")
def list_adapter_families(request: Request, adapter_id: str) -> list[dict[str, Any]]:
    return [
        definition.model_dump(mode="json")
        for definition in _build_adapter_store(request).list_families(adapter_id)
    ]


@router.get("/bindings/catalog", response_model=BindingCatalogResponse)
def get_binding_catalog(
    request: Request,
    workspace_id: str | None = Query(default=None),
    adapter_id: str | None = Query(default=None),
    family_id: str | None = Query(default=None),
    include_disabled: bool = Query(default=False),
) -> BindingCatalogResponse:
    return _build_binding_catalog_service(request).get_catalog(
        workspace_id=workspace_id,
        adapter_id=adapter_id,
        family_id=family_id,
        include_disabled=include_disabled,
    )


@router.get("/workspaces", response_model=list[WorkspaceSummaryView])
def list_workspaces(request: Request) -> list[WorkspaceSummaryView]:
    return _build_workspace_service(request).list_workspaces()


@router.post("/workspaces", response_model=WorkspaceSummaryView, status_code=status.HTTP_201_CREATED)
def create_workspace(request: Request, body: CreateWorkspaceRequest) -> WorkspaceSummaryView:
    return _build_workspace_service(request).create_workspace(
        adapter_id=body.adapter_id,
        family_id=body.family_id,
        display_name=body.display_name,
        slug=body.slug,
    )


@router.post("/workspaces/{workspace_id}/imports/model-package", status_code=status.HTTP_201_CREATED)
def import_workspace_model_package(
    request: Request,
    workspace_id: str,
    body: ImportWorkspaceModelPackageRequest,
) -> dict[str, Any]:
    workspace_service = _build_workspace_service(request)
    workspace = next(item for item in workspace_service.list_workspaces() if item.workspace_id == workspace_id)
    if workspace.adapter_id == "gpt_sovits_local":
        return _build_gpt_sovits_facade(request).import_model_package_to_workspace(
            workspace_id=workspace_id,
            source_path=body.source_path,
            storage_mode=body.storage_mode,
        ).model_dump(mode="json")
    if workspace.adapter_id == "qwen3_tts_local":
        return _build_qwen3_tts_facade(request).import_model_package_to_workspace(
            workspace_id=workspace_id,
            source_path=body.source_path,
            storage_mode=body.storage_mode,
        ).model_dump(mode="json")
    raise ValueError(f"Workspace '{workspace_id}' does not support local package import.")


@router.get("/workspaces/{workspace_id}")
def get_workspace(request: Request, workspace_id: str) -> dict[str, Any]:
    return _build_workspace_service(request).get_workspace_tree(workspace_id).model_dump(mode="json")


@router.patch("/workspaces/{workspace_id}")
def patch_workspace(request: Request, workspace_id: str, body: UpdateWorkspaceRequest) -> dict[str, Any]:
    return _build_workspace_service(request).update_workspace(
        workspace_id=workspace_id,
        display_name=body.display_name,
        slug=body.slug,
        status=body.status,
        ui_order=body.ui_order,
    ).model_dump(mode="json")


@router.delete("/workspaces/{workspace_id}")
def delete_workspace(request: Request, workspace_id: str) -> dict[str, str]:
    _build_workspace_service(request).delete_workspace(workspace_id)
    return {"status": "deleted", "workspace_id": workspace_id}


@router.get("/workspaces/{workspace_id}/main-models")
def list_workspace_main_models(request: Request, workspace_id: str) -> list[dict[str, Any]]:
    return [
        item.model_dump(mode="json")
        for item in _build_workspace_service(request).list_main_models(workspace_id)
    ]


@router.post("/workspaces/{workspace_id}/main-models", status_code=status.HTTP_201_CREATED)
def create_workspace_main_model(
    request: Request,
    workspace_id: str,
    body: CreateMainModelRequest,
) -> dict[str, Any]:
    return _build_workspace_service(request).create_main_model(
        workspace_id=workspace_id,
        main_model_id=body.main_model_id,
        display_name=body.display_name,
        source_type=body.source_type,
        main_model_metadata=body.main_model_metadata,
        shared_assets=body.shared_assets,
    ).model_dump(mode="json")


@router.get("/workspaces/{workspace_id}/main-models/{main_model_id}")
def get_workspace_main_model(request: Request, workspace_id: str, main_model_id: str) -> dict[str, Any]:
    tree = _build_workspace_service(request).get_workspace_tree(workspace_id)
    for main_model in tree.main_models:
        if main_model.main_model_id == main_model_id:
            return main_model.model_dump(mode="json")
    raise LookupError(f"Main model '{main_model_id}' not found.")


@router.patch("/workspaces/{workspace_id}/main-models/{main_model_id}")
def patch_workspace_main_model(
    request: Request,
    workspace_id: str,
    main_model_id: str,
    body: UpdateMainModelRequest,
) -> dict[str, Any]:
    return _build_workspace_service(request).update_main_model(
        workspace_id=workspace_id,
        main_model_id=main_model_id,
        display_name=body.display_name,
        status=body.status,
        main_model_metadata=body.main_model_metadata,
        shared_assets=body.shared_assets,
        default_submodel_id=body.default_submodel_id,
    ).model_dump(mode="json")


@router.delete("/workspaces/{workspace_id}/main-models/{main_model_id}")
def delete_workspace_main_model(request: Request, workspace_id: str, main_model_id: str) -> dict[str, str]:
    _build_workspace_service(request).delete_main_model(workspace_id, main_model_id)
    return {"status": "deleted", "workspace_id": workspace_id, "main_model_id": main_model_id}


@router.get("/workspaces/{workspace_id}/main-models/{main_model_id}/submodels")
def list_workspace_submodels(request: Request, workspace_id: str, main_model_id: str) -> list[dict[str, Any]]:
    return [
        item.model_dump(mode="json")
        for item in _build_workspace_service(request).list_submodels(workspace_id, main_model_id)
    ]


@router.post("/workspaces/{workspace_id}/main-models/{main_model_id}/submodels", status_code=status.HTTP_201_CREATED)
def create_workspace_submodel(
    request: Request,
    workspace_id: str,
    main_model_id: str,
    body: CreateSubmodelRequest,
) -> dict[str, Any]:
    return _build_workspace_service(request).create_submodel(
        workspace_id=workspace_id,
        main_model_id=main_model_id,
        submodel_id=body.submodel_id,
        display_name=body.display_name,
        status=body.status,
        instance_assets=body.instance_assets,
        endpoint=body.endpoint,
        account_binding=body.account_binding,
        adapter_options=body.adapter_options,
        runtime_profile=body.runtime_profile,
        is_hidden_singleton=body.is_hidden_singleton,
    ).model_dump(mode="json")


@router.get("/workspaces/{workspace_id}/main-models/{main_model_id}/submodels/{submodel_id}")
def get_workspace_submodel(
    request: Request,
    workspace_id: str,
    main_model_id: str,
    submodel_id: str,
) -> dict[str, Any]:
    for item in _build_workspace_service(request).list_submodels(workspace_id, main_model_id):
        if item.submodel_id == submodel_id:
            return item.model_dump(mode="json")
    raise LookupError(f"Submodel '{submodel_id}' not found.")


@router.patch("/workspaces/{workspace_id}/main-models/{main_model_id}/submodels/{submodel_id}")
def patch_workspace_submodel(
    request: Request,
    workspace_id: str,
    main_model_id: str,
    submodel_id: str,
    body: UpdateSubmodelRequest,
) -> dict[str, Any]:
    return _build_workspace_service(request).update_submodel(
        workspace_id=workspace_id,
        main_model_id=main_model_id,
        submodel_id=submodel_id,
        display_name=body.display_name,
        status=body.status,
        instance_assets=body.instance_assets,
        endpoint=body.endpoint,
        account_binding=body.account_binding,
        adapter_options=body.adapter_options,
        runtime_profile=body.runtime_profile,
    ).model_dump(mode="json")


@router.delete("/workspaces/{workspace_id}/main-models/{main_model_id}/submodels/{submodel_id}")
def delete_workspace_submodel(
    request: Request,
    workspace_id: str,
    main_model_id: str,
    submodel_id: str,
) -> dict[str, str]:
    _build_workspace_service(request).delete_submodel(workspace_id, main_model_id, submodel_id)
    return {
        "status": "deleted",
        "workspace_id": workspace_id,
        "main_model_id": main_model_id,
        "submodel_id": submodel_id,
    }


@router.put("/workspaces/{workspace_id}/main-models/{main_model_id}/submodels/{submodel_id}/secrets")
def put_workspace_submodel_secrets(
    request: Request,
    workspace_id: str,
    main_model_id: str,
    submodel_id: str,
    body: PutSecretsRequest,
) -> dict[str, Any]:
    return _build_workspace_service(request).put_submodel_secrets(
        workspace_id=workspace_id,
        main_model_id=main_model_id,
        submodel_id=submodel_id,
        secrets=body.secrets,
    ).model_dump(mode="json")


@router.post("/workspaces/{workspace_id}/main-models/{main_model_id}/submodels/{submodel_id}/connectivity-check")
def connectivity_check_workspace_submodel(
    request: Request,
    workspace_id: str,
    main_model_id: str,
    submodel_id: str,
) -> dict[str, Any]:
    service = _build_workspace_service(request)
    submodel = service.list_submodels(workspace_id, main_model_id)
    target = next((item for item in submodel if item.submodel_id == submodel_id), None)
    if target is None:
        raise LookupError(f"Submodel '{submodel_id}' not found.")
    return {
        "status": "ready" if target.status in {"ready", "needs_secret"} else target.status,
        "workspace_id": workspace_id,
        "main_model_id": main_model_id,
        "submodel_id": submodel_id,
    }


@router.get("/workspaces/{workspace_id}/main-models/{main_model_id}/submodels/{submodel_id}/presets")
def list_workspace_presets(
    request: Request,
    workspace_id: str,
    main_model_id: str,
    submodel_id: str,
) -> list[dict[str, Any]]:
    return [
        item.model_dump(mode="json")
        for item in _build_workspace_service(request).list_presets(workspace_id, main_model_id, submodel_id)
    ]


@router.post(
    "/workspaces/{workspace_id}/main-models/{main_model_id}/submodels/{submodel_id}/presets",
    status_code=status.HTTP_201_CREATED,
)
def create_workspace_preset(
    request: Request,
    workspace_id: str,
    main_model_id: str,
    submodel_id: str,
    body: CreateWorkspacePresetRequest,
) -> dict[str, Any]:
    return _build_workspace_service(request).create_preset(
        workspace_id=workspace_id,
        main_model_id=main_model_id,
        submodel_id=submodel_id,
        preset_id=body.preset_id,
        display_name=body.display_name,
        kind=body.kind,
        status=body.status,
        defaults=body.defaults,
        fixed_fields=body.fixed_fields,
        preset_assets=body.preset_assets,
        is_hidden_singleton=body.is_hidden_singleton,
    ).model_dump(mode="json")


@router.patch("/workspaces/{workspace_id}/main-models/{main_model_id}/submodels/{submodel_id}/presets/{preset_id}")
def patch_workspace_preset(
    request: Request,
    workspace_id: str,
    main_model_id: str,
    submodel_id: str,
    preset_id: str,
    body: UpdateWorkspacePresetRequest,
) -> dict[str, Any]:
    return _build_workspace_service(request).update_preset(
        workspace_id=workspace_id,
        main_model_id=main_model_id,
        submodel_id=submodel_id,
        preset_id=preset_id,
        display_name=body.display_name,
        status=body.status,
        defaults=body.defaults,
        fixed_fields=body.fixed_fields,
        preset_assets=body.preset_assets,
    ).model_dump(mode="json")


@router.delete("/workspaces/{workspace_id}/main-models/{main_model_id}/submodels/{submodel_id}/presets/{preset_id}")
def delete_workspace_preset(
    request: Request,
    workspace_id: str,
    main_model_id: str,
    submodel_id: str,
    preset_id: str,
) -> dict[str, str]:
    _build_workspace_service(request).delete_preset(workspace_id, main_model_id, submodel_id, preset_id)
    return {
        "status": "deleted",
        "workspace_id": workspace_id,
        "main_model_id": main_model_id,
        "submodel_id": submodel_id,
        "preset_id": preset_id,
    }


@router.post("/workspaces/{workspace_id}/test-render")
def test_render_workspace(request: Request, workspace_id: str) -> dict[str, Any]:
    tree = _build_workspace_service(request).get_workspace_tree(workspace_id)
    return {
        "status": "ready",
        "workspace_id": workspace_id,
        "main_model_count": len(tree.main_models),
    }
