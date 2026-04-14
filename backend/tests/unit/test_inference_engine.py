import pytest

from backend.app.inference.engine import PyTorchInferenceEngine
from backend.app.inference.types import PreparedSynthesisRequest


class _FakeModelCache:
    def __init__(self, model) -> None:
        self.model = model
        self.acquired: list[tuple[str, str]] = []
        self.released: list[str] = []

    def acquire_model_handle(self, *, gpt_path: str, sovits_path: str):
        self.acquired.append((gpt_path, sovits_path))
        return type(
            "Handle",
            (),
            {
                "cache_key": f"{gpt_path}|{sovits_path}",
                "engine": self.model,
            },
        )()

    def release_model_handle(self, cache_key: str) -> None:
        self.released.append(cache_key)


def _build_request() -> PreparedSynthesisRequest:
    return PreparedSynthesisRequest(
        input_text="hello",
        voice_name="demo",
        model="gpt-sovits-v2",
        response_format="wav",
        text_lang="zh",
        text_split_method="cut5",
        chunk_length=24,
        history_window=4,
        speed=1.0,
        top_k=15,
        top_p=1.0,
        temperature=1.0,
        pause_length=0.3,
        noise_scale=0.35,
        ref_audio="demo.wav",
        ref_text="ref",
        ref_lang="zh",
        gpt_path="demo.ckpt",
        sovits_path="demo.pth",
    )


def test_inference_engine_releases_model_handle_after_stream_consumed(tmp_path):
    class _FakePipeline:
        def synthesize_stream(self, model, request, *, progress_callback=None, should_cancel=None):
            return 32000, iter([b"a", b"b"])

    cache = _FakeModelCache(model=object())
    engine = PyTorchInferenceEngine(model_cache=cache, project_root=tmp_path, pipeline=_FakePipeline())

    sample_rate, stream = engine.synthesize_stream(_build_request())

    assert sample_rate == 32000
    assert list(stream) == [b"a", b"b"]
    assert cache.released == ["demo.ckpt|demo.pth"]


def test_inference_engine_releases_model_handle_when_stream_errors(tmp_path):
    class _BoomPipeline:
        def synthesize_stream(self, model, request, *, progress_callback=None, should_cancel=None):
            def _stream():
                yield b"a"
                raise RuntimeError("boom")

            return 32000, _stream()

    cache = _FakeModelCache(model=object())
    engine = PyTorchInferenceEngine(model_cache=cache, project_root=tmp_path, pipeline=_BoomPipeline())

    _, stream = engine.synthesize_stream(_build_request())

    with pytest.raises(RuntimeError, match="boom"):
        list(stream)

    assert cache.released == ["demo.ckpt|demo.pth"]
