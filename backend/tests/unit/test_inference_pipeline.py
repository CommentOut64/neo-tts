from pathlib import Path

import numpy as np
import pytest

from backend.app.inference.pipeline import PyTorchSynthesisPipeline
from backend.app.inference.types import PreparedSynthesisRequest


class _FakeModel:
    def __init__(self) -> None:
        self.calls = []
        self.hps = type("hps", (), {"data": type("data", (), {"sampling_rate": 32000})()})()

    def infer_optimized(self, **kwargs):
        self.calls.append(kwargs)
        return iter([np.array([0.1, 0.2], dtype=np.float32)])


def _build_request(**kwargs) -> PreparedSynthesisRequest:
    payload = {
        "input_text": "hello world",
        "voice_name": "demo",
        "model": "gpt-sovits-v2",
        "response_format": "wav",
        "text_lang": "auto",
        "text_split_method": "cut5",
        "chunk_length": 24,
        "history_window": 4,
        "speed": 1.0,
        "top_k": 15,
        "top_p": 1.0,
        "temperature": 1.0,
        "pause_length": 0.3,
        "noise_scale": 0.35,
        "ref_audio": "pretrained_models/demo.wav",
        "ref_text": "reference text",
        "ref_lang": "en",
        "gpt_path": "pretrained_models/demo.ckpt",
        "sovits_path": "pretrained_models/demo.pth",
    }
    payload.update(kwargs)
    return PreparedSynthesisRequest(**payload)


def test_pipeline_resolves_relative_ref_audio_and_delegates_to_model(tmp_path: Path):
    pipeline = PyTorchSynthesisPipeline(project_root=tmp_path)
    model = _FakeModel()
    request = _build_request()

    sample_rate, stream = pipeline.synthesize_stream(model, request)
    chunks = list(stream)

    assert sample_rate == 32000
    assert len(chunks) == 1
    assert model.calls[0]["ref_wav_path"] == str((tmp_path / "pretrained_models/demo.wav").resolve())
    assert model.calls[0]["text"] == "hello world"
    assert model.calls[0]["text_split_method"] == "cut5"


def test_pipeline_rejects_empty_input_text(tmp_path: Path):
    pipeline = PyTorchSynthesisPipeline(project_root=tmp_path)
    model = _FakeModel()
    request = _build_request(input_text="   ")

    with pytest.raises(ValueError, match="Input text is empty"):
        pipeline.synthesize_stream(model, request)


def test_pipeline_resolves_managed_ref_audio_relative_to_user_data_root(tmp_path: Path, monkeypatch):
    storage_root = tmp_path / "storage"
    reference_audio = storage_root / "managed_voices" / "voice-demo" / "references" / "ref.wav"
    reference_audio.parent.mkdir(parents=True)
    reference_audio.write_bytes(b"RIFFfake")
    monkeypatch.setenv("NEO_TTS_USER_DATA_ROOT", str(storage_root))
    model = _FakeModel()
    pipeline = PyTorchSynthesisPipeline(project_root=tmp_path)
    request = _build_request(ref_audio="managed_voices/voice-demo/references/ref.wav")

    sample_rate, stream = pipeline.synthesize_stream(model, request)
    chunks = list(stream)

    assert sample_rate == 32000
    assert len(chunks) == 1
    assert model.calls[0]["ref_wav_path"] == str(reference_audio.resolve())
