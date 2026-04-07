from pathlib import Path
from fastapi import APIRouter
from pydantic import BaseModel
import tkinter as tk
from tkinter import filedialog
import threading

router = APIRouter(prefix="/v1/system", tags=["System"])

class FolderSelectResponse(BaseModel):
    path: str | None

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
