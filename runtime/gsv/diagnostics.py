"""Request-local diagnostics; raw exceptions never travel through event sinks."""
from __future__ import annotations

from contextlib import contextmanager, nullcontext
from contextvars import ContextVar
from dataclasses import asdict, replace
from datetime import datetime, timezone
from functools import wraps
import inspect
import json
import logging
import os
from pathlib import Path
import sys
import threading
import time
import traceback
from uuid import uuid4

from .errors import (
    RuntimeDiagnostic, RuntimeDiagnosticCollector, RuntimeFailure, RuntimePhase,
    emit, error_info, fail, report_failure,
)

_request = ContextVar("gsv_request_diagnostics", default=None)
_control = ContextVar("gsv_request_control", default=None)
_model = ContextVar("gsv_request_model", default=None)
_observer = ContextVar("gsv_request_observer", default=None)
_cleanup_notifications = ContextVar("gsv_cleanup_notifications", default=None)
_logger = logging.getLogger("runtime.gsv")
_log_lock = threading.Lock()
_exception_directory: Path | None = None


def configure_exception_logging(log_dir: str | Path) -> None:
    """Select a local log directory without importing the application or opening files."""
    global _exception_directory
    _exception_directory = Path(log_dir).resolve() / "runtime-exceptions"


def current_control():
    return _control.get()


def current_model() -> dict:
    return dict(_model.get() or {})


def bind_model(lease=None, **metadata) -> None:
    value = current_model()
    if lease is not None:
        identity = lease.identity
        value.update(
            model_revision=lease.spec.model_revision or f"{identity.gpt_revision}:{identity.sovits_revision}",
            device=identity.device, dtype=identity.dtype,
            gpt_revision=identity.gpt_revision, sovits_revision=identity.sovits_revision,
            sample_rate=identity.sample_rate, quantizer=identity.quantizer,
        )
    value.update(metadata)
    _model.set(value)


def _merge_control(control=None):
    from .types import Control

    parent = current_control()
    value = control or parent or Control()
    changes = {
        name: getattr(value, name) or getattr(parent, name, None)
        for name in ("request_id", "job_id", "segment_id", "edge_id", "should_cancel")
    }
    changes["request_id"] = changes["request_id"] or changes["job_id"] or uuid4().hex
    changes["attempt"] = value.attempt or getattr(parent, "attempt", None) or 1
    return replace(value, **changes)


class RequestDiagnostics:
    """May follow an application stream across threads; never holds a ContextVar token."""

    def __init__(self, control=None, *, max_events: int = 128) -> None:
        self.control = _merge_control(control)
        self.collector = RuntimeDiagnosticCollector(max_events)
        self.cleanup: dict[str, str] = {}
        self.cleanup_errors: list[dict] = []
        self.failures: list[RuntimeFailure] = []

    def remember(self, failure: RuntimeFailure) -> None:
        if not failure._logged and all(item is not failure for item in self.failures):
            self.failures.append(failure)


@contextmanager
def request_diagnostics(control=None, *, diagnostics: RequestDiagnostics | None = None):
    parent = _request.get()
    state = diagnostics or parent or RequestDiagnostics(control)
    request_token = _request.set(state)
    control_token = _control.set(_merge_control(control or state.control))
    try:
        yield state
    finally:
        try:
            if state is not parent:
                _flush_failures(state)
        finally:
            _control.reset(control_token)
            _request.reset(request_token)


class _RequestSink:
    def __init__(self, state, observer):
        self.state = state
        self.observer = observer
        self.error_key = id(observer) if observer is not None else id(state.collector)
        self._diagnostics_failed = False

    def on_diagnostic(self, event):
        self.state.collector.on_diagnostic(event)
        callback = getattr(self.observer, "on_diagnostic", None)
        if callable(callback) and not self._diagnostics_failed:
            primary = sys.exc_info()[1]
            try:
                callback(event)
            except Exception as exc:
                self._diagnostics_failed = True
                if primary is not None:
                    self.state.cleanup_errors.append({"checkpoint": "diagnostics.on_diagnostic", "traceback": _traceback(exc)})
                    return
                failure = RuntimeFailure(error_info("UNEXPECTED_RUNTIME_ERROR", checkpoint="diagnostics.on_diagnostic", message="Runtime observer failed."), exc)
                pending = _cleanup_notifications.get()
                if pending is not None:
                    pending.append(failure)
                    return
                raise failure from exc

    def on_error(self, info):
        self.state.collector.on_error(info)
        callback = getattr(self.observer, "on_error", None)
        if callable(callback):
            try:
                callback(info)
            except Exception as exc:
                self.state.cleanup_errors.append({"checkpoint": "diagnostics.on_error", "traceback": _traceback(exc)})


def scoped_observer(observer=None):
    state = _request.get()
    if observer is None:
        observer = _observer.get()
    if state is None or isinstance(observer, _RequestSink):
        return observer
    return _RequestSink(state, observer)


def remember_failure(failure: RuntimeFailure) -> None:
    state = _request.get()
    if not failure.runtime_context:
        failure.runtime_context = current_model()
    if state is not None:
        state.remember(failure)


@contextmanager
def _finish_cleanup_before_notification_failure():
    if _cleanup_notifications.get() is not None:
        yield
        return
    pending = []
    token = _cleanup_notifications.set(pending)
    try:
        yield
    except BaseException:
        state = _request.get()
        if state is not None:
            state.cleanup_errors.extend(
                {"checkpoint": "diagnostics.on_diagnostic", "traceback": _traceback(failure)}
                for failure in pending
            )
        raise
    else:
        if pending:
            raise pending[0]
    finally:
        _cleanup_notifications.reset(token)


def runtime_entrypoint(phase: RuntimePhase, checkpoint: str, code: str):
    """Cover validation, computation and finally/cleanup with one public boundary."""
    def decorate(operation):
        signature = inspect.signature(operation)

        @wraps(operation)
        def invoke(*args, **kwargs):
            try:
                bound = signature.bind(*args, **kwargs)
            except TypeError as exc:
                with request_diagnostics(kwargs.get("control")):
                    raise fail(kwargs.get("observer"), error_info("UNEXPECTED_RUNTIME_ERROR", checkpoint=checkpoint, message="Runtime arguments are invalid."), exc) from exc
            bound.apply_defaults()
            with request_diagnostics(bound.arguments.get("control")):
                control = _merge_control(bound.arguments.get("control"))
                for argument, field in (("segment", "segment_id"), ("boundary", "edge_id")):
                    value = bound.arguments.get(argument)
                    if value is not None and getattr(control, field) is None:
                        control = replace(control, **{field: getattr(value, field)})
                control_token = _control.set(control)
                if "control" in bound.arguments:
                    bound.arguments["control"] = control
                observer = scoped_observer(bound.arguments.get("observer"))
                if "observer" in bound.arguments:
                    bound.arguments["observer"] = observer
                observer_token = _observer.set(observer)
                model_token = _model.set(current_model())
                started = time.perf_counter()
                result = None
                try:
                    lease = bound.arguments.get("lease")
                    if lease is not None:
                        bind_model(lease)
                    cleanup_scope = _finish_cleanup_before_notification_failure() if checkpoint in {"lifecycle.release", "lifecycle.close"} else nullcontext()
                    with cleanup_scope:
                        emit(observer, RuntimeDiagnostic("start", phase, checkpoint))
                        result = operation(*bound.args, **bound.kwargs)
                        if checkpoint == "model.load":
                            bind_model(result)
                        emit(observer, RuntimeDiagnostic("success", phase, checkpoint, {"elapsed_ms": f"{(time.perf_counter() - started) * 1000:.3f}"}))
                    return result
                except RuntimeFailure as exc:
                    if checkpoint in {"model.load", "model.assemble"} and result is not None:
                        owner = bound.arguments.get("self")
                        dispose = (lambda: owner.release(result)) if owner is not None else getattr(result.backend, "close", lambda: None)
                        cleanup_operation("model.notification_release", dispose)
                    emit(observer, RuntimeDiagnostic("failure", phase, checkpoint))
                    raise report_failure(observer, exc, control)
                except Exception as exc:
                    emit(observer, RuntimeDiagnostic("failure", phase, checkpoint))
                    failure_code = "CUDA_OOM" if type(exc).__name__ == "OutOfMemoryError" else code
                    raise fail(observer, error_info(failure_code, checkpoint=checkpoint, message="Runtime operation failed.", control=control), exc) from exc
                except BaseException as exc:
                    failure_code = "CANCELLED" if isinstance(exc, (KeyboardInterrupt, GeneratorExit)) or type(exc).__name__ == "CancelledError" else "UNEXPECTED_RUNTIME_ERROR"
                    emit(observer, RuntimeDiagnostic("failure", phase, checkpoint))
                    fail(observer, error_info(failure_code, checkpoint=checkpoint, message="Runtime operation was interrupted.", control=control), exc)
                    raise
                finally:
                    _model.reset(model_token)
                    _observer.reset(observer_token)
                    _control.reset(control_token)
        return invoke
    return decorate


@_finish_cleanup_before_notification_failure()
def cleanup_operation(checkpoint: str, operation, *, wrap_failure: bool = True):
    """A secondary cleanup error must not replace the original inference failure."""
    primary = sys.exc_info()[1]
    state = _request.get()
    emit(None, RuntimeDiagnostic("start", RuntimePhase.LIFECYCLE, checkpoint))
    try:
        result = operation()
    except Exception as exc:
        if state is not None:
            state.cleanup[checkpoint] = "failed"
            state.cleanup_errors.append({"checkpoint": checkpoint, "traceback": _traceback(exc)})
        emit(None, RuntimeDiagnostic("failure", RuntimePhase.LIFECYCLE, checkpoint, {"cleanup": "failed"}))
        if primary is not None:
            return None
        failure = RuntimeFailure(error_info("UNEXPECTED_RUNTIME_ERROR", checkpoint=checkpoint, message="Runtime cleanup failed."), exc)
        remember_failure(failure)
        if not wrap_failure:
            raise
        raise failure from exc
    else:
        if state is not None:
            if state.cleanup.get(checkpoint) != "failed":
                state.cleanup[checkpoint] = "completed"
        emit(None, RuntimeDiagnostic("success", RuntimePhase.LIFECYCLE, checkpoint, {"cleanup": "completed"}))
        return result


def cleanup_status(checkpoint: str, status: str) -> None:
    state = _request.get()
    if state is not None:
        state.cleanup[checkpoint] = status
    emit(None, RuntimeDiagnostic("success", RuntimePhase.LIFECYCLE, checkpoint, {"cleanup": status}))


def _traceback(exc: BaseException) -> str:
    return "".join(traceback.TracebackException.from_exception(exc, capture_locals=False).format(chain=True))


def _cause_chain(exc: BaseException) -> list[dict]:
    result, seen = [], set()
    while exc is not None and id(exc) not in seen:
        seen.add(id(exc))
        result.append({"type": f"{type(exc).__module__}.{type(exc).__qualname__}", "message": str(exc)})
        exc = exc.__cause__ or exc.__context__
    return result


def _write_exception(record: dict) -> None:
    directory = _exception_directory
    if directory is None:
        state_root = Path(os.environ.get("LOCALAPPDATA") or Path.home() / ".local" / "state")
        directory = state_root / "NeoTTS" / "runtime-exceptions"
    payload = (json.dumps(record, ensure_ascii=False) + "\n").encode("utf-8")
    with _log_lock:
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        _restrict_log_access(directory, directory=True)
        path = directory / f"runtime-{os.getpid()}.jsonl"
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        with os.fdopen(descriptor, "ab") as stream:
            _restrict_log_access(path)
            stream.write(payload)


def _restrict_log_access(path: Path, *, directory: bool = False) -> None:
    if os.name != "nt":
        path.chmod(0o700 if directory else 0o600)
        return
    # Windows ignores POSIX mode bits for ACLs. Grant only owner rights and SYSTEM.
    import ctypes
    from ctypes import wintypes

    advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    pointer = ctypes.c_void_p
    advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, ctypes.POINTER(pointer), ctypes.POINTER(wintypes.DWORD)]
    advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW.restype = wintypes.BOOL
    advapi.GetSecurityDescriptorDacl.argtypes = [pointer, ctypes.POINTER(wintypes.BOOL), ctypes.POINTER(pointer), ctypes.POINTER(wintypes.BOOL)]
    advapi.GetSecurityDescriptorDacl.restype = wintypes.BOOL
    advapi.SetNamedSecurityInfoW.argtypes = [wintypes.LPWSTR, wintypes.DWORD, wintypes.DWORD, pointer, pointer, pointer, pointer]
    advapi.SetNamedSecurityInfoW.restype = wintypes.DWORD
    kernel.LocalFree.argtypes = [pointer]
    kernel.LocalFree.restype = pointer
    inherit = "OICI" if directory else ""
    descriptor = pointer()
    sddl = f"D:P(A;{inherit};FA;;;OW)(A;{inherit};FA;;;SY)"
    if not advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW(sddl, 1, ctypes.byref(descriptor), None):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        dacl, present, defaulted = pointer(), wintypes.BOOL(), wintypes.BOOL()
        if not advapi.GetSecurityDescriptorDacl(descriptor, ctypes.byref(present), ctypes.byref(dacl), ctypes.byref(defaulted)):
            raise ctypes.WinError(ctypes.get_last_error())
        status = advapi.SetNamedSecurityInfoW(ctypes.create_unicode_buffer(str(path)), 1, 0x80000004, None, None, dacl, None)
        if status:
            raise ctypes.WinError(status)
    finally:
        kernel.LocalFree(descriptor)


def _flush_failures(state: RequestDiagnostics) -> None:
    try:
        for failure in state.failures:
            if failure._logged:
                continue
            record = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "error": failure.info.safe_dict(), "model": failure.runtime_context,
                "attempt": failure.info.attempt,
                "cleanup": dict(state.cleanup) or {"status": "not_required"},
                "cleanup_errors": list(state.cleanup_errors),
                "traceback": _traceback(failure), "cause_chain": _cause_chain(failure),
                "diagnostics": [asdict(event) for event in state.collector.events()],
            }
            try:
                _write_exception(record)
            except Exception:
                # Logging cannot replace the user's original model/render failure.
                _logger.warning("Runtime exception file could not be written.")
            level = getattr(logging, failure.info.severity.upper(), logging.ERROR)
            _logger.log(
                level, "Runtime failed code=%s phase=%s checkpoint=%s request_id=%s job_id=%s segment_id=%s edge_id=%s model_revision=%s attempt=%s cleanup=%s",
                failure.info.error_code, failure.info.phase.value, failure.info.checkpoint,
                failure.info.request_id, failure.info.job_id, failure.info.segment_id, failure.info.edge_id,
                failure.info.model_revision, failure.info.attempt, record["cleanup"],
                extra={"runtime_failure": record},
            )
            failure._logged = True
    except Exception:
        _logger.warning("Runtime failure diagnostics could not be completed.")
    finally:
        state.failures.clear()
        state.cleanup_errors.clear()
