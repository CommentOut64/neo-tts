from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class InferenceProgressState(BaseModel):
    task_id: str | None = Field(default=None, description="当前推理任务 ID；空闲时为 null。")
    status: Literal["idle", "preparing", "inferencing", "cancelling", "completed", "cancelled", "error"] = Field(
        default="idle",
        description="当前推理状态。",
    )
    progress: float = Field(default=0.0, ge=0.0, le=1.0, description="当前推理进度，范围 0~1。")
    message: str = Field(default="", description="面向调用方的当前状态说明。")
    cancel_requested: bool = Field(default=False, description="是否已收到强制暂停或取消请求。")
    current_segment: int | None = Field(default=None, ge=0, description="当前已完成的分段数。")
    total_segments: int | None = Field(default=None, ge=0, description="本次推理预计处理的总段数。")
    result_id: str | None = Field(default=None, description="若已生成缓存结果，则为结果 ID。")
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC), description="状态最后更新时间。")


class ForcePauseResponse(BaseModel):
    accepted: bool = Field(description="是否成功接受强制暂停请求。")
    state: InferenceProgressState = Field(description="请求处理后的最新推理状态。")


class CleanupResidualsResponse(BaseModel):
    cancelled_active_task: bool = Field(description="是否对当前活动任务发出了取消请求。")
    removed_temp_ref_dirs: int = Field(description="清理掉的临时参考音频目录数量。")
    removed_result_files: int = Field(description="清理掉的历史合成结果文件数量。")
    state: InferenceProgressState = Field(description="清理后的最新推理状态。")


class DeleteSynthesisResultResponse(BaseModel):
    status: Literal["deleted"] = Field(description="删除结果，固定为 `deleted`。")
    result_id: str = Field(description="被删除的结果 ID。")


class InferenceParamsCacheUpsertRequest(BaseModel):
    payload: dict[str, Any] = Field(default_factory=dict, description="要写入缓存的推理参数字典。")


class InferenceParamsCacheResponse(BaseModel):
    payload: dict[str, Any] = Field(default_factory=dict, description="当前缓存中的推理参数。")
    updated_at: datetime | None = Field(default=None, description="缓存最后更新时间；若从未写入则为 null。")
