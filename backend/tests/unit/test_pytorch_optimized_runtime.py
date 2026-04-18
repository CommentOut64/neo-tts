from types import SimpleNamespace
import time

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


def test_warmup_logs_stage_when_t2s_infer_panel_returns_none(monkeypatch):
    logged: list[tuple[str, tuple]] = []

    class _FakeLogger:
        def info(self, message, *args):
            logged.append(("info", (message, *args)))

        def exception(self, message, *args):
            logged.append(("exception", (message, *args)))

    class _FakeT2SModel:
        def infer_panel(self, *args, **kwargs):
            return None, 0

    runtime = object.__new__(GPTSoVITSOptimizedInference)
    runtime.device = "cpu"
    runtime.is_half = False
    runtime.resident_device = "cpu"
    runtime.hps = SimpleNamespace(
        model=SimpleNamespace(version="v2"),
        data=SimpleNamespace(filter_length=1024),
    )
    runtime.get_phones_and_bert = lambda *args, **kwargs: ([1, 2, 3], None, "norm")
    runtime.t2s_model = SimpleNamespace(model=_FakeT2SModel())
    runtime.vq_model = SimpleNamespace(decode=lambda *args, **kwargs: "unused")

    monkeypatch.setattr("backend.app.inference.pytorch_optimized.inference_logger", _FakeLogger())

    runtime.warmup()

    exception_entries = [entry for entry in logged if entry[0] == "exception"]
    assert len(exception_entries) == 1
    message, stage, reason = exception_entries[0][1]
    assert message == "Warmup failed at stage={} reason={}"
    assert stage == "t2s_infer_panel"
    assert "returned no semantic tokens" in reason


def test_warmup_passes_dummy_speaker_embedding_for_v2pro_decode(monkeypatch):
    decode_calls: list[dict] = []

    class _FakeLogger:
        def info(self, message, *args):
            return None

        def exception(self, message, *args):
            raise AssertionError(f"warmup should not fail: {message} {args}")

    class _FakeT2SModel:
        def infer_panel(self, *args, **kwargs):
            return __import__("torch").ones((1, 4), dtype=__import__("torch").long), 0

    class _FakeVQModel:
        is_v2pro = True

        def decode(self, codes, text, refer, noise_scale=0.5, speed=1, sv_emb=None):
            decode_calls.append(
                {
                    "codes_shape": tuple(codes.shape),
                    "sv_emb": sv_emb,
                }
            )
            return "ok"

    runtime = object.__new__(GPTSoVITSOptimizedInference)
    runtime.device = "cpu"
    runtime.is_half = False
    runtime.resident_device = "cpu"
    runtime.hps = SimpleNamespace(
        model=SimpleNamespace(version="v2"),
        data=SimpleNamespace(filter_length=1024),
    )
    runtime.get_phones_and_bert = lambda *args, **kwargs: ([1, 2, 3], None, "norm")
    runtime.t2s_model = SimpleNamespace(model=_FakeT2SModel())
    runtime.vq_model = _FakeVQModel()
    runtime._build_dummy_warmup_speaker_embedding = lambda: "dummy-sv-emb"

    monkeypatch.setattr("backend.app.inference.pytorch_optimized.inference_logger", _FakeLogger())

    runtime.warmup()

    assert len(decode_calls) == 1
    assert decode_calls[0]["sv_emb"] == ["dummy-sv-emb"]


def test_warmup_logs_stage_boundaries_and_runtime_snapshot(monkeypatch):
    logged: list[tuple[str, tuple]] = []

    class _FakeLogger:
        def info(self, message, *args):
            logged.append(("info", (message, *args)))

        def warning(self, message, *args):
            logged.append(("warning", (message, *args)))

        def exception(self, message, *args):
            raise AssertionError(f"warmup should not fail: {message} {args}")

    class _FakeT2SModel:
        def infer_panel(self, *args, **kwargs):
            return __import__("torch").ones((1, 4), dtype=__import__("torch").long), 0

    runtime = object.__new__(GPTSoVITSOptimizedInference)
    runtime.device = "cpu"
    runtime.is_half = False
    runtime.resident_device = "cpu"
    runtime.hps = SimpleNamespace(
        model=SimpleNamespace(version="v2"),
        data=SimpleNamespace(filter_length=1024),
    )
    runtime.get_phones_and_bert = lambda *args, **kwargs: ([1, 2, 3], None, "norm")
    runtime.t2s_model = SimpleNamespace(model=_FakeT2SModel())
    runtime.vq_model = SimpleNamespace(decode=lambda *args, **kwargs: "ok")

    monkeypatch.setattr("backend.app.inference.pytorch_optimized.inference_logger", _FakeLogger())
    monkeypatch.setattr("backend.app.inference.pytorch_optimized.os.getpid", lambda: 4321)
    monkeypatch.setattr("backend.app.inference.pytorch_optimized.torch.cuda.is_available", lambda: False)

    runtime.warmup()

    info_entries = [entry[1] for entry in logged if entry[0] == "info"]
    assert ("Warmup stage begin stage={} detail={}", "phones_and_bert_en", "text='Warmup text.' lang=en") in info_entries
    assert ("Warmup stage end stage={} stage_elapsed_ms={:.2f} detail={}", "phones_and_bert_en", 0.0, "phones=3 norm_text_len=4") not in info_entries
    assert any(
        len(entry) == 4
        and entry[0] == "Warmup stage end stage={} stage_elapsed_ms={:.2f} detail={}"
        and entry[1] == "phones_and_bert_en"
        and "phones=3" in entry[3]
        and "norm_text_len=4" in entry[3]
        for entry in info_entries
    )
    assert any(
        len(entry) == 7
        and entry[0] == "Warmup context device={} resident_device={} half={} pid={} thread_id={} cuda_mem={}"
        and entry[1] == "cpu"
        and entry[2] == "cpu"
        and entry[3] is False
        and entry[4] == 4321
        and isinstance(entry[5], int)
        and entry[6] == "unavailable"
        for entry in info_entries
    )


def test_warmup_watchdog_logs_when_stage_runs_too_long(monkeypatch):
    logged: list[tuple[str, tuple]] = []

    class _FakeLogger:
        def info(self, message, *args):
            logged.append(("info", (message, *args)))

        def warning(self, message, *args):
            logged.append(("warning", (message, *args)))

        def exception(self, message, *args):
            raise AssertionError(f"warmup should not fail: {message} {args}")

    class _FakeT2SModel:
        def infer_panel(self, *args, **kwargs):
            return __import__("torch").ones((1, 4), dtype=__import__("torch").long), 0

    call_count = {"value": 0}

    def _slow_get_phones_and_bert(*args, **kwargs):
        call_count["value"] += 1
        if call_count["value"] == 1:
            time.sleep(0.05)
        return [1, 2, 3], None, "norm"

    runtime = object.__new__(GPTSoVITSOptimizedInference)
    runtime.device = "cpu"
    runtime.is_half = False
    runtime.resident_device = "cpu"
    runtime.hps = SimpleNamespace(
        model=SimpleNamespace(version="v2"),
        data=SimpleNamespace(filter_length=1024),
    )
    runtime.get_phones_and_bert = _slow_get_phones_and_bert
    runtime.t2s_model = SimpleNamespace(model=_FakeT2SModel())
    runtime.vq_model = SimpleNamespace(decode=lambda *args, **kwargs: "ok")

    monkeypatch.setattr("backend.app.inference.pytorch_optimized.inference_logger", _FakeLogger())
    monkeypatch.setattr("backend.app.inference.pytorch_optimized.torch.cuda.is_available", lambda: False)
    monkeypatch.setattr("backend.app.inference.pytorch_optimized._WARMUP_HEARTBEAT_INTERVAL_SECONDS", 0.01, raising=False)

    runtime.warmup()

    warning_entries = [entry[1] for entry in logged if entry[0] == "warning"]
    assert any(
        message == "Warmup still running stage={} stage_elapsed_ms={:.2f} total_elapsed_ms={:.2f} device={} resident_device={} half={} pid={} thread_id={} cuda_mem={} detail={}"
        and stage == "phones_and_bert_en"
        and device == "cpu"
        and resident_device == "cpu"
        and half is False
        and cuda_mem == "unavailable"
        and "text='Warmup text.'" in detail
        for message, stage, _, _, device, resident_device, half, _, _, cuda_mem, detail in warning_entries
    )


def test_extract_prompt_semantic_logs_stage_breakdown(monkeypatch):
    logged: list[tuple[str, tuple]] = []

    class _FakeLogger:
        def info(self, message, *args):
            logged.append(("info", (message, *args)))

    runtime = object.__new__(GPTSoVITSOptimizedInference)
    runtime.device = "cpu"
    runtime.is_half = False
    runtime.ssl_model = SimpleNamespace(
        model=lambda value: {
            "last_hidden_state": __import__("torch").ones((1, value.shape[-1], 3), dtype=__import__("torch").float32)
        }
    )
    runtime.vq_model = SimpleNamespace(
        extract_latent=lambda ssl_content: __import__("torch").tensor([[[5, 6, 7]]], dtype=__import__("torch").long)
    )

    monkeypatch.setattr("backend.app.inference.pytorch_optimized.inference_logger", _FakeLogger())
    monkeypatch.setattr(
        "backend.app.inference.pytorch_optimized.librosa.load",
        lambda reference_audio_path, sr: (__import__("numpy").asarray([0.1, 0.2], dtype=__import__("numpy").float32), sr),
    )

    result = runtime._extract_prompt_semantic("demo-ref.wav")

    assert result.tolist() == [5, 6, 7]
    info_entries = [entry[1] for entry in logged if entry[0] == "info"]
    assert any(
        len(entry) == 4
        and entry[0] == "Prompt semantic stage end stage={} elapsed_ms={:.2f} detail={}"
        and entry[1] == "librosa_load"
        and "samples=2" in entry[3]
        for entry in info_entries
    )
    assert any(
        len(entry) == 4
        and entry[0] == "Prompt semantic stage end stage={} elapsed_ms={:.2f} detail={}"
        and entry[1] == "ssl_model"
        and "ssl_shape=" in entry[3]
        for entry in info_entries
    )
    assert any(
        len(entry) == 4
        and entry[0] == "Prompt semantic stage end stage={} elapsed_ms={:.2f} detail={}"
        and entry[1] == "extract_latent"
        and "codes_shape=" in entry[3]
        for entry in info_entries
    )


def test_runtime_init_no_longer_calls_warmup_implicitly(monkeypatch):
    warmup_calls: list[str] = []

    class _FakeTorchModule:
        def half(self):
            return self

        def to(self, device):
            return self

        def eval(self):
            return self

        def load_state_dict(self, *args, **kwargs):
            return None

    class _FakeLightningModule(_FakeTorchModule):
        def __init__(self, config, *args, **kwargs):
            del args, kwargs
            self.config = config
            self.model = SimpleNamespace()

    monkeypatch.setattr(
        "backend.app.inference.pytorch_optimized.cnhubert.get_model",
        lambda: _FakeTorchModule(),
    )
    monkeypatch.setattr(
        "backend.app.inference.pytorch_optimized.AutoTokenizer.from_pretrained",
        lambda path: object(),
    )
    monkeypatch.setattr(
        "backend.app.inference.pytorch_optimized.AutoModelForMaskedLM.from_pretrained",
        lambda path: _FakeTorchModule(),
    )
    monkeypatch.setattr(
        "backend.app.inference.pytorch_optimized.torch.load",
        lambda path, map_location="cpu": {"config": {"data": {}}, "weight": {}},
    )
    monkeypatch.setattr(
        "backend.app.inference.pytorch_optimized.Text2SemanticLightningModule",
        _FakeLightningModule,
    )
    monkeypatch.setattr(
        "backend.app.inference.pytorch_optimized.load_sovits_new",
        lambda path: {
            "config": {
                "data": {
                    "filter_length": 1024,
                    "hop_length": 256,
                    "n_speakers": 1,
                },
                "train": {"segment_size": 4096},
                "model": {"version": "v2"},
            },
            "weight": {},
        },
    )
    monkeypatch.setattr(
        "backend.app.inference.pytorch_optimized.get_sovits_version_from_path_fast",
        lambda path: (None, "v2", None),
    )
    monkeypatch.setattr(
        "backend.app.inference.pytorch_optimized.SynthesizerTrn",
        lambda *args, **kwargs: _FakeTorchModule(),
    )
    monkeypatch.setattr(
        "backend.app.inference.pytorch_optimized.SV",
        lambda device, is_half: SimpleNamespace(embedding_model=_FakeTorchModule()),
    )
    monkeypatch.setattr(
        "backend.app.inference.pytorch_optimized.GPTSoVITSOptimizedInference.warmup",
        lambda self: warmup_calls.append("called"),
    )

    runtime = GPTSoVITSOptimizedInference("demo-gpt.ckpt", "demo-sovits.pth", "hubert", "bert")

    assert isinstance(runtime, GPTSoVITSOptimizedInference)
    assert warmup_calls == []
