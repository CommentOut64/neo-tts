"""Independent GSV inference runtime.

The package only exposes explicit DTOs and a small lifecycle API.  Application
adapters can inject an existing inference implementation through ``backend``
without making the runtime import the application.
"""
from .errors import RuntimeDiagnostic, RuntimeDiagnosticCollector, RuntimeErrorInfo, RuntimeEventSink, RuntimeFailure
from .runtime import (
    GSVRuntime,
    close,
    describe,
    load_model,
    prepare_reference,
    release,
    render_boundary,
    render_segment,
    synthesize,
)
from .types import (
    BoundaryRequest,
    BoundaryResult,
    Control,
    ModelLease,
    ModelIdentity,
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

__all__ = [
    "BoundaryRequest", "BoundaryResult", "Control", "GSVRuntime", "ModelLease", "ModelSpec",
    "ReferenceFeatures", "ReferenceRequest", "RenderConfig", "RuntimeConfig", "RuntimeDescription",
    "RuntimeDiagnostic", "RuntimeDiagnosticCollector", "RuntimeErrorInfo", "RuntimeEventSink", "RuntimeFailure", "SegmentRequest", "SegmentResult", "ModelIdentity",
    "SynthesisRequest", "SynthesisResult", "close", "describe", "load_model", "prepare_reference", "release",
    "render_boundary", "render_segment", "synthesize",
]
