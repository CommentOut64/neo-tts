from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import numpy as np
import torch

from backend.app.inference.qwen3_tts_runtime import Qwen3TTSSegmentRequest, Qwen3TTSRuntime


class _FakeModel:
    from_pretrained_calls: list[dict[str, object]] = []

    def __init__(self) -> None:
        self.custom_voice_calls: list[dict[str, object]] = []
        self.voice_clone_calls: list[dict[str, object]] = []
        self.voice_design_calls: list[dict[str, object]] = []

    @classmethod
    def from_pretrained(
        cls,
        pretrained_model_name_or_path: str,
        *,
        device_map,
        dtype,
        attn_implementation,
    ):
        cls.from_pretrained_calls.append(
            {
                "model_dir": pretrained_model_name_or_path,
                "device_map": device_map,
                "dtype": dtype,
                "attn_implementation": attn_implementation,
            }
        )
        return cls()

    def generate_custom_voice(self, **kwargs):
        self.custom_voice_calls.append(kwargs)
        return [np.asarray([0.1, 0.2], dtype=np.float32)], 24000

    def generate_voice_clone(self, **kwargs):
        self.voice_clone_calls.append(kwargs)
        return [np.asarray([0.3, 0.4, 0.5], dtype=np.float32)], 24000

    def generate_voice_design(self, **kwargs):
        self.voice_design_calls.append(kwargs)
        return [np.asarray([0.6], dtype=np.float32)], 24000


def _request(**overrides) -> Qwen3TTSSegmentRequest:
    payload = {
        "segment_id": "seg-1",
        "text": "测试文本",
        "model_dir": "F:/models/qwen3",
        "generation_mode": "custom_voice",
        "language": "Chinese",
        "speaker": "Vivian",
        "instruct": "平静地说",
        "reference_audio_path": None,
        "reference_text": None,
        "top_k": 32,
        "top_p": 0.9,
        "temperature": 0.7,
        "extra_generate_kwargs": {"max_new_tokens": 512},
    }
    payload.update(overrides)
    return Qwen3TTSSegmentRequest(**payload)


def test_qwen3_tts_runtime_caches_loaded_model_handles(monkeypatch, tmp_path: Path):
    fake_module = SimpleNamespace(Qwen3TTSModel=_FakeModel)
    monkeypatch.setattr("backend.app.inference.qwen3_tts_runtime.importlib.import_module", lambda name: fake_module)
    runtime = Qwen3TTSRuntime(
        qwen3_tts_root=tmp_path,
        default_device="cuda:1",
        default_dtype="float16",
        default_attn_implementation="flash_attention_2",
    )

    first = runtime.render_segment(_request(model_dir=str(tmp_path / "model-a")))
    second = runtime.render_segment(_request(model_dir=str(tmp_path / "model-a"), instruct="第二次调用"))

    assert _FakeModel.from_pretrained_calls == [
        {
            "model_dir": str((tmp_path / "model-a").resolve()),
            "device_map": "cuda:1",
            "dtype": torch.float16,
            "attn_implementation": "flash_attention_2",
        }
    ]
    assert first.sample_rate == 24000
    assert second.sample_rate == 24000


def test_qwen3_tts_runtime_routes_voice_clone_requests_with_reference_inputs(monkeypatch, tmp_path: Path):
    fake_module = SimpleNamespace(Qwen3TTSModel=_FakeModel)
    monkeypatch.setattr("backend.app.inference.qwen3_tts_runtime.importlib.import_module", lambda name: fake_module)
    runtime = Qwen3TTSRuntime(qwen3_tts_root=tmp_path)
    reference_audio_path = str((tmp_path / "refs" / "demo.wav").resolve())

    result = runtime.render_segment(
        _request(
            generation_mode="voice_clone",
            speaker=None,
            instruct=None,
            reference_audio_path=reference_audio_path,
            reference_text="This is a reference clip.",
        )
    )

    last_model = runtime._model_handles[next(iter(runtime._model_handles))].model  # noqa: SLF001
    assert last_model.voice_clone_calls == [
        {
            "text": "测试文本",
            "language": "Chinese",
            "ref_audio": reference_audio_path,
            "ref_text": "This is a reference clip.",
            "top_k": 32,
            "top_p": 0.9,
            "temperature": 0.7,
            "max_new_tokens": 512,
        }
    ]
    assert np.allclose(result.audio, [0.3, 0.4, 0.5])
