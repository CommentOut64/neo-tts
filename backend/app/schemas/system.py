from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class PrepareExitResponse(BaseModel):
    status: Literal["prepared"] = Field(default="prepared", description="后端退出准备已完成。")
    launcher_exit_requested: bool = Field(description="是否已成功写入 launcher 主动退出请求。")
    active_render_job_status: str | None = Field(
        default=None,
        description="若存在活动 edit-session render job，则返回其退出准备后的状态。",
    )
    inference_status: str = Field(description="旧版 TTS 推理运行态在退出准备后的最终状态。")
