"""The application's single HTTP/SSE projection of Runtime failures."""
from uuid import uuid4
from functools import wraps

from runtime.gsv import Control, RuntimeFailure
from runtime.gsv.diagnostics import request_diagnostics
from runtime.gsv.errors import RuntimeErrorInfo, RuntimePhase, error_info, report_failure


def runtime_job_diagnostics(operation):
    @wraps(operation)
    def invoke(self, job_id: str):
        with request_diagnostics(Control(request_id=job_id, job_id=job_id)):
            return operation(self, job_id)
    return invoke


def record_runtime_failure(exc: RuntimeFailure, *, request_id: str | None = None) -> None:
    with request_diagnostics(Control(request_id=request_id)):
        report_failure(None, exc)


def record_cancellation(exc: BaseException, *, request_id: str | None = None) -> None:
    with request_diagnostics(Control(request_id=request_id)):
        failure = exc.__cause__ if isinstance(exc.__cause__, RuntimeFailure) else None
        if failure is None:
            failure = RuntimeFailure(error_info("CANCELLED", checkpoint="application.cancel", message="Inference was cancelled."), exc)
        report_failure(None, failure)


def map_runtime_error(
    info: RuntimeErrorInfo, *, request_id: str | None = None, job_id: str | None = None
) -> tuple[int, dict]:
    if info.error_code in {"TEXT_EMPTY", "MIXED_LANGUAGE_REQUIRES_AUTO", "REFERENCE_INVALID", "REFERENCE_DECODE_FAILED", "SEMANTIC_INPUT_INVALID"}:
        status = 422
    elif info.error_code in {"REFERENCE_STALE", "LEASE_EXPIRED", "STALE_REQUEST", "RUNTIME_CLOSED", "CANCELLED"}:
        status = 409
    elif info.phase == RuntimePhase.RESOURCE or info.error_code in {
        "MODEL_NOT_FOUND", "MODEL_INCOMPATIBLE", "CHECKPOINT_KEY_MISSING",
        "CHECKPOINT_SHAPE_MISMATCH", "CHECKPOINT_CORRUPTED", "LANGUAGE_RESOURCE_MISSING",
    }:
        status = 424
    elif info.phase == RuntimePhase.DEVICE or info.retryable:
        status = 503
    else:
        status = 500
    # Keep arbitrary details, exception chains, resource paths and tracebacks in logs.
    safe = info.safe_dict()
    error = {
        "code": info.error_code,
        "phase": info.phase.value,
        "checkpoint": info.checkpoint,
        "message": safe["message"],
        "retryable": info.retryable,
        "action": info.action,
        "request_id": info.request_id or request_id or job_id or uuid4().hex,
        "job_id": info.job_id or job_id,
        "segment_id": info.segment_id,
        "edge_id": info.edge_id,
    }
    return status, {"error": error, "message": safe["message"], "detail": safe["message"]}
