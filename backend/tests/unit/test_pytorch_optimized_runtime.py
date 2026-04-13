from types import SimpleNamespace

from backend.app.inference.pytorch_optimized import GPTSoVITSOptimizedInference


class _FakeModule:
    def __init__(self) -> None:
        self.moves: list[str] = []

    def to(self, device: str):
        self.moves.append(device)
        return self


def _build_runtime() -> GPTSoVITSOptimizedInference:
    runtime = object.__new__(GPTSoVITSOptimizedInference)
    runtime.device = "cuda"
    runtime.is_half = True
    runtime.resident_device = "cuda"
    runtime.ssl_model = _FakeModule()
    runtime.bert_model = _FakeModule()
    runtime.t2s_model = _FakeModule()
    runtime.vq_model = _FakeModule()
    runtime.sv_model = SimpleNamespace(embedding_model=_FakeModule())
    return runtime


def test_offload_from_gpu_moves_all_runtime_modules_to_cpu(monkeypatch):
    empty_cache_calls: list[str] = []
    gc_collect_calls: list[str] = []

    monkeypatch.setattr("backend.app.inference.pytorch_optimized.torch.cuda.empty_cache", lambda: empty_cache_calls.append("ok"))
    monkeypatch.setattr("backend.app.inference.pytorch_optimized.gc.collect", lambda: gc_collect_calls.append("ok"))

    runtime = _build_runtime()

    runtime.offload_from_gpu()

    assert runtime.resident_device == "cpu"
    assert runtime.device == "cpu"
    assert runtime.ssl_model.moves == ["cpu"]
    assert runtime.bert_model.moves == ["cpu"]
    assert runtime.t2s_model.moves == ["cpu"]
    assert runtime.vq_model.moves == ["cpu"]
    assert runtime.sv_model.embedding_model.moves == ["cpu"]
    assert empty_cache_calls == ["ok"]
    assert gc_collect_calls == ["ok"]


def test_ensure_on_gpu_restores_offloaded_runtime_modules(monkeypatch):
    monkeypatch.setattr("backend.app.inference.pytorch_optimized.torch.cuda.is_available", lambda: True)

    runtime = _build_runtime()
    runtime.offload_from_gpu()

    runtime.ensure_on_gpu()

    assert runtime.resident_device == "cuda"
    assert runtime.device == "cuda"
    assert runtime.ssl_model.moves == ["cpu", "cuda"]
    assert runtime.bert_model.moves == ["cpu", "cuda"]
    assert runtime.t2s_model.moves == ["cpu", "cuda"]
    assert runtime.vq_model.moves == ["cpu", "cuda"]
    assert runtime.sv_model.embedding_model.moves == ["cpu", "cuda"]
