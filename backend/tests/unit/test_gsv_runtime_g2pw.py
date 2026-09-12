import importlib
import weakref
from types import SimpleNamespace

import pytest
import torch

from runtime.gsv import RuntimeConfig, RuntimeDiagnosticCollector, RuntimeFailure
from runtime.gsv.native import NativeInferenceBackend, _ensure_gpt_path


def _backend(root, device="cpu", bert_path=None):
    class Module:
        def to(self, **kwargs):
            return self

    return NativeInferenceBackend(
        t2s_model=Module(), vq_model=Module(),
        hps=SimpleNamespace(data=SimpleNamespace(sampling_rate=32000)),
        device=device, dtype=torch.float32, resources_root=str(root), bert_path=bert_path,
    )


def test_g2pw_uses_explicit_resources_and_releases_session_on_device_change(tmp_path, monkeypatch):
    _ensure_gpt_path()
    g2pw = importlib.import_module("text.g2pw")
    calls = []

    class Converter:
        def __init__(self, **kwargs):
            calls.append(kwargs)

    monkeypatch.setattr(g2pw, "G2PWPinyin", Converter)
    outside = tmp_path / "outside"
    outside.mkdir()
    monkeypatch.chdir(outside)
    resources = tmp_path / "resources"
    bert = tmp_path / "custom-tokenizer"
    backend = _backend(resources, bert_path=str(bert))
    first = weakref.ref(backend._get_g2pw())
    assert backend._get_g2pw() is first()
    assert len(calls) == 1
    assert calls[0]["model_dir"] == str(resources / "GPT_SoVITS" / "text" / "G2PWModel")
    assert calls[0]["model_source"] == str(bert)
    assert calls[0]["local_files_only"] is True
    assert calls[0]["providers"] == ["CPUExecutionProvider"]

    backend.move_to("cuda", torch.float16)
    assert first() is None
    second = weakref.ref(backend._get_g2pw())
    assert calls[1]["providers"] == ["CUDAExecutionProvider", "CPUExecutionProvider"]
    backend.close()
    assert second() is None


def test_missing_g2pw_resource_fails_without_downloading_or_pypinyin(tmp_path, monkeypatch):
    _ensure_gpt_path()
    onnx_api = importlib.import_module("text.g2pw.onnx_api")

    def unexpected_download(*args, **kwargs):
        raise AssertionError("Runtime must never download missing language resources")

    monkeypatch.setattr(onnx_api, "download_and_decompress", unexpected_download)
    monkeypatch.chdir(tmp_path)
    backend = _backend(tmp_path)
    observer = RuntimeDiagnosticCollector()
    with pytest.raises(RuntimeFailure) as failure:
        backend._get_g2pw(observer=observer)
    assert failure.value.info.error_code == "LANGUAGE_RESOURCE_MISSING"
    assert failure.value.info.checkpoint == "resources.g2pw"
    assert observer.last_error() == failure.value.info
    assert isinstance(failure.value.__cause__, FileNotFoundError)
    assert backend._g2pw is None
    assert not (tmp_path / "GPT_SoVITS").exists()


@pytest.fixture
def g2pw_resources(tmp_path):
    root = tmp_path / "g2pw"
    root.mkdir()
    files = {
        "g2pW.onnx": "fixture",
        "config.py": "use_char_phoneme = False\n",
        "POLYPHONIC_CHARS.txt": "重\tㄓㄨㄥ4\n",
        "MONOPHONIC_CHARS.txt": "中\tㄓㄨㄥ1\n",
        "bopomofo_to_pinyin_wo_tune_dict.json": "{}",
        "char_bopomofo_dict.json": "{}",
    }
    for name, content in files.items():
        (root / name).write_text(content, encoding="utf-8")
    return root


@pytest.mark.parametrize("actual_providers", [["CPUExecutionProvider"], ["CUDAExecutionProvider", "CPUExecutionProvider"]])
def test_cpu_onnx_session_is_local_and_cannot_silently_activate_cuda(g2pw_resources, monkeypatch, actual_providers):
    _ensure_gpt_path()
    onnx_api = importlib.import_module("text.g2pw.onnx_api")
    sessions = []
    tokenizer_calls = []

    class Session:
        def __init__(self, model, **kwargs):
            sessions.append((model, kwargs))
            self.fallback_disabled = False

        def get_providers(self):
            return actual_providers

        def disable_fallback(self):
            self.fallback_disabled = True

    def unexpected_download(*args, **kwargs):
        raise AssertionError("Local CPU setup must not download or preload CUDA DLLs")

    def tokenizer(path, **kwargs):
        tokenizer_calls.append((path, kwargs))
        return object()

    monkeypatch.setattr(onnx_api, "download_and_decompress", unexpected_download)
    monkeypatch.setattr(onnx_api.onnxruntime, "preload_dlls", unexpected_download)
    monkeypatch.setattr(onnx_api.onnxruntime, "get_available_providers", lambda: ["CUDAExecutionProvider", "CPUExecutionProvider"])
    monkeypatch.setattr(onnx_api.onnxruntime, "InferenceSession", Session)
    monkeypatch.setattr(onnx_api.AutoTokenizer, "from_pretrained", tokenizer)
    kwargs = {
        "model_dir": str(g2pw_resources), "model_source": str(g2pw_resources),
        "providers": ["CPUExecutionProvider"], "local_files_only": True,
    }
    if actual_providers != ["CPUExecutionProvider"]:
        with pytest.raises(RuntimeError, match="did not activate"):
            onnx_api.G2PWOnnxConverter(**kwargs)
        assert not tokenizer_calls
    else:
        converter = onnx_api.G2PWOnnxConverter(**kwargs)
        assert converter.session_g2pW.fallback_disabled
        assert tokenizer_calls == [(str(g2pw_resources), {"local_files_only": True})]
    assert sessions[0][0] == str(g2pw_resources / "g2pW.onnx")
    assert sessions[0][1]["providers"] == ["CPUExecutionProvider"]


def test_unknown_g2p_provider_is_not_silently_ignored(tmp_path):
    with pytest.raises(ValueError, match="official G2P"):
        RuntimeConfig(str(tmp_path), g2p_provider="pypinyin")
