from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


AdapterErrorCode = Literal[
    "adapter_unavailable",
    "adapter_not_installed",
    "model_required",
    "invalid_request",
    "render_failed",
    "timeout",
    "cancelled",
    "rate_limited",
    "quota_exceeded",
    "unsupported_capability",
    "manifest_missing",
    "manifest_schema_invalid",
    "asset_missing",
    "asset_fingerprint_mismatch",
    "secret_required",
    "model_in_use",
    "preset_in_use",
]


class BlockAdapterErrorPayload(BaseModel):
    error_code: AdapterErrorCode = Field(description="标准化 adapter 错误码。")
    message: str = Field(default="", description="面向调用方的错误说明。")
    details: dict[str, Any] = Field(default_factory=dict, description="附加诊断字段。")


class BlockAdapterError(RuntimeError):
    def __init__(
        self,
        *,
        error_code: AdapterErrorCode,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.message = message
        self.details = details or {}

    def to_payload(self) -> BlockAdapterErrorPayload:
        return BlockAdapterErrorPayload(
            error_code=self.error_code,
            message=self.message,
            details=self.details,
        )


def block_adapter_error_status_code(error_code: AdapterErrorCode) -> int:
    if error_code in {"model_required"}:
        return 404
    if error_code in {"adapter_not_installed", "model_in_use", "preset_in_use"}:
        return 409
    if error_code in {"render_failed", "timeout", "cancelled", "rate_limited", "quota_exceeded"}:
        return 422
    return 400
