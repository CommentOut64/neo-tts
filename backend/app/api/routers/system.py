from pathlib import Path
from fastapi import APIRouter, Request
from pydantic import BaseModel
import tkinter as tk
from tkinter import filedialog
import threading

from backend.app.schemas.system import PrepareExitResponse, SystemVersionResponse
from backend.app.services.app_exit_service import AppExitService
from backend.app.services.inference_residual_service import InferenceResidualService
from backend.app.services.synthesis_result_store import SynthesisResultStore

router = APIRouter(prefix="/v1/system", tags=["System"])

class FolderSelectResponse(BaseModel):
    path: str | None


class FileSelectResponse(BaseModel):
    path: str | None


def _build_result_store(request: Request) -> SynthesisResultStore:
    existing = getattr(request.app.state, "synthesis_result_store", None)
    if existing is not None:
        return existing
    settings = request.app.state.settings
    store = SynthesisResultStore(
        project_root=settings.project_root,
        results_dir=settings.synthesis_results_dir,
    )
    request.app.state.synthesis_result_store = store
    return store


def _build_inference_residual_service(request: Request) -> InferenceResidualService:
    return InferenceResidualService(
        settings=request.app.state.settings,
        runtime=request.app.state.inference_runtime,
        result_store=_build_result_store(request),
    )


def _build_app_exit_service(request: Request) -> AppExitService:
    return AppExitService(
        settings=request.app.state.settings,
        edit_session_repository=request.app.state.edit_session_repository,
        edit_session_runtime=request.app.state.edit_session_runtime,
        inference_runtime=request.app.state.inference_runtime,
        residual_service=_build_inference_residual_service(request),
        model_cache=getattr(request.app.state, "model_cache", None),
        editable_inference_gateway_cache=getattr(request.app.state, "editable_inference_gateway_cache", None),
    )

def _open_folder_dialog(initial_dir: str | None = None) -> str | None:
    root = tk.Tk()
    root.withdraw()
    # Make sure dialog comes to front
    root.attributes("-topmost", True)
    
    kwargs = {"title": "请选择导出目录"}
    if initial_dir and Path(initial_dir).is_dir():
        kwargs["initialdir"] = initial_dir
        
    selected_path = filedialog.askdirectory(**kwargs)
    root.destroy()
    
    return selected_path if selected_path else None


def _build_file_dialog_filetypes(accept: str | None) -> list[tuple[str, str]]:
    if accept is None:
        return [("所有文件", "*.*")]
    extensions = []
    for raw_item in accept.split(","):
        normalized = raw_item.strip().lower()
        if not normalized:
            continue
        if not normalized.startswith("."):
            normalized = f".{normalized}"
        extensions.append(normalized)
    if not extensions:
        return [("所有文件", "*.*")]
    patterns = " ".join(f"*{extension}" for extension in extensions)
    return [("支持的文件", patterns), ("所有文件", "*.*")]


def _open_file_dialog(initial_dir: str | None = None, accept: str | None = None) -> str | None:
    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)

    kwargs = {
        "title": "请选择文件",
        "filetypes": _build_file_dialog_filetypes(accept),
    }
    if initial_dir and Path(initial_dir).is_dir():
        kwargs["initialdir"] = initial_dir

    selected_path = filedialog.askopenfilename(**kwargs)
    root.destroy()

    return selected_path if selected_path else None

@router.get("/dialog/folder", response_model=FolderSelectResponse)
def open_folder_dialog(initial_dir: str | None = None):
    # Depending on how the server is run, `askdirectory` MUST be called in the main thread (or a dedicated thread that can init GUI).
    # Since FastAPI uses threads for def endpoints, running tkinter in a sub-thread sometimes hangs or causes problems.
    # To be safe, we can try running it directly, but it might complain about "main thread".
    # Wait, Tkinter works fine in a spawned thread as long as the event loop is started and destroyed fully in that thread.
    result = {"path": None}
    
    def run_gui():
        result["path"] = _open_folder_dialog(initial_dir)
        
    t = threading.Thread(target=run_gui)
    t.start()
    t.join()

    return FolderSelectResponse(path=result["path"])


@router.get("/dialog/file", response_model=FileSelectResponse)
def open_file_dialog(initial_dir: str | None = None, accept: str | None = None):
    result = {"path": None}

    def run_gui():
        result["path"] = _open_file_dialog(initial_dir, accept)

    t = threading.Thread(target=run_gui)
    t.start()
    t.join()

    return FileSelectResponse(path=result["path"])


@router.post("/prepare-exit", response_model=PrepareExitResponse)
def prepare_exit(request: Request) -> PrepareExitResponse:
    return _build_app_exit_service(request).prepare_exit()


@router.get("/version", response_model=SystemVersionResponse)
def get_version(request: Request) -> SystemVersionResponse:
    settings = request.app.state.settings
    return SystemVersionResponse(
        version=settings.display_version,
        build_version=settings.app_version,
    )
