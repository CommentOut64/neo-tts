from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from backend.app.inference.engine import PyTorchInferenceEngine
from backend.app.inference.model_cache import PyTorchModelCache


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
    app.state.model_cache = model_cache
    app.state.inference_engine = inference_engine
    yield
