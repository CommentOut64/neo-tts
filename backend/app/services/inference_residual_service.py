from __future__ import annotations

from contextlib import suppress
from dataclasses import dataclass
import shutil

from backend.app.core.settings import AppSettings
from backend.app.schemas.inference import CleanupResidualsResponse, InferenceProgressState
from backend.app.services.inference_runtime import InferenceRuntimeController
from backend.app.services.synthesis_result_store import SynthesisResultStore


@dataclass(frozen=True)
class CleanupResidualResult:
    cancelled_active_task: bool
    removed_temp_ref_dirs: int
    removed_result_files: int
    state: InferenceProgressState

    def to_response(self) -> CleanupResidualsResponse:
        return CleanupResidualsResponse(
            cancelled_active_task=self.cancelled_active_task,
            removed_temp_ref_dirs=self.removed_temp_ref_dirs,
            removed_result_files=self.removed_result_files,
            state=self.state,
        )


class InferenceResidualService:
    def __init__(
        self,
        *,
        settings: AppSettings,
        runtime: InferenceRuntimeController,
        result_store: SynthesisResultStore,
    ) -> None:
        self._settings = settings
        self._runtime = runtime
        self._result_store = result_store

    def cleanup(
        self,
        *,
        force_pause_message: str = "收到残留清理请求，已触发强制暂停。",
        reset_message: str = "推理残留已清理。",
    ) -> CleanupResidualResult:
        cancelled = self._runtime.request_force_pause(message=force_pause_message)
        self._runtime.wait_for_terminal()
        removed_temp_ref_dirs = self._cleanup_temporary_reference_dirs()
        removed_result_files = self._result_store.clear_all_results()
        self._runtime.reset_if_idle(message=reset_message)
        return CleanupResidualResult(
            cancelled_active_task=cancelled,
            removed_temp_ref_dirs=removed_temp_ref_dirs,
            removed_result_files=removed_result_files,
            state=self._runtime.snapshot(),
        )

    def _cleanup_temporary_reference_dirs(self) -> int:
        temp_root = self._settings.managed_voices_dir
        if not temp_root.is_absolute():
            temp_root = self._settings.project_root / temp_root
        temp_root = temp_root / "_temp_refs"

        if not temp_root.exists():
            return 0

        removed = 0
        for child in temp_root.iterdir():
            if child.is_dir():
                shutil.rmtree(child, ignore_errors=False)
                removed += 1
        with suppress(OSError):
            if not any(temp_root.iterdir()):
                temp_root.rmdir()
        return removed
