import pytest

from backend.app.inference.runtime_errors import map_runtime_error
from runtime.gsv import Control, RuntimeFailure
from runtime.gsv.errors import (
    RuntimePhase,
    error_info,
    report_failure,
    runtime_checkpoint,
)


@pytest.mark.parametrize("code, status", [
    ("TEXT_EMPTY", 422), ("MIXED_LANGUAGE_REQUIRES_AUTO", 422),
    ("MODEL_NOT_FOUND", 424), ("LANGUAGE_RESOURCE_MISSING", 424),
    ("REFERENCE_STALE", 409), ("CUDA_OOM", 503),
    ("UNEXPECTED_RUNTIME_ERROR", 500),
])
def test_runtime_http_mapping_has_safe_fields_and_correlation(code, status):
    info = error_info(code, checkpoint="test.stage", message="safe message", details={"path": "private-path"})
    actual_status, payload = map_runtime_error(info, request_id="request-1", job_id="job-1")
    assert actual_status == status
    assert payload["error"]["code"] == code
    assert payload["error"]["request_id"] == "request-1"
    assert payload["error"]["job_id"] == "job-1"
    assert payload["detail"] == payload["message"] == "safe message"
    assert "private-path" not in str(payload)


def test_runtime_checkpoint_preserves_cause_and_emits_error_once():
    events, errors = [], []

    class Observer:
        on_diagnostic = staticmethod(events.append)
        on_error = staticmethod(errors.append)

    observer = Observer()
    cause = ValueError("private-resource-path")
    control = Control(request_id="request-1", job_id="job-1", segment_id="seg-1")
    with (
        pytest.raises(RuntimeFailure) as raised,
        runtime_checkpoint(observer, RuntimePhase.SEMANTIC, "semantic.generate", "SEMANTIC_FAILED", control),
    ):
        raise cause
    report_failure(observer, raised.value, control)
    assert raised.value.__cause__ is cause
    assert len(errors) == 1
    assert errors[0].error_code == "SEMANTIC_FAILED"
    assert errors[0].job_id == "job-1"
    assert errors[0].segment_id == "seg-1"
    assert [event.event for event in events] == ["start", "failure"]
    assert "private-resource-path" not in errors[0].message
