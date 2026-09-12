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


class _CloseableStream:
    def __init__(self, *, iteration_error=False, close_error=False):
        self.chunks = iter([b"a", b"b"])
        self.iteration_error = iteration_error
        self.close_error = close_error
        self.close_count = 0

    def __iter__(self):
        return self

    def __next__(self):
        if self.iteration_error:
            raise ValueError("iteration failed")
        return next(self.chunks)

    def close(self):
        self.close_count += 1
        if self.close_error:
            raise RuntimeError("close failed")


def _build_stream_engine(tmp_path, underlying):
    class _Pipeline:
        def synthesize_stream(self, model, request, **kwargs):
            return 32000, underlying

    cache = _FakeModelCache(model=object())
    engine = PyTorchInferenceEngine(model_cache=cache, project_root=tmp_path, pipeline=_Pipeline())
    _, stream = engine.synthesize_stream(_build_request())
    return cache, stream


@pytest.mark.parametrize("consumed", [0, 1, 2, 3])
def test_stream_close_releases_once_before_during_and_after_consumption(tmp_path, consumed):
    underlying = _CloseableStream()
    cache, stream = _build_stream_engine(tmp_path, underlying)

    for _ in range(consumed):
        next(stream, None)
    if consumed < 3:
        assert cache.released == []
    stream.close()
    stream.close()

    assert underlying.close_count == 1
    assert cache.released == ["demo.ckpt|demo.pth"]
    assert list(stream) == []


def test_stream_close_runs_underlying_generator_cleanup_before_release(tmp_path):
    cleaned = []

    def underlying():
        try:
            yield b"a"
            yield b"b"
        finally:
            assert cache.released == []
            cleaned.append(True)

    cache, stream = _build_stream_engine(tmp_path, underlying())
    assert next(stream) == b"a"
    stream.close()

    assert cleaned == [True]
    assert cache.released == ["demo.ckpt|demo.pth"]


def test_stream_close_error_still_releases_once(tmp_path):
    underlying = _CloseableStream(close_error=True)
    cache, stream = _build_stream_engine(tmp_path, underlying)

    with pytest.raises(RuntimeError, match="close failed"):
        stream.close()
    stream.close()

    assert underlying.close_count == 1
    assert cache.released == ["demo.ckpt|demo.pth"]
    assert list(stream) == []


@pytest.mark.parametrize("close_error", [False, True])
def test_stream_iteration_error_preserved_and_handle_released(tmp_path, close_error):
    underlying = _CloseableStream(iteration_error=True, close_error=close_error)
    cache, stream = _build_stream_engine(tmp_path, underlying)

    with pytest.raises(ValueError, match="iteration failed"):
        next(stream)
    stream.close()

    assert underlying.close_count == 1
    assert cache.released == ["demo.ckpt|demo.pth"]
    assert list(stream) == []


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
