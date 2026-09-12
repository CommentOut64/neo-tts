import io
import os
import wave
from dataclasses import replace

import pytest
import torch
from fastapi.testclient import TestClient

from backend.app.core.path_resolution import resolve_runtime_path
from backend.app.main import create_app
from backend.app.repositories.voice_repository import VoiceRepository
from backend.app.services.voice_service import VoiceService
from backend.tests.e2e.test_edit_session_real_models import (
    _assert_frontend_consumable_state,
    _segment_text_patch,
    _wait_for_snapshot_version,
    _wait_for_terminal_job,
)
from runtime.gsv.loader import NativeBackend


@pytest.mark.skipif(os.getenv("GPT_SOVITS_E2E") != "1", reason="Real model acceptance is opt-in")
@pytest.mark.parametrize("voice_id,expected_version", [("一色1", "v1"), ("诗歌剧", "v2ProPlus")])
@pytest.mark.parametrize("device", ["cpu", "cuda"])
def test_imported_voice_tts_and_editing_with_managed_reference(real_model_app_settings, voice_id, expected_version, device):
    if device == "cuda" and not torch.cuda.is_available():
        pytest.skip("CUDA is unavailable")
    settings = replace(real_model_app_settings, inference_device=device)
    service = VoiceService(VoiceRepository(settings=settings))
    try:
        voice = service.get_voice(voice_id)
    except LookupError:
        pytest.skip(f"Imported acceptance voice is unavailable: {voice_id}")
    for path in (voice.gpt_path, voice.sovits_path, voice.ref_audio):
        if not resolve_runtime_path(
            path, project_root=settings.project_root, user_data_root=settings.user_data_root,
            resources_root=settings.resources_root, managed_voices_dir=settings.managed_voices_dir,
        ).is_file():
            pytest.skip(f"Imported acceptance asset is unavailable: {path}")

    expected_segments = ["今日はいい天気ですね。", "少し散歩しましょう。"]
    app = create_app(settings=settings)
    with TestClient(app) as client:
        ordinary = client.post("/v1/audio/speech", json={
            "input": expected_segments[0], "voice": voice_id, "text_lang": "ja",
        })
        assert ordinary.status_code == 200, ordinary.text
        with wave.open(io.BytesIO(ordinary.content), "rb") as audio:
            assert audio.getframerate() == 32000
            assert audio.getnframes() > 0

        initialize = client.post("/v1/edit-session/initialize", json={
            "raw_text": "".join(expected_segments), "text_language": "ja", "voice_id": voice_id,
            "segment_boundary_mode": "raw_strong_punctuation",
        })
        assert initialize.status_code == 202, initialize.text
        _wait_for_terminal_job(client, initialize.json()["job"]["job_id"])
        snapshot = _wait_for_snapshot_version(client, 1)
        assert len(snapshot["segments"]) == 2 and len(snapshot["edges"]) == 1
        backends = [handle.engine._lease.backend for handle in app.state.model_cache._engines.values()]
        assert backends
        for backend in backends:
            assert isinstance(backend, NativeBackend)
            assert next(backend.vq_model.parameters()).device.type == device
            assert backend.hps.model.version == expected_version
            assert backend.vq_model.enc_p.text_embedding.num_embeddings == (322 if expected_version == "v1" else 732)

        expected_segments[0] = "今日はとてもいい天気ですね。"
        update = client.patch(f"/v1/edit-session/segments/{snapshot['segments'][0]['segment_id']}", json={
            "text_patch": _segment_text_patch(expected_segments[0]), "text_language": "ja",
        })
        assert update.status_code == 202, update.text
        _wait_for_terminal_job(client, update.json()["job"]["job_id"])
        _wait_for_snapshot_version(client, 2)
        _assert_frontend_consumable_state(client, expected_segments, export_root=settings.edit_session_exports_dir)
    assert all(backend._delegate is None for backend in backends)
