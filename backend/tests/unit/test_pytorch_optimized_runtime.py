from types import SimpleNamespace
import time

import numpy as np
import torch

from backend.app.inference.pytorch_optimized import GPTSoVITSOptimizedInference
from backend.app.inference.editable_types import ResolvedRenderContext, ResolvedVoiceBinding
from backend.app.inference.prompt_cache import PromptCache
from backend.app.schemas.edit_session import EditableSegment, InitializeEditSessionRequest


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
    assert len(warning_entries) == 1


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


def _build_editable_runtime_for_prompt_cache() -> GPTSoVITSOptimizedInference:
    runtime = object.__new__(GPTSoVITSOptimizedInference)
    runtime.device = "cpu"
    runtime.is_half = False
    runtime.hps = SimpleNamespace(
        data=SimpleNamespace(
            sampling_rate=32000,
            filter_length=1024,
            hop_length=640,
            win_length=1024,
        ),
        model=SimpleNamespace(version="v2Pro"),
    )
    runtime.vq_model = SimpleNamespace(
        decode_with_trace=lambda *args, **kwargs: (
            torch.ones((1, 1, 14), dtype=torch.float32),
            {"semantic_shape": [1, 1, 4]},
            torch.arange(14, dtype=torch.float32).reshape(1, 1, -1),
        )
    )
    runtime.t2s_model = SimpleNamespace(
        model=SimpleNamespace(
            infer_panel=lambda *args, **kwargs: (
                torch.tensor([[0, 1, 2, 3]], dtype=torch.long),
                4,
            )
        )
    )
    return runtime


def test_build_reference_context_reuses_prompt_cache_for_same_reference():
    runtime = _build_editable_runtime_for_prompt_cache()
    counters = {
        "semantic": 0,
        "spectrogram": 0,
        "speaker": 0,
        "prompt_text": 0,
    }

    runtime._extract_prompt_semantic = lambda reference_audio_path: (
        counters.__setitem__("semantic", counters["semantic"] + 1) or torch.tensor([1, 2, 3], dtype=torch.long)
    )
    runtime.get_spepc = lambda reference_audio_path: (
        counters.__setitem__("spectrogram", counters["spectrogram"] + 1)
        or (
            torch.ones((1, 704, 12), dtype=torch.float32),
            torch.ones((1, 16000), dtype=torch.float32),
        )
    )
    runtime._compute_reference_speaker_embedding = lambda refer_audio: (
        counters.__setitem__("speaker", counters["speaker"] + 1) or torch.ones((1, 2048), dtype=torch.float32)
    )

    def _get_phones_and_bert(text, language, version, default_lang=None):
        del language, version, default_lang
        if text == "参考文本。":
            counters["prompt_text"] += 1
            return [11, 12], torch.ones((1024, 2), dtype=torch.float32), text
        raise AssertionError(f"unexpected text: {text}")

    runtime.get_phones_and_bert = _get_phones_and_bert

    request = InitializeEditSessionRequest(
        raw_text="第一句。",
        voice_id="voice-demo",
        reference_audio_path="ref.wav",
        reference_text="参考文本",
        reference_language="zh",
    )

    first = runtime.build_reference_context(request)
    second = runtime.build_reference_context(request)

    assert first.prompt_phones == [11, 12]
    assert second.prompt_phones == [11, 12]
    assert counters == {
        "semantic": 1,
        "spectrogram": 1,
        "speaker": 1,
        "prompt_text": 1,
    }


def test_build_reference_context_keeps_prompt_bert_on_cpu_when_runtime_device_is_cuda():
    class _FakeDeviceTensor:
        def __init__(self, device_type: str = "cpu") -> None:
            self.device = SimpleNamespace(type=device_type)
            self.moves: list[str] = []

        def to(self, device: str):
            self.moves.append(device)
            return _FakeDeviceTensor(device)

    class _FakePromptCache:
        def __init__(self, entry) -> None:
            self._entry = entry

        def get(self, key):
            del key
            return self._entry

    runtime = object.__new__(GPTSoVITSOptimizedInference)
    runtime.device = "cuda"
    runtime.is_half = True
    runtime.hps = SimpleNamespace(model=SimpleNamespace(version="v2Pro"))
    runtime._resolve_reference_audio_path = lambda path: path

    prompt_bert_cpu = _FakeDeviceTensor("cpu")
    spectrogram_cpu = _FakeDeviceTensor("cpu")
    speaker_embedding_cpu = _FakeDeviceTensor("cpu")
    runtime._prompt_cache = _FakePromptCache(
        SimpleNamespace(
            reference_semantic_tokens=np.asarray([1, 2, 3], dtype=np.int64),
            reference_spectrogram_cpu=spectrogram_cpu,
            reference_speaker_embedding_cpu=speaker_embedding_cpu,
            prompt_phones=[11, 12],
            prompt_bert_cpu=prompt_bert_cpu,
            prompt_norm_text="参考文本。",
        )
    )

    context = runtime.build_reference_context(
        InitializeEditSessionRequest(
            raw_text="第一句。",
            voice_id="voice-demo",
            reference_audio_path="ref.wav",
            reference_text="参考文本",
            reference_language="zh",
        )
    )

    assert context.reference_spectrogram.device.type == "cuda"
    assert context.reference_speaker_embedding.device.type == "cuda"
    assert context.prompt_bert.device.type == "cpu"
    assert prompt_bert_cpu.moves == []


def test_render_segment_base_uses_prompt_features_from_context_instead_of_recomputing():
    runtime = _build_editable_runtime_for_prompt_cache()
    call_texts: list[str] = []

    runtime._extract_prompt_semantic = lambda reference_audio_path: torch.tensor([1, 2, 3], dtype=torch.long)
    runtime.get_spepc = lambda reference_audio_path: (
        torch.ones((1, 704, 12), dtype=torch.float32),
        torch.ones((1, 16000), dtype=torch.float32),
    )
    runtime._compute_reference_speaker_embedding = lambda refer_audio: torch.ones((1, 2048), dtype=torch.float32)

    def _get_phones_and_bert(text, language, version, default_lang=None):
        del language, version, default_lang
        call_texts.append(text)
        if text == "参考文本。":
            return [11, 12], torch.ones((1024, 2), dtype=torch.float32), text
        if text == "你好。":
            return [21, 22], torch.ones((1024, 2), dtype=torch.float32), text
        raise AssertionError(f"unexpected text: {text}")

    runtime.get_phones_and_bert = _get_phones_and_bert

    context = runtime.build_reference_context(
        ResolvedRenderContext(
            voice_id="voice-demo",
            model_key="model-demo",
            reference_audio_path="ref.wav",
            reference_text="参考文本",
            reference_language="zh",
            resolved_voice_binding=ResolvedVoiceBinding(
                voice_binding_id="binding-1",
                voice_id="voice-demo",
                model_key="model-demo",
            ),
            render_profile_id="profile-1",
            render_profile_fingerprint="fp-1",
        )
    )
    call_texts.clear()

    asset = runtime.render_segment_base(
        EditableSegment(
            segment_id="seg-1",
            document_id="doc-1",
            order_key=1,
            stem="你好",
            text_language="zh",
            terminal_raw="。",
            terminal_closer_suffix="",
            terminal_source="original",
            render_version=2,
        ),
        context,
    )

    assert asset.render_version == 2
    assert call_texts == ["你好。"]


def test_build_reference_context_watchdog_logs_prompt_text_stage_and_emits_heartbeat(monkeypatch):
    logged: list[tuple[str, tuple]] = []
    progress_events: list[dict[str, object]] = []

    class _FakeLogger:
        def info(self, message, *args):
            logged.append(("info", (message, *args)))

        def warning(self, message, *args):
            logged.append(("warning", (message, *args)))

    class _FakeProcess:
        def memory_info(self):
            return SimpleNamespace(rss=256 * 1024 * 1024)

        def cpu_percent(self, interval=None):
            del interval
            return 12.5

        def num_threads(self):
            return 9

    runtime = _build_editable_runtime_for_prompt_cache()
    runtime.resident_device = "cpu"
    runtime._prompt_cache = PromptCache()
    runtime._extract_prompt_semantic = lambda reference_audio_path, stage_reporter=None: torch.tensor(
        [1, 2, 3],
        dtype=torch.long,
    )
    runtime.get_spepc = lambda reference_audio_path: (
        torch.ones((1, 704, 12), dtype=torch.float32),
        torch.ones((1, 16000), dtype=torch.float32),
    )
    runtime._compute_reference_speaker_embedding = lambda refer_audio: torch.ones((1, 2048), dtype=torch.float32)

    def _slow_get_phones_and_bert(text, language, version, default_lang=None, stage_reporter=None):
        del version, default_lang
        if callable(stage_reporter):
            stage_reporter("clean_text", language, f"chunk_index=0 text_len={len(text)}")
        time.sleep(0.05)
        return [11, 12], torch.ones((1024, 2), dtype=torch.float32), text

    runtime.get_phones_and_bert = _slow_get_phones_and_bert

    monkeypatch.setattr("backend.app.inference.pytorch_optimized.inference_logger", _FakeLogger())
    monkeypatch.setattr("backend.app.inference.pytorch_optimized.psutil.Process", lambda pid: _FakeProcess())
    monkeypatch.setattr("backend.app.inference.pytorch_optimized.os.getpid", lambda: 2468)
    monkeypatch.setattr("backend.app.inference.pytorch_optimized.torch.cuda.is_available", lambda: False)
    monkeypatch.setattr(
        "backend.app.inference.pytorch_optimized._REFERENCE_CONTEXT_HEARTBEAT_INTERVAL_SECONDS",
        0.01,
        raising=False,
    )

    runtime.build_reference_context(
        InitializeEditSessionRequest(
            raw_text="第一句。",
            voice_id="voice-demo",
            reference_audio_path="ref.wav",
            reference_text="参考文本",
            reference_language="zh",
        ),
        progress_callback=progress_events.append,
    )

    warning_entries = [entry[1] for entry in logged if entry[0] == "warning"]
    assert any(
        message
        == "Reference context still running stage={} stage_elapsed_ms={:.2f} total_elapsed_ms={:.2f} device={} resident_device={} half={} pid={} target_thread_id={} process_rss_mb={:.1f} process_cpu_percent={:.1f} thread_count={} prompt_cache_entries={} cuda_mem={} detail={}"
        and stage == "prompt_text.clean_text"
        and device == "cpu"
        and resident_device == "cpu"
        and half is False
        and pid == 2468
        and rss_mb == 256.0
        and cpu_percent == 12.5
        and thread_count == 9
        and prompt_cache_entries == 0
        and cuda_mem == "unavailable"
        and "text_len=" in detail
        for (
            message,
            stage,
            _stage_elapsed_ms,
            _total_elapsed_ms,
            device,
            resident_device,
            half,
            pid,
            _target_thread_id,
            rss_mb,
            cpu_percent,
            thread_count,
            prompt_cache_entries,
            cuda_mem,
            detail,
        ) in warning_entries
    )
    assert len(warning_entries) == 1
    heartbeat_events = [
        event
        for event in progress_events
        if event.get("status") == "preparing" and "仍在准备参考上下文" in str(event.get("message"))
    ]
    assert heartbeat_events
    assert all("progress" not in event for event in heartbeat_events)
