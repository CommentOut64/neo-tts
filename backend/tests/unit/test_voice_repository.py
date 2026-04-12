import json

from backend.app.core.settings import AppSettings
from backend.app.repositories.voice_repository import VoiceRepository


def test_load_voice_profiles_from_json(sample_voice_config):
    settings = AppSettings(
        project_root=sample_voice_config.parent,
        voices_config_path=sample_voice_config,
        managed_voices_dir=sample_voice_config.parent / "managed_voices",
    )
    repository = VoiceRepository(config_path=sample_voice_config, settings=settings)

    voices = repository.list_voices()

    assert len(voices) == 1
    assert voices[0]["name"] == "demo"
    assert voices[0]["gpt_path"].endswith("pretrained_models/demo.ckpt")


def test_list_voices_recovers_managed_profiles_when_config_missing(tmp_path):
    managed_dir = tmp_path / "managed_voices" / "recovered-demo"
    managed_dir.mkdir(parents=True)
    (managed_dir / "model.ckpt").write_bytes(b"fake-gpt")
    (managed_dir / "model.pth").write_bytes(b"fake-sovits")
    (managed_dir / "reference.wav").write_bytes(b"RIFFfake")
    (managed_dir / "voice.json").write_text(
        json.dumps(
            {
                "description": "recovered voice",
                "ref_text": "reference text",
                "ref_lang": "en",
                "defaults": {
                    "speed": 1.1,
                    "top_k": 12,
                    "top_p": 0.9,
                    "temperature": 0.8,
                    "pause_length": 0.4,
                },
                "created_at": "2026-04-12T00:00:00Z",
                "updated_at": "2026-04-12T00:00:00Z",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    settings = AppSettings(
        project_root=tmp_path,
        voices_config_path=tmp_path / "voices.json",
        managed_voices_dir=tmp_path / "managed_voices",
    )
    repository = VoiceRepository(settings=settings)

    voices = repository.list_voices()

    assert [voice["name"] for voice in voices] == ["recovered-demo"]
    assert voices[0]["managed"] is True
    assert voices[0]["ref_text"] == "reference text"
    assert voices[0]["gpt_path"] == "managed_voices/recovered-demo/model.ckpt"
