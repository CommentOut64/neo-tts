from __future__ import annotations

from typing import Any
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import JSONResponse

from backend.app.services.project_session_service import CaptureToken, ProjectSessionService
from backend.app.services.project_store import NeoError


router = APIRouter(prefix="/v1/projects", tags=["projects"])


def _service(request: Request) -> ProjectSessionService:
    service = getattr(request.app.state, "project_session_service", None)
    if service is None:
        raise HTTPException(status_code=503, detail="project storage is not initialized")
    catalog = getattr(request.app.state, "model_catalog", None)
    if catalog is not None:
        service.set_model_catalog(catalog)
    return service


def _summary(service: ProjectSessionService, *, root=None, project_id: str | None = None) -> dict[str, Any]:
    root = root or service.workspace_path
    metadata_path = root / "workspace.json"
    metadata: dict[str, Any] = {}
    if metadata_path.is_file():
        import json

        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    return {
        "ok": True,
        "project_id": project_id or metadata.get("project_id"),
        "workspace_id": metadata.get("workspace_id", service.workspace_id),
        "workspace_path": str(root),
        "save_revision": metadata.get("last_save_revision", 0),
        "dirty": metadata.get("dirty", False),
        "last_save_stale": getattr(service, "last_save_stale", False),
        "capability": getattr(service, "current_capability", service.capability_for_status("exact")),
    }


def _request_id(request: Request) -> str:
    """Return a caller supplied trace id, or create one for this operation."""
    return request.headers.get("x-request-id") or uuid4().hex


def _project_error_response(exc: Exception, request: Request) -> JSONResponse:
    """Map storage/validation failures to the S3 safe error envelope.

    The router deliberately does not expose exception reprs or tracebacks.  The
    stable fields are consumed by the desktop client and are kept identical for
    all project-file actions.
    """
    request_id = _request_id(request)
    if isinstance(exc, NeoError):
        code = exc.code
        status_code = 409 if code in {"NEO_WRITE_BUSY", "NEO_TARGET_BUSY"} else 422
        retryable = code in {"NEO_WRITE_BUSY", "NEO_TARGET_BUSY"}
        action = "retry" if retryable else "repair_project"
        phase = "storage"
    elif isinstance(exc, FileNotFoundError):
        code, status_code, retryable, action, phase = "NEO_NOT_FOUND", 404, False, "choose_path", "storage"
    elif isinstance(exc, (KeyError, TypeError, ValueError)):
        code, status_code, retryable, action, phase = "PROJECT_INVALID_REQUEST", 400, False, "fix_request", "validation"
    else:
        code, status_code, retryable, action, phase = "NEO_STORAGE_ERROR", 500, False, "view_logs", "storage"
    message = str(exc) or code
    error = {
        "code": code,
        "phase": phase,
        "retryable": retryable,
        "action": action,
        "request_id": request_id,
        "message": message,
    }
    return JSONResponse(
        status_code=status_code,
        content={
            "ok": False,
            "project_id": None,
            "workspace_id": getattr(getattr(request.app.state, "project_session_service", None), "workspace_id", None),
            "save_revision": 0,
            "dirty": True,
            "capability": {
                "play": False,
                "export": False,
                "edit": False,
                "render": False,
                "boundary": False,
            },
            # ``detail`` keeps compatibility with FastAPI HTTPException clients;
            # ``error`` is the S3 project-action envelope used by new clients.
            "detail": error,
            "error": error,
        },
    )


def _raise_project_error(exc: Exception, request: Request) -> JSONResponse:
    """Backward-compatible name used by route handlers."""
    return _project_error_response(exc, request)


@router.post("/new", status_code=status.HTTP_201_CREATED)
def create_project(body: dict[str, Any], request: Request):
    service = _service(request)
    try:
        root = service.create_workspace(
            project_id=body.get("project_id"),
            workspace_id=body.get("workspace_id"),
        )
        return _summary(service, root=root, project_id=body.get("project_id"))
    except Exception as exc:
        return _raise_project_error(exc, request)


@router.post("/open")
def open_project(body: dict[str, Any], request: Request):
    service = _service(request)
    try:
        data = service.open_project(body["path"])
        return {**_summary(service), "project": data["project"]}
    except Exception as exc:
        return _raise_project_error(exc, request)


def _save(body: dict[str, Any], request: Request, *, require_target: bool) -> dict[str, Any]:
    service = _service(request)
    try:
        target = body.get("target")
        if require_target and not target:
            raise ValueError("target is required")
        token_payload = body.get("token")
        token = CaptureToken(**token_payload) if token_payload else None
        revision = service.save(body["payload"], token, target=target, force_partial=require_target)
        return {**_summary(service), "save_revision": revision}
    except Exception as exc:
        return _raise_project_error(exc, request)


@router.post("/save")
def save_project(body: dict[str, Any], request: Request):
    return _save(body, request, require_target=False)


@router.post("/save-as")
def save_project_as(body: dict[str, Any], request: Request):
    return _save(body, request, require_target=True)


@router.post("/import-legacy", status_code=status.HTTP_201_CREATED)
def import_legacy(body: dict[str, Any], request: Request):
    service = _service(request)
    try:
        root = service.import_legacy_session(body["path"], project_id=body.get("project_id"))
        return _summary(service, root=root, project_id=body.get("project_id"))
    except Exception as exc:
        return _raise_project_error(exc, request)


@router.get("/state")
def project_state(request: Request):
    service = _service(request)
    try:
        return _summary(service)
    except Exception as exc:
        return _raise_project_error(exc, request)
