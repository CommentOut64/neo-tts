from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class InferenceProgressState(BaseModel):
    task_id: str | None = None
    status: Literal["idle", "preparing", "inferencing", "cancelling", "completed", "cancelled", "error"] = "idle"
    progress: float = Field(default=0.0, ge=0.0, le=1.0)
    message: str = ""
    cancel_requested: bool = False
    current_segment: int | None = Field(default=None, ge=0)
    total_segments: int | None = Field(default=None, ge=0)
    result_id: str | None = None
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ForcePauseResponse(BaseModel):
    accepted: bool
    state: InferenceProgressState


class CleanupResidualsResponse(BaseModel):
    cancelled_active_task: bool
    removed_temp_ref_dirs: int
    removed_result_files: int
    state: InferenceProgressState


class DeleteSynthesisResultResponse(BaseModel):
    status: Literal["deleted"]
    result_id: str


class InferenceParamsCacheUpsertRequest(BaseModel):
    payload: dict[str, Any] = Field(default_factory=dict)


class InferenceParamsCacheResponse(BaseModel):
    payload: dict[str, Any] = Field(default_factory=dict)
    updated_at: datetime | None = None
