import io
from pathlib import Path
import wave

import numpy as np
from fastapi.testclient import TestClient

from backend.app.core.settings import AppSettings
from backend.app.main import create_app


class FakeInferenceEngine:
    def __init__(self) -> None:
        self.last_request = None

    def synthesize_stream(self, request):
        self.last_request = request
        return 32000, iter([np.array([0.1, -0.1, 0.0], dtype=np.float32)])


class MissingAssetsInferenceEngine(FakeInferenceEngine):
    def synthesize_stream(self, request):
        raise FileNotFoundError("missing-model.ckpt")


def test_audio_speech_merges_voice_defaults_and_streams_wav(sample_voice_config):
    settings = AppSettings(
        project_root=sample_voice_config.parent,
        voices_config_path=sample_voice_config,
    )
    app = create_app(settings=settings)
    app.state.inference_engine = FakeInferenceEngine()
    client = TestClient(app)

    response = client.post(
        "/v1/audio/speech",
        json={
            "input": "hello world",
            "voice": "demo",
        },
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("audio/wav")
    assert response.content[:4] == b"RIFF"
    with wave.open(io.BytesIO(response.content), "rb") as wav_file:
        assert wav_file.getframerate() == 32000
        assert wav_file.getnframes() == 3
    assert app.state.inference_engine.last_request is not None
    assert app.state.inference_engine.last_request.speed == 1.0
    assert app.state.inference_engine.last_request.top_k == 15
    assert app.state.inference_engine.last_request.ref_audio.endswith("demo.wav")


def test_audio_speech_returns_404_when_voice_not_found(sample_voice_config):
    settings = AppSettings(
        project_root=sample_voice_config.parent,
        voices_config_path=sample_voice_config,
    )
    app = create_app(settings=settings)
    app.state.inference_engine = FakeInferenceEngine()
    client = TestClient(app)

    response = client.post(
        "/v1/audio/speech",
        json={
            "input": "hello world",
            "voice": "missing-voice",
        },
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Voice 'missing-voice' not found."}


def test_audio_speech_rejects_unsupported_response_format(sample_voice_config):
    settings = AppSettings(
        project_root=sample_voice_config.parent,
        voices_config_path=sample_voice_config,
    )
    app = create_app(settings=settings)
    app.state.inference_engine = FakeInferenceEngine()
    client = TestClient(app)

    response = client.post(
        "/v1/audio/speech",
        json={
            "input": "hello world",
            "voice": "demo",
            "response_format": "ogg",
        },
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "Unsupported response_format 'ogg'."}


def test_audio_speech_returns_422_when_inference_assets_missing(sample_voice_config):
    settings = AppSettings(
        project_root=sample_voice_config.parent,
        voices_config_path=sample_voice_config,
    )
    app = create_app(settings=settings)
    app.state.inference_engine = MissingAssetsInferenceEngine()
    client = TestClient(app)

    response = client.post(
        "/v1/audio/speech",
        json={
            "input": "hello world",
            "voice": "demo",
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"].startswith("Inference assets not found:")


def test_audio_speech_accepts_multipart_custom_reference_audio(sample_voice_config):
    settings = AppSettings(
        project_root=sample_voice_config.parent,
        voices_config_path=sample_voice_config,
        managed_voices_dir=sample_voice_config.parent / "managed_voices",
    )
    app = create_app(settings=settings)
    app.state.inference_engine = FakeInferenceEngine()
    client = TestClient(app)

    response = client.post(
        "/v1/audio/speech",
        data={
            "input": "hello world",
            "voice": "demo",
            "ref_text": "custom reference text",
            "ref_lang": "zh",
            "speed": "0.85",
            "top_k": "9",
        },
        files={
            "ref_audio_file": ("custom.wav", b"RIFFcustom", "audio/wav"),
        },
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("audio/wav")
    assert app.state.inference_engine.last_request is not None
    assert app.state.inference_engine.last_request.ref_text == "custom reference text"
    assert app.state.inference_engine.last_request.ref_lang == "zh"
    assert app.state.inference_engine.last_request.speed == 0.85
    assert app.state.inference_engine.last_request.top_k == 9
    assert app.state.inference_engine.last_request.ref_audio.endswith("custom.wav")
    assert not Path(app.state.inference_engine.last_request.ref_audio).exists()
