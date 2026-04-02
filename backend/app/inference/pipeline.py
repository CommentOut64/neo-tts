from __future__ import annotations

from pathlib import Path
from typing import Any, Iterator

import numpy as np

from backend.app.inference.text_processing import normalize_whitespace
from backend.app.inference.types import CancelChecker, PreparedSynthesisRequest, ProgressCallback


class PyTorchSynthesisPipeline:
    def __init__(self, project_root: Path) -> None:
        self._project_root = project_root

    def synthesize_stream(
        self,
        model: Any,
        request: PreparedSynthesisRequest,
        *,
        progress_callback: ProgressCallback | None = None,
        should_cancel: CancelChecker | None = None,
    ) -> tuple[int, Iterator[np.ndarray]]:
        normalized_text = normalize_whitespace(request.input_text)
        if not normalized_text:
            raise ValueError("Input text is empty after normalization.")

        reference_audio = self._resolve_ref_audio(request.ref_audio)
        stream = model.infer_optimized(
            ref_wav_path=reference_audio,
            prompt_text=request.ref_text,
            prompt_lang=request.ref_lang,
            text=normalized_text,
            text_lang=request.text_lang,
            text_split_method=request.text_split_method,
            top_k=request.top_k,
            top_p=request.top_p,
            temperature=request.temperature,
            speed=request.speed,
            chunk_length=request.chunk_length,
            noise_scale=request.noise_scale,
            history_window=request.history_window,
            pause_length=request.pause_length,
            progress_callback=progress_callback,
            should_cancel=should_cancel,
        )
        sample_rate = int(model.hps.data.sampling_rate)
        return sample_rate, stream

    def _resolve_ref_audio(self, ref_audio: str) -> str:
        path = Path(ref_audio)
        if not path.is_absolute():
            path = self._project_root / path
        return str(path.resolve())
