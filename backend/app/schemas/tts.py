from __future__ import annotations

from pydantic import BaseModel


class SpeechRequest(BaseModel):
    input: str
    voice: str = "default"
    model: str = "gpt-sovits-v2"
    response_format: str = "wav"
    speed: float | None = None
    top_k: int | None = None
    top_p: float | None = None
    temperature: float | None = None
    text_lang: str = "auto"
    text_split_method: str = "cut5"
    chunk_length: int = 24
    history_window: int = 4
    pause_length: float | None = None
    noise_scale: float | None = None
    sid: int | None = None
    ref_audio: str | None = None
    ref_text: str | None = None
    ref_lang: str | None = None
