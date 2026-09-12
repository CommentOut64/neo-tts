import numpy as np
import pytest
import torch
from dataclasses import replace

from runtime.gsv import RuntimeFailure
from runtime.gsv.language import (
    LanguageResolution,
    LanguageResolutionService,
    LanguageSpan,
)
from runtime.gsv.native import _clean_text_features


def test_language_dependency_failure_is_not_replaced_by_heuristics(tmp_path):
    with pytest.raises(RuntimeFailure) as error:
        LanguageResolutionService(str(tmp_path)).resolve("auto", "Hello こんにちは")
    assert error.value.info.error_code == "LANGUAGE_RESOURCE_MISSING"


def test_language_resolution_rejects_silently_dropped_characters(monkeypatch):
    resolver = LanguageResolutionService()
    monkeypatch.setattr(resolver, "_official_spans", lambda *args: (LanguageSpan("Hello", "en"),))
    with pytest.raises(RuntimeFailure) as error:
        resolver.resolve("auto", "Hello こんにちは")
    assert error.value.info.error_code == "TEXT_FRONTEND_FAILED"


def test_g2p_consumes_all_resolved_spans_without_detecting_again(monkeypatch):
    from runtime.gsv.native import _ensure_gpt_path

    _ensure_gpt_path()
    import GPT_SoVITS.text as text_module
    from GPT_SoVITS.text import cleaner

    calls = []
    resolution = LanguageResolution("mixed", (LanguageSpan("Hello ", "en"), LanguageSpan("こんにちは", "ja")))

    def clean(text, language, version):
        calls.append((text, language))
        return [language], [1], text

    def unexpected_detection(*args, **kwargs):
        raise AssertionError("The frontend must consume the existing resolution")

    monkeypatch.setattr(cleaner, "clean_text", clean)
    monkeypatch.setattr(text_module, "cleaned_text_to_sequence", lambda phones, version: [11 if phones[0] == "en" else 22])
    monkeypatch.setattr(LanguageResolutionService, "resolve", unexpected_detection)

    phones, bert, text = _clean_text_features(
        "Hello こんにちは", "en", "v2", None, None, "cpu", torch.float32, resolution
    )
    assert calls == [("Hello ", "en"), ("こんにちは", "ja")]
    assert phones == [11, 22]
    assert bert.shape == (1024, 2)
    assert np.isfinite(bert.numpy()).all()
    assert text == "Hello こんにちは"


@pytest.mark.parametrize("declared", ["auto", "en"])
def test_real_official_resolution_keeps_japanese_and_english(declared):
    resolution = LanguageResolutionService().resolve(declared, "Hello こんにちは。")
    assert resolution.mixed
    assert {span.language for span in resolution.spans} == {"en", "ja"}
    assert "".join(span.text for span in resolution.spans).replace(" ", "") == "Helloこんにちは。"
    assert resolution.fallback == ("auto" if declared == "en" else None)


@pytest.fixture
def synthesis_runtime(tmp_path):
    from runtime.gsv import GSVRuntime, ModelSpec, RuntimeConfig

    received = []

    class Backend:
        sample_rate = 32000
        device = "cpu"
        dtype = "float32"

        def __init__(self, spec, config):
            pass

        def synthesize(self, request, control, observer):
            received.append(request)
            return np.ones(8, dtype=np.float32)

    gpt, sovits = tmp_path / "gpt", tmp_path / "sovits"
    gpt.write_bytes(b"gpt")
    sovits.write_bytes(b"sovits")
    runtime = GSVRuntime(RuntimeConfig(str(tmp_path)), backend_factory=Backend)
    yield runtime, ModelSpec(str(gpt), str(sovits)), str(tmp_path / "ref.wav"), received
    runtime.close()


def test_synthesis_reuses_matching_text_and_reference_resolution_with_fallback_diagnostic(synthesis_runtime, monkeypatch):
    from runtime.gsv import ReferenceRequest, RuntimeDiagnosticCollector, SynthesisRequest

    runtime, spec, reference_path, received = synthesis_runtime
    resolver = runtime._language
    monkeypatch.setattr(resolver, "_official_spans", lambda *args: (LanguageSpan("Hello ", "en"), LanguageSpan("こんにちは", "ja")))
    resolution = resolver.resolve("en", "Hello こんにちは")
    reference_resolution = resolver.resolve("en", "reference")

    def should_not_resolve(*args, **kwargs):
        raise AssertionError("Matching resolutions must reach synthesis without another detection")

    monkeypatch.setattr(resolver, "resolve", should_not_resolve)
    observer = RuntimeDiagnosticCollector()
    request = SynthesisRequest(
        "Hello こんにちは", ReferenceRequest(reference_path, "reference", "en", language_resolution=reference_resolution),
        language="en", model_spec=spec, language_resolution=resolution,
    )
    runtime.synthesize(request, observer=observer)
    assert received[0].language_resolution is resolution
    assert received[0].reference.language_resolution is reference_resolution
    assert received[0].language == "auto"
    assert len([event for event in observer.events() if event.event == "language_fallback"]) == 1
    assert request.language == "en"


@pytest.mark.parametrize("change,expected", [
    ("text", ("en", "changed")), ("language", ("ja", "hello")),
    ("span", ("en", "hello")), ("reference", ("en", "changed reference")),
])
def test_synthesis_recomputes_only_invalidated_resolution(synthesis_runtime, monkeypatch, change, expected):
    from runtime.gsv import ReferenceRequest, SynthesisRequest

    runtime, spec, reference_path, received = synthesis_runtime
    resolver = runtime._language
    target = resolver.resolve("en", "hello")
    reference = resolver.resolve("en", "reference")
    request = SynthesisRequest(
        "hello", ReferenceRequest(reference_path, "reference", "en", language_resolution=reference),
        language="en", model_spec=spec, language_resolution=target,
    )
    if change == "text":
        request = replace(request, text="changed")
    elif change == "language":
        request = replace(request, language="ja")
    elif change == "span":
        request = replace(request, language_resolution=replace(target, spans=(LanguageSpan("hell", "en"),)))
    else:
        request = replace(request, reference=replace(request.reference, text="changed reference"))
    calls = []
    original = resolver.resolve

    def resolve(language, text, **kwargs):
        calls.append((language, text))
        return original(language, text, **kwargs)

    monkeypatch.setattr(resolver, "resolve", resolve)
    runtime.synthesize(request)
    assert calls == [expected]
    if change == "reference":
        assert received[0].language_resolution is target
    else:
        assert received[0].reference.language_resolution is reference
        assert "".join(span.text for span in received[0].language_resolution.spans) == expected[1]
