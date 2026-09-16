from __future__ import annotations

from pydantic import BaseModel, Field


class SpeechRequest(BaseModel):
    input: str = Field(description="要合成的文本内容。")
    voice: str = Field(default="default", description="使用的音色 ID。")
    model: str = Field(default="gpt-sovits-v2", description="模型标识。")
    model_id: str | None = Field(default=None, description="可选 catalog 模型 ID；不复用 model 家族字段。")
    model_revision: str = Field(default="", description="可选模型内容 revision。")
    preset_id: str | None = Field(default=None, description="可选预设 ID；缺失时投影为 voice。")
    preset_revision: str = Field(default="", description="可选预设 revision。")
    response_format: str = Field(default="wav", description="响应格式；常见值为 `wav` 或流式音频格式。")
    speed: float | None = Field(default=None, description="可选的语速覆盖值。")
    top_k: int | None = Field(default=None, description="可选的采样 top_k 覆盖值。")
    top_p: float | None = Field(default=None, description="可选的采样 top_p 覆盖值。")
    temperature: float | None = Field(default=None, description="可选的采样温度覆盖值。")
    text_lang: str = Field(default="auto", description="输入文本语言。")
    text_split_method: str = Field(default="cut5", description="文本切分策略。")
    chunk_length: int = Field(default=24, description="分块推理长度。")
    history_window: int = Field(default=4, description="跨 chunk 历史窗口大小。")
    pause_length: float | None = Field(default=None, description="句间停顿时长覆盖值。")
    noise_scale: float | None = Field(default=None, description="可选的 noise scale 覆盖值。")
    sid: int | None = Field(default=None, description="可选的说话人索引。")
    ref_audio: str | None = Field(default=None, description="参考音频路径；JSON 请求时直接传路径。")
    ref_text: str | None = Field(default=None, description="参考文本。")
    ref_lang: str | None = Field(default=None, description="参考文本语言。")
    style_ref_audio: str | None = Field(default=None, description="可选风格参考音频；S1 仅传递。")
    style_ref_text: str | None = Field(default=None, description="可选风格参考文本。")
    style_ref_lang: str | None = Field(default=None, description="可选风格参考文本语言。")
