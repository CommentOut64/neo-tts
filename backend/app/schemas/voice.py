from pydantic import BaseModel, Field


class VoiceDefaults(BaseModel):
    speed: float = 1.0
    top_k: int = 15
    top_p: float = 1.0
    temperature: float = 1.0
    pause_length: float = 0.3


class VoiceProfile(BaseModel):
    name: str
    gpt_path: str
    sovits_path: str
    ref_audio: str
    ref_text: str
    ref_lang: str = Field(default="zh")
    description: str = Field(default="")
    defaults: VoiceDefaults = Field(default_factory=VoiceDefaults)
    managed: bool = Field(default=False)
    created_at: str | None = Field(default=None)
    updated_at: str | None = Field(default=None)
