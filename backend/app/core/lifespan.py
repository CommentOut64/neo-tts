from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from backend.app.inference.engine import PyTorchInferenceEngine
from backend.app.inference.model_cache import PyTorchModelCache
from backend.app.services.inference_params_cache import InferenceParamsCacheStore
from backend.app.services.inference_runtime import InferenceRuntimeController
from backend.app.services.synthesis_result_store import SynthesisResultStore


@asynccontextmanager
async def app_lifespan(app: FastAPI):
    settings = app.state.settings
    model_cache = PyTorchModelCache(
        project_root=settings.project_root,
        cnhubert_base_path=settings.cnhubert_base_path,
        bert_path=settings.bert_path,
    )
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
    app.state.model_cache = model_cache
    app.state.inference_engine = inference_engine
    app.state.inference_runtime = inference_runtime
    app.state.synthesis_result_store = synthesis_result_store
    app.state.inference_params_cache_store = inference_params_cache_store
    yield
