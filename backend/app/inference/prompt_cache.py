from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
import hashlib
import threading

import numpy as np
import torch


@dataclass(frozen=True)
class PromptCacheKey:
    reference_audio_path: str
    reference_text: str
    reference_language: str
    model_version: str
    inference_config_fingerprint: str

    def short(self) -> str:
        encoded = "|".join(
            [
                self.reference_audio_path,
                self.reference_text,
                self.reference_language,
                self.model_version,
                self.inference_config_fingerprint,
            ]
        )
        return hashlib.sha1(encoded.encode("utf-8")).hexdigest()[:12]


@dataclass
class PromptCacheEntry:
    reference_semantic_tokens: np.ndarray
    reference_spectrogram_cpu: torch.Tensor
    reference_speaker_embedding_cpu: torch.Tensor
    prompt_phones: list[int]
    prompt_bert_cpu: torch.Tensor
    prompt_norm_text: str


class PromptCache:
    def __init__(self, *, max_entries: int = 8) -> None:
        self._max_entries = max(1, int(max_entries))
        self._entries: OrderedDict[PromptCacheKey, PromptCacheEntry] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key: PromptCacheKey) -> PromptCacheEntry | None:
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return None
            self._entries.move_to_end(key)
            return self._clone_entry(entry)

    def put(self, key: PromptCacheKey, entry: PromptCacheEntry) -> None:
        normalized = self._normalize_entry(entry)
        with self._lock:
            self._entries[key] = normalized
            self._entries.move_to_end(key)
            while len(self._entries) > self._max_entries:
                self._entries.popitem(last=False)

    def entry_count(self) -> int:
        with self._lock:
            return len(self._entries)

    @staticmethod
    def _normalize_entry(entry: PromptCacheEntry) -> PromptCacheEntry:
        return PromptCacheEntry(
            reference_semantic_tokens=np.array(entry.reference_semantic_tokens, dtype=np.int64, copy=True),
            reference_spectrogram_cpu=entry.reference_spectrogram_cpu.detach().to("cpu").clone(),
            reference_speaker_embedding_cpu=entry.reference_speaker_embedding_cpu.detach().to("cpu").clone(),
            prompt_phones=list(entry.prompt_phones),
            prompt_bert_cpu=entry.prompt_bert_cpu.detach().to("cpu").clone(),
            prompt_norm_text=entry.prompt_norm_text,
        )

    @staticmethod
    def _clone_entry(entry: PromptCacheEntry) -> PromptCacheEntry:
        return PromptCacheEntry(
            reference_semantic_tokens=np.array(entry.reference_semantic_tokens, dtype=np.int64, copy=True),
            reference_spectrogram_cpu=entry.reference_spectrogram_cpu.clone(),
            reference_speaker_embedding_cpu=entry.reference_speaker_embedding_cpu.clone(),
            prompt_phones=list(entry.prompt_phones),
            prompt_bert_cpu=entry.prompt_bert_cpu.clone(),
            prompt_norm_text=entry.prompt_norm_text,
        )
