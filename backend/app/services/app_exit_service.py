from __future__ import annotations

from contextlib import suppress
from datetime import datetime
import gc
import json
from typing import Any

from backend.app.core.settings import AppSettings
from backend.app.repositories.edit_session_repository import EditSessionRepository
from backend.app.schemas.system import PrepareExitResponse
from backend.app.services.edit_session_runtime import EditSessionRuntime
from backend.app.services.inference_residual_service import InferenceResidualService
from backend.app.services.inference_runtime import InferenceRuntimeController


class AppExitService:
    def __init__(
        self,
        *,
        settings: AppSettings,
        edit_session_repository: EditSessionRepository,
        edit_session_runtime: EditSessionRuntime,
        inference_runtime: InferenceRuntimeController,
        residual_service: InferenceResidualService,
        model_cache: Any | None = None,
        editable_inference_gateway_cache: dict[tuple[str, str], Any] | None = None,
    ) -> None:
        self._settings = settings
        self._edit_session_repository = edit_session_repository
        self._edit_session_runtime = edit_session_runtime
        self._inference_runtime = inference_runtime
        self._residual_service = residual_service
        self._model_cache = model_cache
        self._editable_inference_gateway_cache = editable_inference_gateway_cache

    def prepare_exit(self) -> PrepareExitResponse:
        active_render_job_status = self._prepare_edit_session_job_for_exit()
        cleanup_result = self._residual_service.cleanup(
            force_pause_message="收到退出准备请求，已触发强制暂停。",
            reset_message="退出准备已完成，推理残留已清理。",
        )
        self._release_inference_resources()
        launcher_exit_requested = self._request_launcher_exit()
        return PrepareExitResponse(
            launcher_exit_requested=launcher_exit_requested,
            active_render_job_status=active_render_job_status,
            inference_status=cleanup_result.state.status,
        )

    def _prepare_edit_session_job_for_exit(self) -> str | None:
        active_session = self._edit_session_repository.get_active_session()
        if active_session is None or active_session.active_job_id is None:
            return None

        job_id = active_session.active_job_id
        snapshot = self._edit_session_runtime.get_job(job_id)
        if snapshot is None:
            return None
        if snapshot.status in self._edit_session_runtime.TERMINAL_STATUSES:
            return snapshot.status

        self._edit_session_runtime.request_pause(job_id)
        terminal_snapshot = self._edit_session_runtime.wait_for_job_terminal(job_id)
        return terminal_snapshot.status if terminal_snapshot is not None else None

    def _request_launcher_exit(self) -> bool:
        runtime_state_path = self._settings.project_root / "logs" / "launcher" / "runtime-state.json"
        if not runtime_state_path.exists():
            return False

        try:
            runtime_state = json.loads(runtime_state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return False

        launcher_pid = runtime_state.get("launcherPid")
        if not isinstance(launcher_pid, int) or launcher_pid <= 0:
            return False

        exit_request_path = self._settings.project_root / "logs" / "launcher" / "control" / "exit-request.json"
        exit_request_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "kind": "user_exit",
            "source": "frontend",
            "requested_at": datetime.now().astimezone().isoformat(),
            "launcher_pid": launcher_pid,
        }
        temp_path = exit_request_path.with_name(f"{exit_request_path.name}.tmp")
        try:
            temp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            temp_path.replace(exit_request_path)
            return True
        except OSError:
            with suppress(OSError):
                temp_path.unlink()
            return False

    def _release_inference_resources(self) -> None:
        if self._editable_inference_gateway_cache:
            for gateway in list(self._editable_inference_gateway_cache.values()):
                clear_backend = getattr(gateway, "clear_backend", None)
                if callable(clear_backend):
                    clear_backend()
            self._editable_inference_gateway_cache.clear()

        gc.collect()
        if self._model_cache is not None:
            self._model_cache.clear()
        gc.collect()

        try:
            import torch
        except ImportError:
            return

        if hasattr(torch, "cuda") and hasattr(torch.cuda, "empty_cache"):
            torch.cuda.empty_cache()
