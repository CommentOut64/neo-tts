from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Iterator

import numpy as np

from backend.app.inference.pipeline import PyTorchSynthesisPipeline
from backend.app.inference.types import CancelChecker, PreparedSynthesisRequest, ProgressCallback

if TYPE_CHECKING:
    from backend.app.inference.model_cache import PyTorchModelCache


class PyTorchInferenceEngine:
    def __init__(
        self,
        model_cache: "PyTorchModelCache",
        project_root: Path,
        pipeline: PyTorchSynthesisPipeline | None = None,
    ) -> None:
        self._model_cache = model_cache
        self._pipeline = pipeline or PyTorchSynthesisPipeline(project_root=project_root)

    def synthesize_stream(
        self,
        request: PreparedSynthesisRequest,
        *,
        progress_callback: ProgressCallback | None = None,
        should_cancel: CancelChecker | None = None,
    ) -> tuple[int, Iterator[np.ndarray]]:
        model = self._model_cache.get_engine(gpt_path=request.gpt_path, sovits_path=request.sovits_path)
        return self._pipeline.synthesize_stream(
            model,
            request,
            progress_callback=progress_callback,
            should_cancel=should_cancel,
        )
