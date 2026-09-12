import io
import os
import wave
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from backend.app.main import create_app


@pytest.mark.skipif(
    os.getenv("GPT_SOVITS_E2E") != "1",
    reason="未启用真实模型 E2E，请设置 GPT_SOVITS_E2E=1。",
)
@pytest.mark.parametrize("device", ["cpu", "cuda"])
def test_real_model_tts_uses_gsv_runtime_on_selected_device(real_model_env, real_model_app_settings, device, monkeypatch):
    """Exercise ordinary HTTP TTS through the selected native Runtime device."""
    import torch

    from backend.app.inference.gsv_runtime_adapter import GSVRuntimeEngineAdapter
    from runtime.gsv.loader import NativeBackend
    if device == "cuda" and not torch.cuda.is_available():
        pytest.skip("CUDA is unavailable")
    app = create_app(settings=replace(real_model_app_settings, inference_device=device))
    with TestClient(app) as client:
        response = client.post(
            "/v1/audio/speech",
            json={"input": "你好。", "voice": real_model_env.voice_id},
        )
        handles = list(app.state.model_cache._engines.values())
        assert handles
        for handle in handles:
            assert isinstance(handle.engine, GSVRuntimeEngineAdapter)
            backend = handle.engine._lease.backend
            assert isinstance(backend, NativeBackend)
            assert handle.resident_device == device
            assert backend.device == device
            assert next(backend.t2s_model.parameters()).device.type == device
            assert next(backend.vq_model.parameters()).device.type == device
            converter = backend._delegate._g2pw
            assert converter is not None
            providers = converter._g2pw.session_g2pW.get_providers()
            expected = ["CUDAExecutionProvider", "CPUExecutionProvider"] if device == "cuda" else ["CPUExecutionProvider"]
            assert providers == expected
            del converter
            if device == "cuda":
                handle.engine.offload_from_gpu()
                assert next(backend.t2s_model.parameters()).device.type == "cpu"
                assert backend._delegate._g2pw is None
                handle.engine.ensure_on_gpu()
                assert next(backend.t2s_model.parameters()).device.type == "cuda"

        from GPT_SoVITS.text import cleaner

        clean_text = cleaner.clean_text
        languages = []

        def record_frontend(text, language, version, **kwargs):
            result = clean_text(text, language, version, **kwargs)
            if result[0]:
                languages.append((language, text))
            return result

        monkeypatch.setattr(cleaner, "clean_text", record_frontend)
        mixed_response = client.post(
            "/v1/audio/speech",
            json={"input": "Hello こんにちは。", "text_lang": "en", "voice": real_model_env.voice_id},
        )
        assert mixed_response.status_code == 200, mixed_response.text
        assert any(language == "en" and "Hello" in text for language, text in languages)
        assert any(language == "ja" and "こんにちは" in text for language, text in languages)
        with wave.open(io.BytesIO(mixed_response.content), "rb") as wav_file:
            assert wav_file.getframerate() == 32000
            assert wav_file.getnframes() > 0

    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("audio/wav")
    assert response.content[:4] == b"RIFF"
    with wave.open(io.BytesIO(response.content), "rb") as wav_file:
        assert wav_file.getframerate() == 32000
        assert wav_file.getnframes() > 0
