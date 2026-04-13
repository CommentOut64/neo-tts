from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager, suppress
from pathlib import Path

from fastapi import FastAPI

from backend.app.core.logging import get_logger
from backend.app.repositories.edit_session_repository import EditSessionRepository
from backend.app.repositories.voice_repository import VoiceRepository
from backend.app.services.edit_asset_store import EditAssetStore
from backend.app.services.edit_session_maintenance_service import EditSessionMaintenanceService
from backend.app.services.edit_session_runtime import EditSessionRuntime
from backend.app.services.export_service import ExportService
from backend.app.services.inference_params_cache import InferenceParamsCacheStore
from backend.app.services.inference_runtime import InferenceRuntimeController
from backend.app.services.synthesis_result_store import SynthesisResultStore

lifespan_logger = get_logger("lifespan")


def _resolve_project_path(project_root: Path, raw_path: str) -> str:
    path = Path(raw_path)
    if not path.is_absolute():
        path = project_root / path
    return str(path.resolve())


def _preload_configured_voices(app: FastAPI, model_cache) -> None:
    settings = app.state.settings
    if not settings.preload_on_start or not settings.preload_voice_ids:
        return

    repository = VoiceRepository(config_path=settings.voices_config_path, settings=settings)
    for voice_id in settings.preload_voice_ids:
        try:
            voice = repository.get_voice(voice_id)
        except LookupError as exc:
            lifespan_logger.warning("启动预加载跳过，未找到音色 voice_id={} reason={}", voice_id, exc)
            continue

        try:
            resolved_gpt_path = _resolve_project_path(settings.project_root, str(voice["gpt_path"]))
            resolved_sovits_path = _resolve_project_path(settings.project_root, str(voice["sovits_path"]))
            get_model_handle = getattr(model_cache, "get_model_handle", None)
            if callable(get_model_handle):
                handle = get_model_handle(
                    gpt_path=resolved_gpt_path,
                    sovits_path=resolved_sovits_path,
                )
                handle.pinned = True
            else:
                model_cache.get_engine(
                    gpt_path=resolved_gpt_path,
                    sovits_path=resolved_sovits_path,
                )
            lifespan_logger.info("启动预加载完成 voice_id={}", voice_id)
        except Exception as exc:
            lifespan_logger.warning("启动预加载失败 voice_id={} reason={}", voice_id, exc)


@asynccontextmanager
async def app_lifespan(app: FastAPI):
    from backend.app.inference.engine import PyTorchInferenceEngine
    from backend.app.inference.model_cache import PyTorchModelCache, build_model_cache_from_settings

    settings = app.state.settings
    model_cache = build_model_cache_from_settings(
        settings=settings,
        model_cache_cls=PyTorchModelCache,
    )
    _preload_configured_voices(app, model_cache)
    inference_engine = PyTorchInferenceEngine(
        model_cache=model_cache,
        project_root=settings.project_root,
    )
    inference_runtime = InferenceRuntimeController()
    synthesis_result_store = SynthesisResultStore(
        project_root=settings.project_root,
        results_dir=settings.synthesis_results_dir,
    )
    inference_params_cache_store = InferenceParamsCacheStore(
        project_root=settings.project_root,
        cache_file=settings.inference_params_cache_file,
    )
    edit_session_repository = EditSessionRepository(
        project_root=settings.project_root,
        db_file=settings.edit_session_db_file,
    )
    edit_session_repository.initialize_schema()
    edit_asset_store = EditAssetStore(
        project_root=settings.project_root,
        assets_dir=settings.edit_session_assets_dir,
        export_root=settings.edit_session_exports_dir,
        staging_ttl_seconds=settings.edit_session_staging_ttl_seconds,
    )
    edit_session_runtime = EditSessionRuntime()
    edit_session_export_service = ExportService(
        repository=edit_session_repository,
        asset_store=edit_asset_store,
    )
    edit_session_maintenance_service = EditSessionMaintenanceService(
        repository=edit_session_repository,
        asset_store=edit_asset_store,
        runtime=edit_session_runtime,
    )
    await edit_session_maintenance_service.reconcile_on_startup()
    cleanup_task = asyncio.create_task(edit_session_maintenance_service.run_periodic_loop())
    app.state.model_cache = model_cache
    app.state.inference_engine = inference_engine
    app.state.inference_runtime = inference_runtime
    app.state.synthesis_result_store = synthesis_result_store
    app.state.inference_params_cache_store = inference_params_cache_store
    app.state.edit_session_repository = edit_session_repository
    app.state.edit_asset_store = edit_asset_store
    app.state.edit_session_runtime = edit_session_runtime
    app.state.edit_session_export_service = edit_session_export_service
    app.state.edit_session_maintenance_service = edit_session_maintenance_service
    app.state.edit_session_cleanup_task = cleanup_task
    try:
        yield
    finally:
        cleanup_task.cancel()
        with suppress(asyncio.CancelledError):
            await cleanup_task
