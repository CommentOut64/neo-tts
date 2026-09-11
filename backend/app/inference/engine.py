from __future__ import annotations

import time
from pathlib import Path
from typing import TYPE_CHECKING, Iterator

import numpy as np

from backend.app.core.logging import get_logger
from backend.app.inference.pipeline import PyTorchSynthesisPipeline
from backend.app.inference.types import CancelChecker, PreparedSynthesisRequest, ProgressCallback
from backend.app.inference.types import InferenceCancelledError
from backend.app.inference.runtime_errors import record_cancellation
from runtime.gsv import Control, RuntimeFailure
from runtime.gsv.diagnostics import RequestDiagnostics, cleanup_operation, request_diagnostics
from runtime.gsv.errors import report_failure

if TYPE_CHECKING:
    from backend.app.inference.model_cache import PyTorchModelCache

inference_engine_logger = get_logger("inference_engine")


class _ModelHandleStream(Iterator[np.ndarray]):
    """Own the acquired handle even before the first iteration."""

    def __init__(self, stream: Iterator[np.ndarray], model_cache: "PyTorchModelCache", cache_key: str, diagnostics: RequestDiagnostics | None = None) -> None:
        self._stream = stream
        self._model_cache = model_cache
        self._cache_key = cache_key
        self._closed = False
        self._diagnostics = diagnostics or RequestDiagnostics()

    def __next__(self) -> np.ndarray:
        with request_diagnostics(diagnostics=self._diagnostics):
            return self._next()

    def _next(self) -> np.ndarray:
        if self._closed:
            raise StopIteration
        try:
            return next(self._stream)
        except StopIteration:
            self.close()
            raise
        except BaseException as exc:
            if isinstance(exc, RuntimeFailure):
                report_failure(None, exc)
            elif isinstance(exc, InferenceCancelledError):
                record_cancellation(exc)
            try:
                self.close()
            except Exception:
                inference_engine_logger.exception("Failed to close inference stream after iteration error")
            raise

    def close(self) -> None:
        with request_diagnostics(diagnostics=self._diagnostics):
            cleanup_operation("application.stream_close", self._close, wrap_failure=False)

    def _close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            close = getattr(self._stream, "close", None)
            if close is not None:
                close()
        finally:
            cleanup_operation("application.model_handle_release", lambda: self._model_cache.release_model_handle(self._cache_key), wrap_failure=False)


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
        diagnostics = RequestDiagnostics(Control(request_id=getattr(request, "request_id", None), should_cancel=should_cancel))
        with request_diagnostics(diagnostics=diagnostics):
            try:
                return self._prepare_stream(request, diagnostics, progress_callback=progress_callback, should_cancel=should_cancel)
            except RuntimeFailure as exc:
                report_failure(None, exc)
                raise

    def _prepare_stream(self, request, diagnostics, *, progress_callback=None, should_cancel=None):
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
        except Exception as exc:
            if isinstance(exc, RuntimeFailure):
                report_failure(None, exc)
            cleanup_operation("application.model_handle_release", lambda: self._model_cache.release_model_handle(handle.cache_key), wrap_failure=False)
            raise
        inference_engine_logger.info(
            "推理流准备完成 voice_name={} sample_rate={} elapsed_ms={:.2f}",
            request.voice_name,
            sample_rate,
            (time.perf_counter() - started) * 1000,
        )
        return sample_rate, _ModelHandleStream(stream, self._model_cache, handle.cache_key, diagnostics)

    def _wrap_stream(self, *, stream: Iterator[np.ndarray], cache_key: str) -> Iterator[np.ndarray]:
        return _ModelHandleStream(stream, self._model_cache, cache_key)
