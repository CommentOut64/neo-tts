from typing import Literal

from pydantic import BaseModel, Field


class VoiceDefaults(BaseModel):
    speed: float = Field(default=1.0, description="默认语速。")
    top_k: int = Field(default=15, description="默认采样 top_k。")
    top_p: float = Field(default=1.0, description="默认采样 top_p。")
    temperature: float = Field(default=1.0, description="默认采样温度。")
    noise_scale: float = Field(default=0.35, description="默认 SoVITS 解码噪声系数。")
    pause_length: float = Field(default=0.3, description="默认句间停顿时长，单位秒。")


class VoiceProfile(BaseModel):
    name: str = Field(description="音色名称，也是接口里使用的 voice ID。")
    model_instance_id: str | None = Field(default=None, description="兼容投影来源的模型实例 ID。")
    preset_id: str | None = Field(default=None, description="兼容投影来源的预设 ID。")
    gpt_path: str = Field(description="该音色关联的 GPT 权重文件路径。")
    sovits_path: str = Field(description="该音色关联的 SoVITS 权重文件路径。")
    weight_storage_mode: Literal["external", "managed"] = Field(
        default="external",
        description="权重存储模式；`external` 表示引用外部路径，`managed` 表示复制到项目内受管目录。",
    )
    gpt_fingerprint: str = Field(default="", description="GPT 权重当前指纹；未启用时为空字符串。")
    sovits_fingerprint: str = Field(default="", description="SoVITS 权重当前指纹；未启用时为空字符串。")
    ref_audio: str = Field(description="参考音频文件路径。")
    ref_text: str = Field(description="参考音频对应的参考文本。")
    ref_lang: str = Field(default="zh", description="参考文本语言。")
    description: str = Field(default="", description="音色说明，供前端展示。")
    defaults: VoiceDefaults = Field(default_factory=VoiceDefaults, description="该音色的默认推理参数。")
    managed: bool = Field(default=False, description="是否为系统托管的音色。")
    created_at: str | None = Field(default=None, description="创建时间；若无记录则为 null。")
    updated_at: str | None = Field(default=None, description="最后更新时间；若无记录则为 null。")
