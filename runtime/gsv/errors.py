from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field, replace

try:
    from enum import StrEnum
except ImportError:  # Python 3.10 launcher compatibility; project runtime remains 3.11+.
    from enum import Enum

    class StrEnum(str, Enum):
        pass
from collections.abc import Mapping
from typing import Protocol
import re


class RuntimePhase(StrEnum):
    RESOURCE = "resource"
    MODEL = "model"
    DEVICE = "device"
    REFERENCE = "reference"
    TEXT_FRONTEND = "text_frontend"
    SEMANTIC = "semantic"
    ACOUSTIC = "acoustic"
    BOUNDARY = "boundary"
    OUTPUT = "output"
    LIFECYCLE = "lifecycle"


@dataclass(frozen=True, slots=True)
class ErrorSpec:
    phase: RuntimePhase
    retryable: bool = False
    severity: str = "error"
    action: str = "inspect_logs"


ERROR_REGISTRY: dict[str, ErrorSpec] = {
    "RESOURCE_MISSING": ErrorSpec(RuntimePhase.RESOURCE, action="install_resource"),
    "RESOURCE_INVALID": ErrorSpec(RuntimePhase.RESOURCE),
    "RESOURCE_VERSION_UNSUPPORTED": ErrorSpec(RuntimePhase.RESOURCE),
    "MODEL_NOT_FOUND": ErrorSpec(RuntimePhase.MODEL, action="select_model"),
    "MODEL_INCOMPATIBLE": ErrorSpec(RuntimePhase.MODEL, action="select_model"),
    "MODEL_LOAD_FAILED": ErrorSpec(RuntimePhase.MODEL, retryable=True),
    "MODEL_HASH_MISMATCH": ErrorSpec(RuntimePhase.MODEL),
    "CHECKPOINT_KEY_MISSING": ErrorSpec(RuntimePhase.MODEL),
    "CHECKPOINT_SHAPE_MISMATCH": ErrorSpec(RuntimePhase.MODEL),
    "CHECKPOINT_CORRUPTED": ErrorSpec(RuntimePhase.MODEL),
    "DEVICE_UNAVAILABLE": ErrorSpec(RuntimePhase.DEVICE, action="retry_cpu"),
    "DEVICE_TRANSFER_FAILED": ErrorSpec(RuntimePhase.DEVICE, retryable=True),
    "CUDA_OOM": ErrorSpec(RuntimePhase.DEVICE, retryable=True, action="retry_cpu"),
    "ORT_PROVIDER_FAILED": ErrorSpec(RuntimePhase.DEVICE, retryable=True),
    "REFERENCE_INVALID": ErrorSpec(RuntimePhase.REFERENCE),
    "REFERENCE_DECODE_FAILED": ErrorSpec(RuntimePhase.REFERENCE, action="select_reference"),
    "REFERENCE_FEATURE_FAILED": ErrorSpec(RuntimePhase.REFERENCE, retryable=True),
    "REFERENCE_STALE": ErrorSpec(RuntimePhase.REFERENCE, action="refresh_reference"),
    "TEXT_EMPTY": ErrorSpec(RuntimePhase.TEXT_FRONTEND),
    "LANGUAGE_RESOURCE_MISSING": ErrorSpec(RuntimePhase.TEXT_FRONTEND, action="install_resource"),
    "MIXED_LANGUAGE_REQUIRES_AUTO": ErrorSpec(RuntimePhase.TEXT_FRONTEND, action="use_auto"),
    "TEXT_FRONTEND_FAILED": ErrorSpec(RuntimePhase.TEXT_FRONTEND),
    "SEMANTIC_FAILED": ErrorSpec(RuntimePhase.SEMANTIC, retryable=True),
    "SEMANTIC_INPUT_INVALID": ErrorSpec(RuntimePhase.SEMANTIC),
    "SEMANTIC_OUTPUT_INVALID": ErrorSpec(RuntimePhase.SEMANTIC),
    "ACOUSTIC_FAILED": ErrorSpec(RuntimePhase.ACOUSTIC, retryable=True),
    "ACOUSTIC_OUTPUT_INVALID": ErrorSpec(RuntimePhase.ACOUSTIC),
    "NAN_OR_INF_OUTPUT": ErrorSpec(RuntimePhase.OUTPUT),
    "BOUNDARY_CONTEXT_INCOMPATIBLE": ErrorSpec(RuntimePhase.BOUNDARY),
    "BOUNDARY_CONTEXT_MISSING": ErrorSpec(RuntimePhase.BOUNDARY),
    "BOUNDARY_RENDER_FAILED": ErrorSpec(RuntimePhase.BOUNDARY, retryable=True),
    "EMPTY_AUDIO": ErrorSpec(RuntimePhase.OUTPUT),
    "INVALID_SAMPLE_RATE": ErrorSpec(RuntimePhase.OUTPUT),
    "CANCELLED": ErrorSpec(RuntimePhase.LIFECYCLE, severity="info", action="retry"),
    "RUNTIME_CLOSED": ErrorSpec(RuntimePhase.LIFECYCLE),
    "LEASE_EXPIRED": ErrorSpec(RuntimePhase.LIFECYCLE, retryable=True),
    "STALE_REQUEST": ErrorSpec(RuntimePhase.LIFECYCLE, action="refresh_request"),
    "UNEXPECTED_RUNTIME_ERROR": ErrorSpec(RuntimePhase.LIFECYCLE),
}


@dataclass(frozen=True, slots=True)
class RuntimeErrorInfo:
    error_code: str
    phase: RuntimePhase
    checkpoint: str
    message: str
    retryable: bool = False
    severity: str = "error"
    request_id: str | None = None
    job_id: str | None = None
    segment_id: str | None = None
    edge_id: str | None = None
    model_revision: str | None = None
    cause_code: str | None = None
    details: Mapping[str, str] = field(default_factory=dict)
    action: str = "inspect_logs"
    attempt: int = 1

    def __post_init__(self) -> None:
        object.__setattr__(self, "message", safe_message(self.message))
        object.__setattr__(self, "details", safe_details(self.details))

    def safe_dict(self) -> dict[str, object]:
        return {
            "error_code": self.error_code,
            "phase": self.phase.value,
            "checkpoint": self.checkpoint,
            "message": safe_message(self.message),
            "retryable": self.retryable,
            "severity": self.severity,
            "request_id": self.request_id,
            "job_id": self.job_id,
            "segment_id": self.segment_id,
            "edge_id": self.edge_id,
            "model_revision": self.model_revision,
            "cause_code": self.cause_code,
            "details": safe_details(self.details),
            "action": self.action,
            "attempt": self.attempt,
        }


class RuntimeFailure(RuntimeError):
    def __init__(self, info: RuntimeErrorInfo, cause: BaseException | None = None) -> None:
        super().__init__(info.message)
        self.info = info
        self._reported_observers: set[int] = set()
        self._logged = False
        self.runtime_context: dict = {}
        if cause is not None:
            self.__cause__ = cause


@dataclass(frozen=True, slots=True)
class RuntimeDiagnostic:
    event: str
    phase: RuntimePhase
    checkpoint: str
    details: Mapping[str, str] = field(default_factory=dict)
    request_id: str | None = None
    job_id: str | None = None
    segment_id: str | None = None
    edge_id: str | None = None
    model_revision: str | None = None
    attempt: int = 1


class RuntimeEventSink(Protocol):
    def on_diagnostic(self, event: RuntimeDiagnostic) -> None: ...
    def on_error(self, error: RuntimeErrorInfo) -> None: ...


class RuntimeDiagnosticCollector:
    def __init__(self, max_events: int = 128) -> None:
        self._max_events = max(1, int(max_events))
        self._events: list[RuntimeDiagnostic] = []
        self._last_error: RuntimeErrorInfo | None = None

    def on_diagnostic(self, event: RuntimeDiagnostic) -> None:
        if len(self._events) >= self._max_events:
            self._events.pop(0)
        self._events.append(event)

    def on_error(self, error: RuntimeErrorInfo) -> None:
        self._last_error = error

    def events(self) -> tuple[RuntimeDiagnostic, ...]:
        return tuple(self._events)

    def last_error(self) -> RuntimeErrorInfo | None:
        return self._last_error


def error_info(code: str, *, checkpoint: str, message: str, control=None, details: Mapping[str, str] | None = None, cause_code: str | None = None) -> RuntimeErrorInfo:
    from .diagnostics import current_control, current_model

    control = control or current_control()
    spec = ERROR_REGISTRY.get(code, ERROR_REGISTRY["UNEXPECTED_RUNTIME_ERROR"])
    return RuntimeErrorInfo(
        error_code=code,
        phase=spec.phase,
        checkpoint=checkpoint,
        message=safe_message(message),
        retryable=spec.retryable,
        severity=spec.severity,
        request_id=getattr(control, "request_id", None),
        job_id=getattr(control, "job_id", None),
        segment_id=getattr(control, "segment_id", None),
        edge_id=getattr(control, "edge_id", None),
        details=dict(details or {}),
        cause_code=cause_code,
        action=spec.action,
        model_revision=current_model().get("model_revision"),
        attempt=getattr(control, "attempt", None) or 1,
    )


def emit(observer, event: RuntimeDiagnostic) -> None:
    from .diagnostics import current_control, current_model, scoped_observer

    control = current_control()
    event = replace(event, details=safe_details(event.details), model_revision=event.model_revision or current_model().get("model_revision"), attempt=getattr(control, "attempt", None) or 1, **{
        name: getattr(event, name) or getattr(control, name, None)
        for name in ("request_id", "job_id", "segment_id", "edge_id")
    })
    observer = scoped_observer(observer)
    if observer is not None and callable(getattr(observer, "on_diagnostic", None)):
        observer.on_diagnostic(event)


def fail(observer, info: RuntimeErrorInfo, cause: BaseException | None = None) -> RuntimeFailure:
    return report_failure(observer, RuntimeFailure(info, cause))


def report_failure(observer, failure: RuntimeFailure, control=None) -> RuntimeFailure:
    from .diagnostics import current_control, current_model, remember_failure, scoped_observer

    inherited = current_control()
    if control is not None:
        failure.info = replace(failure.info, **{
            name: getattr(failure.info, name) or getattr(control, name, None) or getattr(inherited, name, None)
            for name in ("request_id", "job_id", "segment_id", "edge_id")
        })
    elif inherited is not None:
        failure.info = replace(failure.info, **{
            name: getattr(failure.info, name) or getattr(inherited, name, None)
            for name in ("request_id", "job_id", "segment_id", "edge_id")
        })
    cause = failure.__cause__ or failure.__context__
    failure.info = replace(
        failure.info, model_revision=failure.info.model_revision or current_model().get("model_revision"),
        cause_code=failure.info.cause_code or (type(cause).__name__ if cause is not None else None),
        attempt=getattr(control or inherited, "attempt", None) or failure.info.attempt,
    )
    remember_failure(failure)
    observer = scoped_observer(observer)
    key = getattr(observer, "error_key", id(observer))
    if observer is not None and key not in failure._reported_observers:
        callback = getattr(observer, "on_error", None)
        if callable(callback):
            failure._reported_observers.add(key)
            callback(failure.info)
    return failure


@contextmanager
def runtime_checkpoint(observer, phase: RuntimePhase, checkpoint: str, code: str, control=None):
    emit(observer, RuntimeDiagnostic("start", phase, checkpoint))
    try:
        check_cancelled(control, checkpoint, observer)
        yield
        check_cancelled(control, checkpoint, observer)
    except RuntimeFailure as exc:
        emit(observer, RuntimeDiagnostic("failure", phase, checkpoint))
        raise report_failure(observer, exc, control)
    except Exception as exc:
        emit(observer, RuntimeDiagnostic("failure", phase, checkpoint))
        error_code = "CUDA_OOM" if type(exc).__name__ == "OutOfMemoryError" else code
        messages = {
            "RESOURCE_MISSING": "A required inference resource could not be loaded.",
            "REFERENCE_FEATURE_FAILED": "Reference audio could not be prepared.",
            "REFERENCE_DECODE_FAILED": "Reference audio could not be decoded.",
            "CHECKPOINT_CORRUPTED": "Checkpoint could not be decoded.",
            "TEXT_FRONTEND_FAILED": "Text could not be processed.",
            "SEMANTIC_FAILED": "Speech generation failed.",
            "ACOUSTIC_FAILED": "Audio generation failed.",
            "BOUNDARY_RENDER_FAILED": "Audio boundary rendering failed.",
            "CUDA_OOM": "There is not enough GPU memory for inference.",
        }
        raise fail(observer, error_info(error_code, checkpoint=checkpoint, message=messages.get(error_code, "Inference failed."), control=control), exc) from exc
    except BaseException:
        emit(observer, RuntimeDiagnostic("failure", phase, checkpoint))
        raise
    else:
        emit(observer, RuntimeDiagnostic("success", phase, checkpoint))


def check_cancelled(control, checkpoint: str, observer=None) -> None:
    from .diagnostics import current_control

    control = control or current_control()
    if control is not None and control.cancelled():
        raise fail(observer, error_info("CANCELLED", checkpoint=checkpoint, message="Inference was cancelled.", control=control))


_PRIVATE_MESSAGE = re.compile(r"(?:[A-Za-z]:[\\/]|\\\\|(?:^|\s)/(?:[^\s/]+/)|https?://|(?:api[_-]?key|password|secret|token)\s*[:=])", re.IGNORECASE)
_SAFE_DETAIL_KEYS = frozenset({"language_fallback", "elapsed_ms", "cleanup", "device", "dtype", "version", "count"})


def safe_message(message: str) -> str:
    if not isinstance(message, str) or _PRIVATE_MESSAGE.search(message):
        return "Runtime operation failed. See the local exception log for details."
    return message


def safe_details(details: Mapping) -> dict[str, str]:
    return {
        key: str(value) for key, value in details.items()
        if key in _SAFE_DETAIL_KEYS and not _PRIVATE_MESSAGE.search(str(value))
    }
