from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import json
import logging
from types import SimpleNamespace

import numpy as np
import pytest

from backend.app.inference.runtime_errors import map_runtime_error
from runtime.gsv import (
    Control, GSVRuntime, ModelSpec, ReferenceRequest, RenderConfig,
    RuntimeConfig, RuntimeFailure, SegmentRequest,
    SynthesisRequest,
)
from runtime.gsv import diagnostics
from runtime.gsv.diagnostics import RequestDiagnostics, request_diagnostics
from runtime.gsv.errors import RuntimePhase, error_info, runtime_checkpoint


class Backend:
    device = "cpu"
    dtype = "float32"
    sample_rate = 32000

    def __init__(self, spec, config):
        self.closed = False

    def prepare_reference(self, request, control, observer):
        return {"semantic": [1], "phones": [2]}

    def render_segment(self, request, features, config, control, observer):
        with runtime_checkpoint(observer, RuntimePhase.SEMANTIC, "semantic.generate", "SEMANTIC_FAILED", control):
            try:
                raise KeyError("private prompt, token=private-token")
            except KeyError as exc:
                raise ValueError(r"F:\private\model.pth") from exc

    def synthesize(self, request, control, observer):
        self.request = request
        return np.ones(8, dtype=np.float32)

    def close(self):
        self.closed = True


@pytest.fixture
def runtime_env(tmp_path, monkeypatch):
    log_dir = tmp_path / "private-logs"
    monkeypatch.setattr(diagnostics, "_exception_directory", log_dir)
    gpt, sovits = tmp_path / "gpt.ckpt", tmp_path / "sovits.pth"
    gpt.write_bytes(b"gpt")
    sovits.write_bytes(b"sovits")
    spec = ModelSpec(str(gpt), str(sovits))
    runtime = GSVRuntime(RuntimeConfig(str(tmp_path)), backend_factory=Backend)
    yield runtime, spec, log_dir
    runtime.close()


def records(directory):
    return [json.loads(line) for path in directory.glob("*.jsonl") for line in path.read_text(encoding="utf-8").splitlines()]


def test_failure_keeps_full_chain_and_cleanup_in_private_log_only(runtime_env, caplog):
    runtime, spec, log_dir = runtime_env
    caplog.set_level(logging.INFO, logger="runtime.gsv")
    state = RequestDiagnostics(Control(request_id="request-1", job_id="job-1", attempt=2), max_events=8)
    errors = []
    observer = SimpleNamespace(on_error=errors.append)
    with request_diagnostics(diagnostics=state):
        lease = runtime.load_model(spec)
        features = runtime.prepare_reference(lease, ReferenceRequest(str(log_dir / "ref.wav"), "hello", "en"))
        with pytest.raises(RuntimeFailure) as caught:
            runtime.render_segment(lease, SegmentRequest("segment-1", "hello", "en"), features, RenderConfig(), observer=observer)
        runtime.close()

    assert len(errors) == 1
    assert errors[0].job_id == "job-1"
    assert errors[0].segment_id == "segment-1"
    assert isinstance(caught.value.__cause__, ValueError)
    result, = records(log_dir)
    assert result["error"]["request_id"] == "request-1"
    assert result["error"]["cause_code"] == "ValueError"
    assert result["model"]["device"] == "cpu"
    assert result["error"]["model_revision"]
    assert result["attempt"] == 2
    assert result["cleanup"]["lifecycle.activity_release"] == "completed"
    assert result["cleanup"]["lifecycle.backend_close"] == "completed"
    assert len(result["diagnostics"]) <= 8
    assert "private-token" in result["traceback"]
    assert "KeyError" in result["traceback"] and "ValueError" in result["traceback"]
    assert [item["type"].split(".")[-1] for item in result["cause_chain"]] == ["RuntimeFailure", "ValueError", "KeyError"]
    _, payload = map_runtime_error(caught.value.info)
    assert "private-token" not in str(payload) and "private" not in str(payload)
    assert all("private-token" not in entry.getMessage() for entry in caplog.records)
    assert diagnostics.current_control() is None


@pytest.mark.parametrize("scenario,code", [
    ("closed", "RUNTIME_CLOSED"), ("missing_spec", "MODEL_NOT_FOUND"), ("cancelled", "CANCELLED"),
])
def test_synthesis_preflight_failures_emit_once_and_are_logged(runtime_env, scenario, code):
    runtime, spec, log_dir = runtime_env
    if scenario == "closed":
        runtime.close()
    reference = ReferenceRequest(str(log_dir / "ref.wav"), "hello", "en")
    request = SynthesisRequest("hello", reference, language="en", model_spec=None if scenario == "missing_spec" else spec)
    errors = []
    observer = SimpleNamespace(on_error=errors.append)
    with pytest.raises(RuntimeFailure) as caught:
        runtime.synthesize(request, Control(request_id="preflight", should_cancel=lambda: scenario == "cancelled"), observer)
    assert caught.value.info.error_code == code
    assert len(errors) == 1 and errors[0].request_id == "preflight"
    assert records(log_dir)[0]["error"]["error_code"] == code


@pytest.mark.parametrize("observer_fails", [False, True])
def test_close_attempts_every_backend_and_language_even_when_one_close_fails(runtime_env, observer_fails):
    runtime, spec, log_dir = runtime_env
    first, second = runtime.load_model(spec), runtime.load_model(spec)
    closed = []

    def fail_close():
        closed.append("first")
        raise OSError("close-failed")

    first.backend.close = fail_close
    second.backend.close = lambda: closed.append("second")
    runtime._language.close = lambda: closed.append("language")
    errors = []

    def diagnostic(event):
        if observer_fails:
            raise OSError("close observer failed")

    with pytest.raises(RuntimeFailure):
        runtime.close(observer=SimpleNamespace(on_diagnostic=diagnostic, on_error=errors.append))
    assert closed == ["first", "second", "language"]
    assert not runtime._leases and not runtime._active
    assert len(errors) == 1
    result, = records(log_dir)
    assert result["error"]["phase"] == "lifecycle"
    assert "close-failed" in result["traceback"]
    assert result["cleanup_errors"][0]["checkpoint"] == "lifecycle.backend_close"
    assert result["cleanup"]["lifecycle.language_close"] == "completed"
    if observer_fails:
        assert any("close observer failed" in error["traceback"] for error in result["cleanup_errors"])


def test_cleanup_failure_does_not_mask_synthesis_failure(runtime_env):
    runtime, spec, log_dir = runtime_env
    created = []

    class FailingBackend(Backend):
        def __init__(self, *args):
            super().__init__(*args)
            created.append(self)

        def synthesize(self, request, control, observer):
            raise RuntimeFailure(error_info("SEMANTIC_FAILED", checkpoint="semantic.generate", message="Generation failed."))

        def close(self):
            self.closed = True
            raise OSError("cleanup-also-failed")

    runtime._backend_factory = FailingBackend
    errors = []
    request = SynthesisRequest("hello", ReferenceRequest(str(log_dir / "ref.wav"), "hello", "en"), language="en", model_spec=spec)
    with pytest.raises(RuntimeFailure) as caught:
        runtime.synthesize(request, observer=SimpleNamespace(on_error=errors.append))
    assert caught.value.info.error_code == "SEMANTIC_FAILED"
    assert created[0].closed and not runtime._leases and not runtime._active
    assert len(errors) == 1
    result, = records(log_dir)
    assert result["error"]["error_code"] == "SEMANTIC_FAILED"
    assert result["cleanup"]["lifecycle.backend_close"] == "failed"
    assert "cleanup-also-failed" in result["cleanup_errors"][0]["traceback"]


def test_request_context_does_not_leak_across_threads(runtime_env):
    runtime, spec, log_dir = runtime_env
    lease = runtime.load_model(spec)
    features = runtime.prepare_reference(lease, ReferenceRequest(str(log_dir / "ref.wav"), "hello", "en"))

    def render(identity):
        with request_diagnostics(Control(request_id=identity, job_id=identity)):
            with pytest.raises(RuntimeFailure):
                runtime.render_segment(lease, SegmentRequest(identity, "hello", "en"), features, RenderConfig())
        assert diagnostics.current_control() is None

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(render, ["job-a", "job-b"]))
    assert {(r["error"]["request_id"], r["error"]["job_id"], r["error"]["segment_id"]) for r in records(log_dir)} == {
        ("job-a", "job-a", "job-a"), ("job-b", "job-b", "job-b"),
    }


def test_old_lease_identity_is_rejected_before_backend_work(runtime_env):
    runtime, spec, log_dir = runtime_env
    lease = runtime.load_model(spec)
    stale = replace(lease, identity=replace(lease.identity, gpt_revision="old"))
    with pytest.raises(RuntimeFailure) as caught:
        runtime.prepare_reference(stale, ReferenceRequest(str(log_dir / "ref.wav"), "hello", "en"))
    assert caught.value.info.error_code == "STALE_REQUEST"
    assert not runtime._active


def test_corrupt_audio_has_reference_decode_code(runtime_env, tmp_path):
    from runtime.gsv.native import _load_audio

    broken = tmp_path / "broken.wav"
    broken.write_bytes(b"not an audio file")
    with pytest.raises(RuntimeFailure) as caught:
        _load_audio(str(broken), 16000, "cpu")
    assert caught.value.info.error_code == "REFERENCE_DECODE_FAILED"
    assert map_runtime_error(caught.value.info)[0] == 422


def test_public_error_info_never_exposes_private_message_or_details():
    from runtime.gsv.errors import RuntimeErrorInfo

    info = RuntimeErrorInfo("REFERENCE_DECODE_FAILED", RuntimePhase.REFERENCE, "reference.decode", r"Cannot read F:\private\voice.wav", details={"prompt": "private text", "token": "private-token"})
    assert "private" not in str(info.safe_dict())
    assert "private" not in info.message


def test_observer_failure_is_structured_and_cannot_hide_original_error(runtime_env):
    runtime, spec, log_dir = runtime_env
    errors = []

    def diagnostic(event):
        raise ValueError("observer diagnostic failed")

    def error(info):
        errors.append(info)
        raise OSError("observer error failed")

    with pytest.raises(RuntimeFailure) as caught:
        runtime.load_model(spec, observer=SimpleNamespace(on_diagnostic=diagnostic, on_error=error))
    assert caught.value.info.checkpoint == "diagnostics.on_diagnostic"
    assert len(errors) == 1
    result, = records(log_dir)
    assert "observer diagnostic failed" in result["traceback"]
    assert "observer error failed" in result["cleanup_errors"][0]["traceback"]
    assert not runtime._leases


def test_log_write_failure_preserves_inference_failure(runtime_env, monkeypatch):
    runtime, spec, log_dir = runtime_env
    lease = runtime.load_model(spec)
    features = runtime.prepare_reference(lease, ReferenceRequest(str(log_dir / "ref.wav"), "hello", "en"))

    def disk_failure(record):
        raise OSError("log disk unavailable")

    monkeypatch.setattr(diagnostics, "_write_exception", disk_failure)
    with pytest.raises(RuntimeFailure) as caught:
        runtime.render_segment(lease, SegmentRequest("seg", "hello", "en"), features, RenderConfig())
    assert caught.value.info.error_code == "SEMANTIC_FAILED"
    assert not runtime._active


@pytest.mark.parametrize("checkpoint,event_kind", [
    ("semantic.generate", "failure"), ("lifecycle.activity_release", "start"),
])
def test_secondary_observer_failure_preserves_model_error_and_cleanup(runtime_env, checkpoint, event_kind):
    runtime, spec, log_dir = runtime_env
    lease = runtime.load_model(spec)
    features = runtime.prepare_reference(lease, ReferenceRequest(str(log_dir / "ref.wav"), "hello", "en"))
    errors = []

    def diagnostic(event):
        if event.checkpoint == checkpoint and event.event == event_kind:
            raise OSError("secondary observer failure")

    observer = SimpleNamespace(on_diagnostic=diagnostic, on_error=errors.append)
    with pytest.raises(RuntimeFailure) as caught:
        runtime.render_segment(lease, SegmentRequest("seg", "hello", "en"), features, RenderConfig(), observer=observer)
    assert caught.value.info.error_code == "SEMANTIC_FAILED"
    assert isinstance(caught.value.__cause__, ValueError)
    assert not runtime._active
    assert len(errors) == 1 and errors[0].error_code == "SEMANTIC_FAILED"
    result, = records(log_dir)
    assert result["cleanup"]["lifecycle.activity_release"] == "completed"
    assert any("secondary observer failure" in error["traceback"] for error in result["cleanup_errors"])


@pytest.mark.parametrize("operation", ["prepare_reference", "release", "close"])
def test_observer_failure_cannot_prevent_mandatory_cleanup(runtime_env, operation):
    runtime, spec, log_dir = runtime_env
    lease = runtime.load_model(spec)

    def diagnostic(event):
        if event.phase == RuntimePhase.LIFECYCLE:
            raise OSError("cleanup notification failed")

    observer = SimpleNamespace(on_diagnostic=diagnostic)
    with pytest.raises(RuntimeFailure) as caught:
        if operation == "prepare_reference":
            runtime.prepare_reference(lease, ReferenceRequest(str(log_dir / "ref.wav"), "hello", "en"), observer=observer)
        else:
            getattr(runtime, operation)(*([lease] if operation == "release" else []), observer=observer)
    assert caught.value.info.checkpoint == "diagnostics.on_diagnostic"
    assert not runtime._active
    if operation != "prepare_reference":
        assert lease.backend.closed and not runtime._leases
    result, = records(log_dir)
    assert "cleanup notification failed" in result["traceback"]
    assert "completed" in result["cleanup"].values()


def test_stream_diagnostics_follow_request_across_worker_thread_and_close(runtime_env):
    from backend.app.inference.engine import _ModelHandleStream

    runtime, spec, log_dir = runtime_env
    released = []

    def generate():
        with runtime_checkpoint(None, RuntimePhase.ACOUSTIC, "acoustic.decode", "ACOUSTIC_FAILED"):
            raise ValueError("stream inference failed")
        yield np.ones(1)

    state = RequestDiagnostics(Control(request_id="http-request"))
    stream = _ModelHandleStream(generate(), SimpleNamespace(release_model_handle=released.append), "model-key", state)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(next, stream)
        with pytest.raises(RuntimeFailure):
            future.result()
    stream.close()
    assert released == ["model-key"]
    result, = records(log_dir)
    assert result["error"]["request_id"] == "http-request"
    assert result["cleanup"]["application.model_handle_release"] == "completed"
    assert result["cleanup"]["application.stream_close"] == "completed"


@pytest.mark.parametrize("checkpoint", ["model.assemble", "model.load"])
def test_success_observer_failure_releases_unreturned_lease(runtime_env, checkpoint):
    runtime, spec, log_dir = runtime_env
    created = []

    def factory(*args):
        backend = Backend(*args)
        created.append(backend)
        return backend

    def event(value):
        if value.checkpoint == checkpoint and value.event == "success":
            raise ValueError("observer failed after construction")

    runtime._backend_factory = factory
    with pytest.raises(RuntimeFailure):
        runtime.load_model(spec, observer=SimpleNamespace(on_diagnostic=event))
    assert len(created) == 1 and created[0].closed
    assert not runtime._leases
    result, = records(log_dir)
    assert result["cleanup"]["model.notification_release"] == "completed"


def test_keyboard_interrupt_keeps_signal_and_records_cancellation(runtime_env):
    runtime, spec, log_dir = runtime_env
    lease = runtime.load_model(spec)
    features = runtime.prepare_reference(lease, ReferenceRequest(str(log_dir / "ref.wav"), "hello", "en"))

    def interrupted(*args):
        raise KeyboardInterrupt("interrupted")

    lease.backend.render_segment = interrupted
    with pytest.raises(KeyboardInterrupt):
        runtime.render_segment(lease, SegmentRequest("seg", "hello", "en"), features, RenderConfig())
    result, = records(log_dir)
    assert result["error"]["error_code"] == "CANCELLED"
    assert not runtime._active
