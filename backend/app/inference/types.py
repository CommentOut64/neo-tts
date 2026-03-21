from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterator

import numpy as np
from pydantic import BaseModel


class InferenceRequest(BaseModel):
    input_text: str
    voice_name: str
    model: str
    response_format: str
    text_lang: str
    chunk_length: int
    history_window: int
    speed: float
    top_k: int
    top_p: float
    temperature: float
    pause_length: float
    noise_scale: float
    ref_audio: str
    ref_text: str
    ref_lang: str
    gpt_path: str
    sovits_path: str


class PreparedSynthesisRequest(InferenceRequest):
    pass


@dataclass(frozen=True)
class ModelHandle:
    cache_key: str
    gpt_path: str
    sovits_path: str
    engine: Any


@dataclass(frozen=True)
class InferenceStreamResult:
    sample_rate: int
    stream: Iterator[np.ndarray]
