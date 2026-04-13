from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Iterator, Mapping

import numpy as np
from pydantic import BaseModel


class InferenceRequest(BaseModel):
    input_text: str
    voice_name: str
    model: str
    response_format: str
    text_lang: str
    text_split_method: str = "cut5"
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


@dataclass
class ModelHandle:
    cache_key: str
    gpt_path: str
    sovits_path: str
    engine: Any
    active_count: int = 0
    last_used_at: float = 0.0
    resident_device: str = "cuda"
    pinned: bool = False


@dataclass(frozen=True)
class InferenceStreamResult:
    sample_rate: int
    stream: Iterator[np.ndarray]


ProgressPayload = Mapping[str, Any]
ProgressCallback = Callable[[ProgressPayload], None]
CancelChecker = Callable[[], bool]


class InferenceCancelledError(RuntimeError):
    """推理被外部强制中断时抛出的领域异常。"""
