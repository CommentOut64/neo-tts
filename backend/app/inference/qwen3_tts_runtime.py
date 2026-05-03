from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
import importlib
from pathlib import Path
import sys
import threading
from typing import Any, Literal

import numpy as np
import torch


GenerationMode = Literal["custom_voice", "voice_design", "voice_clone"]


@dataclass(frozen=True)
class Qwen3TTSSegmentRequest:
    segment_id: str
    text: str
    model_dir: str
    generation_mode: GenerationMode
    language: str | None = None
    speaker: str | None = None
    instruct: str | None = None
    reference_audio_path: str | None = None
    reference_text: str | None = None
    top_k: int | None = None
    top_p: float | None = None
    temperature: float | None = None
    device: str | None = None
    dtype: str | None = None
    attn_implementation: str | None = None
    extra_generate_kwargs: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Qwen3TTSSegmentResult:
    segment_id: str
    audio: np.ndarray
    sample_rate: int
    trace: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Qwen3TTSModelHandle:
    cache_key: tuple[str, str, str | None, str | None]
    model_dir: str
    model: Any


class Qwen3TTSRuntime:
    def __init__(
        self,
        *,
        qwen3_tts_root: Path | None = None,
        default_device: str = "cuda:0",
        default_dtype: str = "bfloat16",
        default_attn_implementation: str | None = "flash_attention_2",
    ) -> None:
        self._qwen3_tts_root = qwen3_tts_root.resolve() if qwen3_tts_root is not None else None
        self._default_device = default_device
        self._default_dtype = default_dtype
        self._default_attn_implementation = default_attn_implementation
        self._model_handles: dict[tuple[str, str, str | None, str | None], Qwen3TTSModelHandle] = {}
        self._lock = threading.Lock()

    def get_model_handle(
        self,
        *,
        model_dir: str,
        device: str | None = None,
        dtype: str | None = None,
        attn_implementation: str | None = None,
    ) -> Qwen3TTSModelHandle:
        resolved_model_dir = str(Path(model_dir).resolve())
        effective_device = device or self._default_device
        effective_dtype = dtype or self._default_dtype
        effective_attn_implementation = (
            attn_implementation if attn_implementation is not None else self._default_attn_implementation
        )
        cache_key = (
            resolved_model_dir,
            effective_device,
            effective_dtype,
            effective_attn_implementation,
        )
        with self._lock:
            handle = self._model_handles.get(cache_key)
            if handle is not None:
                return handle
            model_cls = self._load_model_class()
            model = model_cls.from_pretrained(
                resolved_model_dir,
                device_map=effective_device,
                dtype=self._resolve_dtype(effective_dtype),
                attn_implementation=effective_attn_implementation,
            )
            handle = Qwen3TTSModelHandle(
                cache_key=cache_key,
                model_dir=resolved_model_dir,
                model=model,
            )
            self._model_handles[cache_key] = handle
            return handle

    def render_segment(self, request: Qwen3TTSSegmentRequest) -> Qwen3TTSSegmentResult:
        handle = self.get_model_handle(
            model_dir=request.model_dir,
            device=request.device,
            dtype=request.dtype,
            attn_implementation=request.attn_implementation,
        )
        generate_kwargs = self._build_generate_kwargs(request)
        language = request.language or "Auto"
        if request.generation_mode == "custom_voice":
            if not request.speaker:
                raise ValueError("Qwen3 custom_voice requires speaker.")
            wavs, sample_rate = handle.model.generate_custom_voice(
                text=request.text,
                language=language,
                speaker=request.speaker,
                instruct=request.instruct or None,
                **generate_kwargs,
            )
        elif request.generation_mode == "voice_design":
            if not request.instruct:
                raise ValueError("Qwen3 voice_design requires instruct.")
            wavs, sample_rate = handle.model.generate_voice_design(
                text=request.text,
                language=language,
                instruct=request.instruct,
                **generate_kwargs,
            )
        elif request.generation_mode == "voice_clone":
            if not request.reference_audio_path:
                raise ValueError("Qwen3 voice_clone requires reference_audio_path.")
            wavs, sample_rate = handle.model.generate_voice_clone(
                text=request.text,
                language=language,
                ref_audio=request.reference_audio_path,
                ref_text=request.reference_text,
                **generate_kwargs,
            )
        else:
            raise ValueError(f"Unsupported Qwen3 generation_mode '{request.generation_mode}'.")
        if not wavs:
            raise RuntimeError("Qwen3-TTS returned empty audio.")
        return Qwen3TTSSegmentResult(
            segment_id=request.segment_id,
            audio=np.asarray(wavs[0], dtype=np.float32),
            sample_rate=int(sample_rate),
            trace={
                "generation_mode": request.generation_mode,
                "model_dir": handle.model_dir,
            },
        )

    def _load_model_class(self) -> Any:
        with self._prepend_qwen3_tts_root():
            module = importlib.import_module("qwen_tts")
        model_cls = getattr(module, "Qwen3TTSModel", None)
        if model_cls is None:
            raise ImportError("qwen_tts.Qwen3TTSModel is unavailable.")
        return model_cls

    def _build_generate_kwargs(self, request: Qwen3TTSSegmentRequest) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        if request.top_k is not None:
            payload["top_k"] = request.top_k
        if request.top_p is not None:
            payload["top_p"] = request.top_p
        if request.temperature is not None:
            payload["temperature"] = request.temperature
        payload.update(request.extra_generate_kwargs)
        return payload

    @staticmethod
    def _resolve_dtype(raw_dtype: str | None) -> Any:
        if raw_dtype is None:
            return None
        normalized = raw_dtype.strip().lower()
        if normalized == "float16":
            return torch.float16
        if normalized == "bfloat16":
            return torch.bfloat16
        if normalized == "float32":
            return torch.float32
        raise ValueError(f"Unsupported Qwen3 dtype '{raw_dtype}'.")

    @contextmanager
    def _prepend_qwen3_tts_root(self):
        if self._qwen3_tts_root is None:
            yield
            return
        root = str(self._qwen3_tts_root)
        inserted = False
        if root not in sys.path:
            sys.path.insert(0, root)
            inserted = True
        try:
            yield
        finally:
            if inserted:
                sys.path.remove(root)
