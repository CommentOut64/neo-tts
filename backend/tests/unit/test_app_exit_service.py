from __future__ import annotations

import json
from pathlib import Path
import threading
import time

from backend.app.core.settings import AppSettings
from backend.app.repositories.edit_session_repository import EditSessionRepository
from backend.app.schemas.edit_session import ActiveDocumentState, InitializeEditSessionRequest, RenderJobResponse
from backend.app.services.app_exit_service import AppExitService
from backend.app.services.edit_session_runtime import EditSessionRuntime
from backend.app.services.inference_residual_service import InferenceResidualService
from backend.app.services.inference_runtime import InferenceRuntimeController
from backend.app.services.synthesis_result_store import SynthesisResultStore


def _build_settings(tmp_path: Path) -> AppSettings:
    return AppSettings(
        project_root=tmp_path,
        voices_config_path=tmp_path / "voices.json",
        managed_voices_dir=tmp_path / "managed_voices",
        synthesis_results_dir=tmp_path / "synthesis_results",
        inference_params_cache_file=tmp_path / "state" / "params_cache.json",
        edit_session_db_file=tmp_path / "storage" / "edit_session" / "session.db",
        edit_session_assets_dir=tmp_path / "storage" / "edit_session" / "assets",
        edit_session_exports_dir=tmp_path / "storage" / "edit_session" / "exports",
    )


def _build_repository(settings: AppSettings) -> EditSessionRepository:
    repository = EditSessionRepository(
        project_root=settings.project_root,
        db_file=settings.edit_session_db_file,
    )
    repository.initialize_schema()
    return repository


def _build_render_job(*, job_id: str, status: str = "rendering") -> RenderJobResponse:
    return RenderJobResponse(
        job_id=job_id,
        document_id="doc-1",
        status=status,
        progress=0.5,
        message="running",
        cancel_requested=False,
        pause_requested=False,
    )


def _seed_active_edit_session(
    repository: EditSessionRepository,
    *,
    job_id: str,
) -> None:
    repository.upsert_active_session(
        ActiveDocumentState(
            document_id="doc-1",
            session_status="ready",
            active_job_id=job_id,
            initialize_request=InitializeEditSessionRequest(
                raw_text="第一句。第二句。",
                voice_id="demo",
            ),
        )
    )


def _write_launcher_runtime_state(project_root: Path) -> None:
    runtime_state_path = project_root / "logs" / "launcher" / "runtime-state.json"
    runtime_state_path.parent.mkdir(parents=True, exist_ok=True)
    runtime_state_path.write_text(
        json.dumps(
            {
                "launcherPid": 12345,
                "runtimeMode": "dev",
                "frontendMode": "web",
                "startupSource": "double-click",
                "isElevated": False,
                "backend": {
                    "mode": "owned",
                    "pid": 24680,
                    "port": 18600,
                    "origin": "http://127.0.0.1:18600",
                    "command": "python -m backend.app.cli --port 18600",
                },
                "frontendHost": {
                    "kind": "vite",
                    "pid": 13579,
                    "port": 5175,
                    "origin": "http://127.0.0.1:5175",
                    "command": "npm run dev",
                    "browserOpened": True,
                },
                "lastPhase": "running",
                "lastError": "",
                "logFilePath": str(project_root / "logs" / "launcher" / "launcher.log"),
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def _pause_job_when_requested(runtime: EditSessionRuntime, job_id: str) -> threading.Thread:
    def _worker() -> None:
        deadline = time.time() + 2
        while time.time() < deadline:
            snapshot = runtime.get_job(job_id)
            if snapshot is not None and snapshot.pause_requested:
                runtime.update_job(job_id, status="paused", message="job paused")
                return
            time.sleep(0.01)
        raise AssertionError("pause request was not observed before timeout")

    thread = threading.Thread(target=_worker)
    thread.start()
    return thread


def _cancel_inference_when_requested(runtime: InferenceRuntimeController, task_id: str) -> threading.Thread:
    def _worker() -> None:
        deadline = time.time() + 2
        while time.time() < deadline:
            if runtime.should_cancel(task_id):
                runtime.mark_cancelled(task_id=task_id, message="cancelled for exit")
                return
            time.sleep(0.01)
        raise AssertionError("force pause request was not observed before timeout")

    thread = threading.Thread(target=_worker)
    thread.start()
    return thread


def test_prepare_exit_pauses_active_render_job_and_requests_launcher_exit(tmp_path: Path):
    settings = _build_settings(tmp_path)
    repository = _build_repository(settings)
    edit_session_runtime = EditSessionRuntime()
    inference_runtime = InferenceRuntimeController()
    result_store = SynthesisResultStore(
        project_root=settings.project_root,
        results_dir=settings.synthesis_results_dir,
    )
    residual_service = InferenceResidualService(
        settings=settings,
        runtime=inference_runtime,
        result_store=result_store,
    )
    _write_launcher_runtime_state(tmp_path)

    job_id = "job-1"
    _seed_active_edit_session(repository, job_id=job_id)
    edit_session_runtime.start_job(_build_render_job(job_id=job_id))
    pause_thread = _pause_job_when_requested(edit_session_runtime, job_id)

    service = AppExitService(
        settings=settings,
        edit_session_repository=repository,
        edit_session_runtime=edit_session_runtime,
        inference_runtime=inference_runtime,
        residual_service=residual_service,
    )

    response = service.prepare_exit()
    pause_thread.join(timeout=2)

    assert response.status == "prepared"
    assert response.launcher_exit_requested is True
    assert response.active_render_job_status == "paused"
    assert response.inference_status == "idle"
    assert edit_session_runtime.get_job(job_id).pause_requested is True

    exit_request_path = tmp_path / "logs" / "launcher" / "control" / "exit-request.json"
    assert exit_request_path.exists()
    assert json.loads(exit_request_path.read_text(encoding="utf-8"))["launcher_pid"] == 12345


def test_prepare_exit_force_pauses_tts_runtime_and_cleans_residuals(tmp_path: Path):
    settings = _build_settings(tmp_path)
    repository = _build_repository(settings)
    edit_session_runtime = EditSessionRuntime()
    inference_runtime = InferenceRuntimeController()
    result_store = SynthesisResultStore(
        project_root=settings.project_root,
        results_dir=settings.synthesis_results_dir,
    )
    residual_service = InferenceResidualService(
        settings=settings,
        runtime=inference_runtime,
        result_store=result_store,
    )
    _write_launcher_runtime_state(tmp_path)

    temp_ref_dir = settings.managed_voices_dir / "_temp_refs" / "dangling"
    temp_ref_dir.mkdir(parents=True, exist_ok=True)
    (temp_ref_dir / "leftover.wav").write_bytes(b"wav")
    saved_result = result_store.save_wav(b"RIFFdemo")

    task_id = inference_runtime.start_task(message="legacy inference is running")
    cancel_thread = _cancel_inference_when_requested(inference_runtime, task_id)

    service = AppExitService(
        settings=settings,
        edit_session_repository=repository,
        edit_session_runtime=edit_session_runtime,
        inference_runtime=inference_runtime,
        residual_service=residual_service,
    )

    response = service.prepare_exit()
    cancel_thread.join(timeout=2)

    assert response.status == "prepared"
    assert response.launcher_exit_requested is True
    assert response.active_render_job_status is None
    assert response.inference_status == "idle"
    assert not temp_ref_dir.exists()
    assert not saved_result.file_path.exists()
    exit_request_path = tmp_path / "logs" / "launcher" / "control" / "exit-request.json"
    assert json.loads(exit_request_path.read_text(encoding="utf-8"))["launcher_pid"] == 12345


def test_prepare_exit_is_idempotent_when_no_launcher_state_exists(tmp_path: Path):
    settings = _build_settings(tmp_path)
    repository = _build_repository(settings)
    edit_session_runtime = EditSessionRuntime()
    inference_runtime = InferenceRuntimeController()
    result_store = SynthesisResultStore(
        project_root=settings.project_root,
        results_dir=settings.synthesis_results_dir,
    )
    residual_service = InferenceResidualService(
        settings=settings,
        runtime=inference_runtime,
        result_store=result_store,
    )
    service = AppExitService(
        settings=settings,
        edit_session_repository=repository,
        edit_session_runtime=edit_session_runtime,
        inference_runtime=inference_runtime,
        residual_service=residual_service,
    )

    first = service.prepare_exit()
    second = service.prepare_exit()

    assert first.status == "prepared"
    assert second.status == "prepared"
    assert first.launcher_exit_requested is False
    assert second.launcher_exit_requested is False
    assert first.active_render_job_status is None
    assert second.active_render_job_status is None
    assert first.inference_status == "idle"
    assert second.inference_status == "idle"

    exit_request_path = tmp_path / "logs" / "launcher" / "control" / "exit-request.json"
    assert not exit_request_path.exists()


def test_prepare_exit_clears_model_cache_and_editable_gateway_backends(tmp_path: Path):
    settings = _build_settings(tmp_path)
    repository = _build_repository(settings)
    edit_session_runtime = EditSessionRuntime()
    inference_runtime = InferenceRuntimeController()
    result_store = SynthesisResultStore(
        project_root=settings.project_root,
        results_dir=settings.synthesis_results_dir,
    )
    residual_service = InferenceResidualService(
        settings=settings,
        runtime=inference_runtime,
        result_store=result_store,
    )

    class FakeModelCache:
        def __init__(self) -> None:
            self.clear_calls = 0

        def clear(self) -> None:
            self.clear_calls += 1

    class FakeGateway:
        def __init__(self) -> None:
            self.clear_calls = 0

        def clear_backend(self) -> None:
            self.clear_calls += 1

    model_cache = FakeModelCache()
    first_gateway = FakeGateway()
    second_gateway = FakeGateway()

    service = AppExitService(
        settings=settings,
        edit_session_repository=repository,
        edit_session_runtime=edit_session_runtime,
        inference_runtime=inference_runtime,
        residual_service=residual_service,
        model_cache=model_cache,
        editable_inference_gateway_cache={
            ("gpt-a", "sovits-a"): first_gateway,
            ("gpt-b", "sovits-b"): second_gateway,
        },
    )

    response = service.prepare_exit()

    assert response.status == "prepared"
    assert model_cache.clear_calls == 1
    assert first_gateway.clear_calls == 1
    assert second_gateway.clear_calls == 1
