from __future__ import annotations

import time
from pathlib import Path
from typing import TYPE_CHECKING, Iterator

import numpy as np

from backend.app.core.logging import get_logger
from backend.app.inference.pipeline import PyTorchSynthesisPipeline
from backend.app.inference.types import CancelChecker, PreparedSynthesisRequest, ProgressCallback

if TYPE_CHECKING:
    from backend.app.inference.model_cache import PyTorchModelCache

inference_engine_logger = get_logger("inference_engine")


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
        started = time.perf_counter()
        inference_engine_logger.debug(
            "开始准备推理流 voice_name={} gpt_path={} sovits_path={}",
            request.voice_name,
            request.gpt_path,
            request.sovits_path,
        )
        handle = self._model_cache.acquire_model_handle(gpt_path=request.gpt_path, sovits_path=request.sovits_path)
        try:
            sample_rate, stream = self._pipeline.synthesize_stream(
                handle.engine,
                request,
                progress_callback=progress_callback,
                should_cancel=should_cancel,
            )
        except Exception:
            self._model_cache.release_model_handle(handle.cache_key)
            raise
        inference_engine_logger.info(
            "推理流准备完成 voice_name={} sample_rate={} elapsed_ms={:.2f}",
            request.voice_name,
            sample_rate,
            (time.perf_counter() - started) * 1000,
        )
        return sample_rate, self._wrap_stream(stream=stream, cache_key=handle.cache_key)

    def _wrap_stream(self, *, stream: Iterator[np.ndarray], cache_key: str) -> Iterator[np.ndarray]:
        try:
            for chunk in stream:
                yield chunk
        finally:
            self._model_cache.release_model_handle(cache_key)
