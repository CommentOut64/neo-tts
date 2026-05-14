from __future__ import annotations

from importlib import import_module
from typing import Any

__all__ = ["GPTSoVITSLocalAdapter", "ExternalHttpTtsAdapter", "Qwen3TTSLocalAdapter"]


def __getattr__(name: str) -> Any:
    if name == "GPTSoVITSLocalAdapter":
        return import_module("backend.app.inference.adapters.gpt_sovits_local_adapter").GPTSoVITSLocalAdapter
    if name == "ExternalHttpTtsAdapter":
        return import_module("backend.app.inference.adapters.external_http_tts_adapter").ExternalHttpTtsAdapter
    if name == "Qwen3TTSLocalAdapter":
        return import_module("backend.app.inference.adapters.qwen3_tts_local_adapter").Qwen3TTSLocalAdapter
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
