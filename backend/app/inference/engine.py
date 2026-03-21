from __future__ import annotations

from pathlib import Path
from typing import Iterator

import numpy as np

from backend.app.inference.model_cache import PyTorchModelCache
from backend.app.inference.pipeline import PyTorchSynthesisPipeline
from backend.app.inference.types import PreparedSynthesisRequest


class PyTorchInferenceEngine:
    def __init__(
        self,
        model_cache: PyTorchModelCache,
        project_root: Path,
        pipeline: PyTorchSynthesisPipeline | None = None,
    ) -> None:
        self._model_cache = model_cache
        self._pipeline = pipeline or PyTorchSynthesisPipeline(project_root=project_root)

    def synthesize_stream(self, request: PreparedSynthesisRequest) -> tuple[int, Iterator[np.ndarray]]:
        model = self._model_cache.get_engine(gpt_path=request.gpt_path, sovits_path=request.sovits_path)
        return self._pipeline.synthesize_stream(model, request)
