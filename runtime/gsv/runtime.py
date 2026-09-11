from __future__ import annotations

import copy
import threading
from collections.abc import Mapping
from dataclasses import fields, is_dataclass, replace
from pathlib import Path

import numpy as np

from .diagnostics import bind_model, cleanup_operation, cleanup_status, runtime_entrypoint

from .errors import (
    RuntimeFailure,
    RuntimePhase,
    check_cancelled,
    error_info,
    fail,
    report_failure,
)
from .language import LanguageResolutionService
from .loader import load_model as _load_model
from .types import (
    BoundaryRequest,
    BoundaryResult,
    Control,
    ModelLease,
    ModelSpec,
    ReferenceFeatures,
    ReferenceRequest,
    RenderConfig,
    RuntimeConfig,
    RuntimeDescription,
    SegmentRequest,
    SegmentResult,
    SynthesisRequest,
    SynthesisResult,
)


class GSVRuntime:
    def __init__(self, config: RuntimeConfig | None = None, *, backend_factory=None) -> None:
        self.config = config or RuntimeConfig(resources_root=str(Path(__file__).resolve().parents[2]))
        self._backend_factory = backend_factory
        self._leases: dict[str, ModelLease] = {}
        self._active: dict[str, int] = {}
        self._pending_release: set[str] = set()
        self._close_requested = False
        self._closed = False
        self._lock = threading.RLock()
        self._compute_lock = threading.Lock()
        self._language = LanguageResolutionService(self.config.resources_root)

    def _ensure_open(self, control=None):
        if self._closed or self._close_requested:
            raise RuntimeFailure(error_info("RUNTIME_CLOSED", checkpoint="lifecycle.open", message="Runtime is closed.", control=control))

    @runtime_entrypoint(RuntimePhase.MODEL, "model.load", "MODEL_LOAD_FAILED")
    def load_model(self, spec: ModelSpec, observer=None, *, control=None) -> ModelLease:
        try:
            bind_model(device=self.config.device, dtype=self.config.dtype)
            with self._lock:
                self._ensure_open()
                check_cancelled(control, "model.start", observer)
                lease = _load_model(spec, self.config, observer, self._backend_factory)
                try:
                    check_cancelled(control, "model.publish", observer)
                except RuntimeFailure:
                    cleanup_operation("model.cancelled_release", lambda: getattr(lease.backend, "close", lambda: None)())
                    raise
                self._leases[lease.lease_id] = lease
                return lease
        except RuntimeFailure as exc:
            raise report_failure(observer, exc)

    def _lease(self, lease: ModelLease, control=None) -> ModelLease:
        with self._lock:
            self._ensure_open(control)
            current = self._leases.get(lease.lease_id)
        if current is None:
            raise RuntimeFailure(error_info("LEASE_EXPIRED", checkpoint="lifecycle.lease", message="Model lease is not active.", control=control))
        return current

    def _enter(self, lease: ModelLease, control=None) -> ModelLease:
        with self._lock:
            self._ensure_open(control)
            current = self._leases.get(lease.lease_id)
            if current is None:
                raise RuntimeFailure(error_info("LEASE_EXPIRED", checkpoint="lifecycle.lease", message="Model lease is not active.", control=control))
            if current.identity != lease.identity:
                raise RuntimeFailure(error_info("STALE_REQUEST", checkpoint="lifecycle.identity", message="Model lease identity has changed.", control=control))
            self._active[current.lease_id] = self._active.get(current.lease_id, 0) + 1
            bind_model(current)
            return current

    @runtime_entrypoint(RuntimePhase.REFERENCE, "reference.prepare", "REFERENCE_FEATURE_FAILED")
    def prepare_reference(self, lease: ModelLease, reference: ReferenceRequest, control: Control | None = None, observer=None) -> ReferenceFeatures:
        control = control or Control()
        current = None
        try:
            current = self._enter(lease, control)
            check_cancelled(control, "reference.start", observer)
            resolution = self._language.resolve_or_reuse(reference.language, reference.text, reference.language_resolution, observer=observer)
            reference = replace(reference, language=resolution.inference_language, language_resolution=resolution)
            with self._compute_lock:
                if not reference.text.strip() or not reference.audio_path:
                    raise RuntimeFailure(error_info("REFERENCE_INVALID", checkpoint="reference.validate", message="Reference audio and text are required.", control=control))
                payload = _cpu_copy(current.backend.prepare_reference(reference, control, observer))
                check_cancelled(control, "reference.output", observer)
                data = getattr(getattr(getattr(current.backend, "engine", None), "hps", None), "data", None)
                sample_rate = int(getattr(data, "sampling_rate", current.identity.sample_rate))
                result = ReferenceFeatures(
                    reference_id=reference.identity or reference.audio_path,
                    content_revision=reference.content_revision,
                    model_revision=current.identity.gpt_revision,
                    sovits_revision=current.identity.sovits_revision,
                    processing_revision=self.config.processing_revision,
                    sample_rate=sample_rate,
                    semantic_tokens=tuple(_sequence_value(_payload_value(payload, "semantic_tokens", "semantic"))),
                    phones=tuple(_sequence_value(_payload_value(payload, "phones", "phones"))),
                    payload=payload,
                )
                return result
        except RuntimeFailure as exc:
            raise report_failure(observer, exc, control)
        except Exception as exc:
            info = error_info("REFERENCE_FEATURE_FAILED", checkpoint="reference.prepare", message="Reference features could not be prepared.", control=control)
            raise fail(observer, info, exc) from exc
        finally:
            if current is not None:
                cleanup_operation("lifecycle.activity_release", lambda: self._leave(current.lease_id))

    @runtime_entrypoint(RuntimePhase.SEMANTIC, "semantic.segment", "ACOUSTIC_FAILED")
    def render_segment(self, lease: ModelLease, segment: SegmentRequest, features: ReferenceFeatures, config: RenderConfig, control: Control | None = None, observer=None) -> SegmentResult:
        control = control or Control(segment_id=segment.segment_id)
        current = None
        try:
            current = self._enter(lease, control)
            if control.segment_id is not None and control.segment_id != segment.segment_id:
                raise RuntimeFailure(error_info("STALE_REQUEST", checkpoint="segment.identity", message="Segment request identity does not match its control.", control=control))
            _validate_features(current, features, self.config.processing_revision, control)
            check_cancelled(control, "semantic.start", observer)
            resolution = self._language.resolve_or_reuse(segment.language, segment.text, segment.language_resolution, observer=observer)
            segment = replace(segment, language=resolution.inference_language, language_resolution=resolution)
            with self._compute_lock:
                payload = current.backend.render_segment(segment, features.payload, config, control, observer)
                check_cancelled(control, "output.segment", observer)
                audio = _validated_audio(getattr(payload, "core_audio", getattr(payload, "audio", payload)), control)
                result = SegmentResult(
                    segment_id=segment.segment_id,
                    render_version=segment.render_version,
                    sample_rate=current.identity.sample_rate,
                    audio=audio,
                    frame_count=int(getattr(payload, "decoder_frame_count", 0)),
                    phones=tuple(getattr(payload, "phone_ids", ())),
                    semantic=tuple(getattr(payload, "semantic_tokens", ())),
                    left_margin_audio=_validated_optional_audio(
                        getattr(payload, "left_margin_audio", np.zeros(0)), control
                    ),
                    right_margin_audio=_validated_optional_audio(
                        getattr(payload, "right_margin_audio", np.zeros(0)), control
                    ),
                    trace=_cpu_copy(getattr(payload, "trace", {}) or {}),
                )
                if result.audio.size == 0:
                    raise RuntimeFailure(error_info("EMPTY_AUDIO", checkpoint="output.segment", message="Segment produced no audio.", control=control))
                return result
        except RuntimeFailure as exc:
            raise report_failure(observer, exc, control)
        except Exception as exc:
            info = error_info("ACOUSTIC_FAILED", checkpoint="acoustic.segment", message="Segment rendering failed.", control=control)
            raise fail(observer, info, exc) from exc
        finally:
            if current is not None:
                cleanup_operation("lifecycle.activity_release", lambda: self._leave(current.lease_id))

    @runtime_entrypoint(RuntimePhase.BOUNDARY, "boundary.render", "BOUNDARY_RENDER_FAILED")
    def render_boundary(self, lease: ModelLease, boundary: BoundaryRequest, left: SegmentResult, right: SegmentResult, features: ReferenceFeatures, config: RenderConfig, control: Control | None = None, observer=None) -> BoundaryResult:
        control = control or Control(edge_id=boundary.edge_id)
        current = None
        try:
            current = self._enter(lease, control)
            if control.edge_id is not None and control.edge_id != boundary.edge_id:
                raise RuntimeFailure(error_info("STALE_REQUEST", checkpoint="boundary.identity", message="Boundary request identity does not match its control.", control=control))
            check_cancelled(control, "boundary.start", observer)
            _validate_features(current, features, self.config.processing_revision, control)
            if left.segment_id != boundary.left_segment_id or right.segment_id != boundary.right_segment_id:
                raise RuntimeFailure(error_info("BOUNDARY_CONTEXT_INCOMPATIBLE", checkpoint="boundary.validate", message="Boundary segment identities do not match.", control=control))
            if left.sample_rate != current.identity.sample_rate or right.sample_rate != current.identity.sample_rate:
                raise RuntimeFailure(error_info("BOUNDARY_CONTEXT_INCOMPATIBLE", checkpoint="boundary.validate", message="Boundary sample rates do not match the model.", control=control))
            with self._compute_lock:
                payload = current.backend.render_boundary(boundary, left, right, features.payload, config, control, observer)
                check_cancelled(control, "output.boundary", observer)
                audio = _validated_audio(getattr(payload, "boundary_audio", getattr(payload, "audio", payload)), control)
                if audio.size == 0:
                    raise RuntimeFailure(error_info("EMPTY_AUDIO", checkpoint="output.boundary", message="Boundary produced no audio.", control=control))
                return BoundaryResult(boundary.edge_id, boundary.left_segment_id, boundary.right_segment_id, boundary.edge_version, current.identity.sample_rate, audio, getattr(payload, "boundary_strategy", boundary.effective_strategy or boundary.strategy), _cpu_copy(getattr(payload, "trace", {}) or {}))
        except RuntimeFailure as exc:
            raise report_failure(observer, exc, control)
        except Exception as exc:
            info = error_info("BOUNDARY_RENDER_FAILED", checkpoint="boundary.render", message="Boundary rendering failed.", control=control)
            raise fail(observer, info, exc) from exc
        finally:
            if current is not None:
                cleanup_operation("lifecycle.activity_release", lambda: self._leave(current.lease_id))

    @runtime_entrypoint(RuntimePhase.ACOUSTIC, "synthesis.run", "UNEXPECTED_RUNTIME_ERROR")
    def synthesize(self, request: SynthesisRequest, control: Control | None = None, observer=None) -> SynthesisResult:
        control = control or Control()
        self._ensure_open(control)
        check_cancelled(control, "synthesis.start", observer)
        spec = getattr(request, "model_spec", None)
        if spec is None:
            raise RuntimeFailure(error_info("MODEL_NOT_FOUND", checkpoint="model.resolve", message="SynthesisRequest requires a model_spec."))
        lease = self.load_model(spec, observer)
        current = None
        try:
            current = self._enter(lease, control)
            with self._compute_lock:
                text_resolution = self._language.resolve_or_reuse(request.language, request.text, request.language_resolution, observer=observer)
                reference_resolution = self._language.resolve_or_reuse(
                    request.reference.language, request.reference.text, request.reference.language_resolution, observer=observer
                )
                request = replace(
                    request,
                    language=text_resolution.inference_language,
                    language_resolution=text_resolution,
                    reference=replace(
                        request.reference,
                        language=reference_resolution.inference_language,
                        language_resolution=reference_resolution,
                    ),
                )
                audio = current.backend.synthesize(request, control, observer)
                check_cancelled(control, "output.synthesis", observer)
                result = SynthesisResult(current.identity.sample_rate, _validated_audio(audio, control))
                if result.audio.size == 0:
                    raise RuntimeFailure(error_info("EMPTY_AUDIO", checkpoint="output.synthesis", message="Synthesis produced no audio.", control=control))
                return result
        except RuntimeFailure as exc:
            raise report_failure(observer, exc, control)
        except Exception as exc:
            info = error_info("UNEXPECTED_RUNTIME_ERROR", checkpoint="synthesis.run", message="Synthesis failed.", control=control)
            raise fail(observer, info, exc) from exc
        finally:
            if current is not None:
                cleanup_operation("lifecycle.activity_release", lambda: self._leave(lease.lease_id))
            cleanup_operation("lifecycle.synthesis_release", lambda: self.release(lease))

    @runtime_entrypoint(RuntimePhase.DEVICE, "device.move", "DEVICE_TRANSFER_FAILED")
    def move_model(self, lease: ModelLease, device: str, dtype: str, *, observer=None, control=None) -> ModelLease:
        with self._compute_lock, self._lock:
            current = self._lease(lease)
            if self._active.get(current.lease_id, 0):
                raise RuntimeFailure(error_info("DEVICE_TRANSFER_FAILED", checkpoint="device.move", message="Model is active."))
            try:
                current.backend.move_to(device, dtype)
            except Exception as exc:
                raise RuntimeFailure(error_info("DEVICE_TRANSFER_FAILED", checkpoint="device.move", message="Model transfer failed."), exc) from exc
            identity = replace(current.identity, device=current.backend.device, dtype=str(current.backend.dtype).removeprefix("torch."))
            updated = replace(current, identity=identity)
            self._leases[current.lease_id] = updated
            return updated

    @runtime_entrypoint(RuntimePhase.LIFECYCLE, "lifecycle.release", "UNEXPECTED_RUNTIME_ERROR")
    def release(self, lease: ModelLease, *, observer=None, control=None) -> None:
        with self._lock:
            if self._active.get(lease.lease_id, 0):
                self._pending_release.add(lease.lease_id)
                cleanup_status("lifecycle.release", "deferred")
                return
            current = self._leases.pop(lease.lease_id, None)
            self._pending_release.discard(lease.lease_id)
        if current is None:
            cleanup_status("lifecycle.release", "already_released")
            return
        close_backend = getattr(current.backend, "close", None)
        if callable(close_backend):
            cleanup_operation("lifecycle.backend_close", close_backend)

    def _leave(self, lease_id: str) -> None:
        should_release = False
        lease = None
        should_close = False
        with self._lock:
            remaining = self._active.get(lease_id, 0) - 1
            if remaining > 0:
                self._active[lease_id] = remaining
            else:
                self._active.pop(lease_id, None)
            should_release = lease_id in self._pending_release and lease_id in self._leases
            if should_release:
                lease = self._leases.get(lease_id)
            should_close = self._close_requested and not self._active
        if should_release and lease is not None:
            self.release(lease)
        if should_close:
            self.close()

    @runtime_entrypoint(RuntimePhase.LIFECYCLE, "lifecycle.close", "UNEXPECTED_RUNTIME_ERROR")
    def close(self, *, observer=None, control=None) -> None:
        with self._lock:
            if self._active:
                self._close_requested = True
                cleanup_status("lifecycle.close", "deferred")
                return
            leases = tuple(self._leases.values())
            self._leases.clear()
            self._closed = True
        failures = []
        for lease in leases:
            bind_model(lease)
            close_backend = getattr(lease.backend, "close", None)
            if callable(close_backend):
                try:
                    cleanup_operation("lifecycle.backend_close", close_backend)
                except RuntimeFailure as exc:
                    failures.append(exc)
        try:
            cleanup_operation("lifecycle.language_close", self._language.close)
        except RuntimeFailure as exc:
            failures.append(exc)
        if failures:
            raise failures[0]

    @runtime_entrypoint(RuntimePhase.LIFECYCLE, "lifecycle.describe", "UNEXPECTED_RUNTIME_ERROR")
    def describe(self, *, observer=None, control=None) -> RuntimeDescription:
        return RuntimeDescription("gsv", "1", self.config.processing_revision, ("synthesis", "segment", "boundary"), self.config.device, self.config.dtype)


_default_runtime = GSVRuntime()
load_model = _default_runtime.load_model
prepare_reference = _default_runtime.prepare_reference
render_segment = _default_runtime.render_segment
render_boundary = _default_runtime.render_boundary
synthesize = _default_runtime.synthesize
describe = _default_runtime.describe
release = _default_runtime.release
close = _default_runtime.close


def _validate_features(current: ModelLease, features: ReferenceFeatures, processing_revision: str, control: Control) -> None:
    if features.model_revision != current.identity.gpt_revision or features.sovits_revision != current.identity.sovits_revision:
        raise RuntimeFailure(error_info("REFERENCE_STALE", checkpoint="reference.validate", message="Reference features belong to a different model revision.", control=control))
    if features.processing_revision and features.processing_revision != processing_revision:
        raise RuntimeFailure(error_info("REFERENCE_STALE", checkpoint="reference.validate", message="Reference features use an incompatible processing revision.", control=control))


@runtime_entrypoint(RuntimePhase.OUTPUT, "output.validate", "ACOUSTIC_OUTPUT_INVALID")
def _validated_audio(value, control: Control) -> np.ndarray:
    try:
        audio = np.asarray(value, dtype=np.float32).copy()
    except Exception as exc:
        raise RuntimeFailure(error_info("ACOUSTIC_OUTPUT_INVALID", checkpoint="output.validate", message="Audio output is not numeric.", control=control)) from exc
    if audio.ndim != 1 or audio.size == 0:
        raise RuntimeFailure(error_info("EMPTY_AUDIO", checkpoint="output.validate", message="Audio output is empty or has an invalid shape.", control=control))
    if not np.isfinite(audio).all():
        raise RuntimeFailure(error_info("NAN_OR_INF_OUTPUT", checkpoint="output.validate", message="Audio output contains NaN or Inf.", control=control))
    return audio


@runtime_entrypoint(RuntimePhase.OUTPUT, "output.margin_validate", "ACOUSTIC_OUTPUT_INVALID")
def _validated_optional_audio(value, control: Control) -> np.ndarray:
    try:
        audio = np.asarray(value, dtype=np.float32).copy()
    except Exception as exc:
        raise RuntimeFailure(error_info("ACOUSTIC_OUTPUT_INVALID", checkpoint="output.validate", message="Audio output is not numeric.", control=control)) from exc
    if audio.ndim != 1:
        raise RuntimeFailure(error_info("ACOUSTIC_OUTPUT_INVALID", checkpoint="output.validate", message="Audio output has an invalid shape.", control=control))
    if not np.isfinite(audio).all():
        raise RuntimeFailure(error_info("NAN_OR_INF_OUTPUT", checkpoint="output.validate", message="Audio output contains NaN or Inf.", control=control))
    return audio


def _payload_value(payload, attribute: str, key: str):
    if isinstance(payload, Mapping):
        return payload.get(key)
    return getattr(payload, attribute, None)


def _sequence_value(value):
    if value is None:
        return ()
    if isinstance(value, np.ndarray):
        return value.reshape(-1).tolist()
    return value


def _cpu_copy(value):
    """Copy boundary data so callers never own backend/device storage."""
    import torch

    if isinstance(value, torch.Tensor):
        dtype = torch.float32 if value.is_floating_point() else value.dtype
        return value.detach().to(device="cpu", dtype=dtype).clone()
    if isinstance(value, np.ndarray):
        return value.copy()
    if isinstance(value, Mapping):
        return {key: _cpu_copy(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return tuple(_cpu_copy(item) for item in value)
    if isinstance(value, list):
        return [_cpu_copy(item) for item in value]
    if is_dataclass(value):
        return replace(value, **{field.name: _cpu_copy(getattr(value, field.name)) for field in fields(value)})
    return copy.deepcopy(value)
