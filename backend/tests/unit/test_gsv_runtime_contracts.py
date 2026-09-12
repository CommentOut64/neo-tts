from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from runtime.gsv import (
    BoundaryRequest,
    Control,
    ModelSpec,
    ReferenceRequest,
    RenderConfig,
    RuntimeConfig,
    RuntimeDiagnosticCollector,
    RuntimeFailure,
    SegmentRequest,
    SegmentResult,
)
from runtime.gsv.language import LanguageResolutionService
from runtime.gsv.runtime import GSVRuntime


def _spec(tmp_path):
    gpt = tmp_path / "gpt.ckpt"
    sovits = tmp_path / "sovits.pth"
    gpt.write_bytes(b"gpt")
    sovits.write_bytes(b"sovits")
    return ModelSpec(str(gpt), str(sovits))


class Backend:
    def __init__(self, spec, config):
        self.engine = SimpleNamespace(hps=SimpleNamespace(data=SimpleNamespace(sampling_rate=32000)))

    def prepare_reference(self, request, control, observer):
        return {"reference": request.text}

    def render_segment(self, request, features, config, control, observer):
        return SimpleNamespace(core_audio=np.ones(16, dtype=np.float32), decoder_frame_count=1, phone_ids=[1], semantic_tokens=[2], trace={})

    def render_boundary(self, request, left, right, features, config, control, observer):
        return SimpleNamespace(boundary_audio=np.zeros(4, dtype=np.float32), boundary_strategy="crossfade_only", trace={})


def test_runtime_contracts_are_immutable_and_absolute(tmp_path):
    config = RuntimeConfig(str(tmp_path))
    assert config.resources_root == str(tmp_path.resolve())
    with pytest.raises(ValueError):
        ModelSpec("relative.ckpt", "relative.pth")


def test_runtime_lifecycle_and_cpu_results(tmp_path):
    runtime = GSVRuntime(RuntimeConfig(str(tmp_path)), backend_factory=Backend)
    lease = runtime.load_model(_spec(tmp_path))
    features = runtime.prepare_reference(lease, ReferenceRequest(str(tmp_path / "ref.wav"), "hello", "en"))
    result = runtime.render_segment(lease, SegmentRequest("seg", "hello", "en"), features, RenderConfig())
    assert result.audio.dtype == np.float32
    runtime.release(lease)
    with pytest.raises(RuntimeFailure) as exc:
        runtime.render_segment(lease, SegmentRequest("seg", "hello", "en"), features, RenderConfig())
    assert exc.value.info.error_code == "LEASE_EXPIRED"
    runtime.close()


def test_reference_features_are_cpu_isolated_and_revision_checked(tmp_path):
    import torch

    class TensorBackend(Backend):
        def __init__(self, spec, config):
            super().__init__(spec, config)
            self.source = torch.ones(2)

        def prepare_reference(self, request, control, observer):
            return {"tensor": self.source, "ids": torch.tensor([2**30 + 1], dtype=torch.int64)}

    runtime = GSVRuntime(RuntimeConfig(str(tmp_path)), backend_factory=TensorBackend)
    lease = runtime.load_model(_spec(tmp_path))
    features = runtime.prepare_reference(lease, ReferenceRequest(str(tmp_path / "ref.wav"), "hello", "en"))
    features.payload["tensor"][0] = 9
    assert features.payload["tensor"].device.type == "cpu"
    assert lease.backend.source.tolist() == [1, 1]
    assert features.payload["ids"].dtype == torch.int64
    assert features.payload["ids"].item() == 2**30 + 1
    stale = features.__class__(
        reference_id=features.reference_id,
        content_revision=features.content_revision,
        model_revision="stale",
        sovits_revision=features.sovits_revision,
        processing_revision=features.processing_revision,
        sample_rate=features.sample_rate,
    )
    with pytest.raises(RuntimeFailure) as exc:
        runtime.render_segment(lease, SegmentRequest("seg", "hello", "en"), stale, RenderConfig())
    assert exc.value.info.error_code == "REFERENCE_STALE"
    runtime.close()


def test_close_during_render_defers_backend_release(tmp_path):
    import threading

    started = threading.Event()
    proceed = threading.Event()

    class BlockingBackend(Backend):
        def render_segment(self, request, features, config, control, observer):
            started.set()
            proceed.wait(timeout=2)
            return super().render_segment(request, features, config, control, observer)

        def close(self):
            self.closed = True

    runtime = GSVRuntime(RuntimeConfig(str(tmp_path)), backend_factory=BlockingBackend)
    lease = runtime.load_model(_spec(tmp_path))
    features = runtime.prepare_reference(lease, ReferenceRequest(str(tmp_path / "ref.wav"), "hello", "en"))
    thread = threading.Thread(target=lambda: runtime.render_segment(lease, SegmentRequest("seg", "hello", "en"), features, RenderConfig()))
    thread.start()
    assert started.wait(timeout=2)
    runtime.close()
    assert lease.lease_id in runtime._leases
    proceed.set()
    thread.join(timeout=2)
    assert lease.lease_id not in runtime._leases
    assert getattr(lease.backend, "closed", False)


@pytest.mark.parametrize("failure_kind", ["cancelled_reference", "stale_reference", "boundary_identity"])
def test_validation_failures_do_not_leak_active_lease(tmp_path, failure_kind):
    class CloseTrackingBackend(Backend):
        closed = False

        def close(self):
            self.closed = True

    runtime = GSVRuntime(RuntimeConfig(str(tmp_path)), backend_factory=CloseTrackingBackend)
    lease = runtime.load_model(_spec(tmp_path))

    if failure_kind == "cancelled_reference":
        with pytest.raises(RuntimeFailure) as exc:
            runtime.prepare_reference(
                lease,
                ReferenceRequest(str(tmp_path / "ref.wav"), "hello", "en"),
                Control(should_cancel=lambda: True),
            )
        assert exc.value.info.error_code == "CANCELLED"
    else:
        features = runtime.prepare_reference(
            lease,
            ReferenceRequest(str(tmp_path / "ref.wav"), "hello", "en"),
        )
        if failure_kind == "stale_reference":
            stale = features.__class__(
                reference_id=features.reference_id,
                content_revision=features.content_revision,
                model_revision="stale",
                sovits_revision=features.sovits_revision,
                processing_revision=features.processing_revision,
                sample_rate=features.sample_rate,
            )
            with pytest.raises(RuntimeFailure) as exc:
                runtime.render_segment(lease, SegmentRequest("seg", "hello", "en"), stale, RenderConfig())
            assert exc.value.info.error_code == "REFERENCE_STALE"
        else:
            left = SegmentResult("wrong-left", 1, 32000, np.ones(2, dtype=np.float32))
            right = SegmentResult("right", 1, 32000, np.ones(2, dtype=np.float32))
            with pytest.raises(RuntimeFailure) as exc:
                runtime.render_boundary(
                    lease,
                    BoundaryRequest("edge", "left", "right"),
                    left,
                    right,
                    features,
                    RenderConfig(),
                )
            assert exc.value.info.error_code == "BOUNDARY_CONTEXT_INCOMPATIBLE"

    runtime.release(lease)
    assert lease.backend.closed is True
    assert lease.lease_id not in runtime._active
    assert lease.lease_id not in runtime._leases


def test_segment_rejects_non_finite_margin_audio(tmp_path):
    class InvalidMarginBackend(Backend):
        def render_segment(self, request, features, config, control, observer):
            payload = super().render_segment(request, features, config, control, observer)
            payload.left_margin_audio = np.array([np.nan], dtype=np.float32)
            return payload

    runtime = GSVRuntime(RuntimeConfig(str(tmp_path)), backend_factory=InvalidMarginBackend)
    lease = runtime.load_model(_spec(tmp_path))
    features = runtime.prepare_reference(lease, ReferenceRequest(str(tmp_path / "ref.wav"), "hello", "en"))

    with pytest.raises(RuntimeFailure) as exc:
        runtime.render_segment(lease, SegmentRequest("seg", "hello", "en"), features, RenderConfig())

    assert exc.value.info.error_code == "NAN_OR_INF_OUTPUT"
    runtime.close()


def test_loader_rejects_invalid_sample_rate(tmp_path):
    class InvalidSampleRateBackend(Backend):
        def __init__(self, spec, config):
            self.sample_rate = 0

    runtime = GSVRuntime(RuntimeConfig(str(tmp_path)), backend_factory=InvalidSampleRateBackend)

    with pytest.raises(RuntimeFailure) as exc:
        runtime.load_model(_spec(tmp_path))

    assert exc.value.info.error_code == "INVALID_SAMPLE_RATE"
    runtime.close()


def test_diagnostic_collector_is_bounded():
    collector = RuntimeDiagnosticCollector(max_events=2)
    from runtime.gsv.errors import RuntimeDiagnostic, RuntimePhase
    for index in range(3):
        collector.on_diagnostic(RuntimeDiagnostic(str(index), RuntimePhase.MODEL, "checkpoint"))
    assert [event.event for event in collector.events()] == ["1", "2"]


def test_language_en_mixed_falls_back_or_fails_strict():
    service = LanguageResolutionService()
    resolved = service.resolve("en", "hello 日本語")
    assert resolved.fallback == "auto"
    with pytest.raises(RuntimeFailure) as exc:
        service.resolve("en", "hello 日本語", strict=True)
    assert exc.value.info.error_code == "MIXED_LANGUAGE_REQUIRES_AUTO"


def test_default_loader_does_not_import_application_layer(tmp_path, monkeypatch):
    import sys

    from runtime.gsv.loader import load_model

    spec = _spec(tmp_path)
    monkeypatch.delitem(sys.modules, "backend.app", raising=False)
    with pytest.raises(RuntimeFailure) as exc:
        load_model(spec, RuntimeConfig(str(tmp_path)))
    assert exc.value.info.error_code == "CHECKPOINT_CORRUPTED"
    assert "backend.app" not in sys.modules


@pytest.mark.skipif(not __import__("os").environ.get("GPT_SOVITS_E2E"), reason="real model smoke is opt-in")
def test_native_loader_loads_real_supported_checkpoint_without_factory():
    from runtime.gsv.loader import load_model

    spec = ModelSpec(
        "F:/neo-tts/pretrained_models/GPT_weights_v2Pro/Neuro1-e5.ckpt",
        "F:/neo-tts/pretrained_models/SoVITS_weights_v2Pro/Neuro1_e8_s400.pth",
    )
    lease = load_model(spec, RuntimeConfig("F:/neo-tts", device="cpu"))
    assert lease.identity.sample_rate == 32000
    assert lease.identity.device == "cpu"
    lease.backend.close()
