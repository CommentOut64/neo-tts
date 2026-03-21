from backend.app.repositories.voice_repository import VoiceRepository


def test_load_voice_profiles_from_json(sample_voice_config):
    repository = VoiceRepository(config_path=sample_voice_config)

    voices = repository.list_voices()

    assert len(voices) == 1
    assert voices[0]["name"] == "demo"
    assert voices[0]["gpt_path"].endswith("pretrained_models/demo.ckpt")
