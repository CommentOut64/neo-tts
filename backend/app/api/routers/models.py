from __future__ import annotations

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile, status

from backend.app.schemas.model_catalog import ExternalModelImportRequest, PresetCreateRequest, PresetPatchRequest
from backend.app.services.model_catalog import ModelCatalogService
from backend.app.repositories.voice_repository import VoiceRepository

router = APIRouter(prefix="/v1", tags=["model-catalog"])


def _service(request: Request) -> ModelCatalogService:
    existing = getattr(request.app.state, "model_catalog", None)
    if existing is not None:
        return existing
    settings = request.app.state.settings
    try:
        legacy = VoiceRepository(config_path=settings.voices_config_path, settings=settings).list_voices()
    except Exception:
        legacy = []
    catalog = ModelCatalogService(user_data_root=settings.user_data_root, builtin_voices=legacy)
    request.app.state.model_catalog = catalog
    return catalog


@router.get("/model-catalog/tree")
def model_catalog_tree(request: Request):
    return _service(request).list_tree()


@router.get("/models/{model_id}")
def get_model(model_id: str, request: Request):
    try:
        return _service(request).get_model(model_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/models/import", status_code=status.HTTP_201_CREATED)
def import_external_model(body: ExternalModelImportRequest, request: Request):
    try:
        return _service(request).import_external(body)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/models/import-managed", status_code=status.HTTP_201_CREATED)
async def import_managed_model(
    request: Request,
    model_id: str = Form(...),
    gpt_file: UploadFile = File(...),
    sovits_file: UploadFile = File(...),
):
    try:
        return _service(request).import_managed(
            model_id=model_id,
            gpt_name=gpt_file.filename or "", gpt_bytes=await gpt_file.read(),
            sovits_name=sovits_file.filename or "", sovits_bytes=await sovits_file.read(),
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.delete("/models/{model_id}")
def delete_model(model_id: str, request: Request):
    try:
        cache = getattr(request.app.state, "model_cache", None)
        pending = _service(request).delete_model(
            model_id,
            retire=getattr(cache, "retire_revision", None),
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"status": "retiring" if pending else "deleted", "model_id": model_id}


@router.patch("/models/{model_id}")
def relocate_external_model(model_id: str, body: ExternalModelImportRequest, request: Request):
    if body.model_id != model_id:
        raise HTTPException(status_code=400, detail="model_id must match the route parameter.")
    return import_external_model(body, request)


@router.get("/models/{model_id}/presets")
def list_presets(model_id: str, request: Request):
    try:
        return _service(request).list_presets(model_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/models/{model_id}/presets", status_code=status.HTTP_201_CREATED)
def create_preset(model_id: str, body: PresetCreateRequest, request: Request):
    try:
        return _service(request).create_preset(model_id, body)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.delete("/models/{model_id}/presets/{preset_id}")
def delete_preset(model_id: str, preset_id: str, request: Request):
    try:
        _service(request).delete_preset(model_id, preset_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"status": "deleted", "preset_id": preset_id}


@router.patch("/models/{model_id}/presets/{preset_id}")
def update_preset(model_id: str, preset_id: str, body: PresetPatchRequest, request: Request):
    try:
        return _service(request).update_preset(model_id, preset_id, body)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
