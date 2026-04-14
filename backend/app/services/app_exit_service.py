from __future__ import annotations

import gc
from typing import Any

from backend.app.core.settings import AppSettings
from backend.app.repositories.edit_session_repository import EditSessionRepository
from backend.app.schemas.system import PrepareExitResponse
from backend.app.services.edit_session_runtime import EditSessionRuntime
from backend.app.services.inference_residual_service import InferenceResidualService
from backend.app.services.inference_runtime import InferenceRuntimeController
from backend.app.services.owner_control_client import OwnerControlClient


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
        owner_control_client: OwnerControlClient | None = None,
    ) -> None:
        self._settings = settings
        self._edit_session_repository = edit_session_repository
        self._edit_session_runtime = edit_session_runtime
        self._inference_runtime = inference_runtime
        self._residual_service = residual_service
        self._model_cache = model_cache
        self._editable_inference_gateway_cache = editable_inference_gateway_cache
        self._owner_control_client = owner_control_client or OwnerControlClient(
            origin=settings.owner_control_origin,
            token=settings.owner_control_token,
            session_id=settings.owner_session_id,
        )

    def prepare_exit(self) -> PrepareExitResponse:
        active_render_job_status = self._prepare_edit_session_job_for_exit()
        cleanup_result = self._residual_service.cleanup(
            force_pause_message="收到退出准备请求，已触发强制暂停。",
            reset_message="退出准备已完成，推理残留已清理。",
        )
        if cleanup_result.state.status in self._inference_runtime.TERMINAL_STATUSES:
            self._release_inference_resources()
        launcher_exit_requested = self._request_owner_shutdown()
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

    def _request_owner_shutdown(self) -> bool:
        try:
            return self._owner_control_client.request_shutdown(source="backend_prepare_exit")
        except Exception:
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
