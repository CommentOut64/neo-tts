import json

import pytest

from backend.app.core.settings import AppSettings
from backend.app.repositories.voice_repository import VoiceRepository
from backend.app.schemas.voice import VoiceDefaults


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


def test_list_voices_recovers_reference_text_from_reference_sidecar_when_voice_metadata_missing(tmp_path):
    managed_dir = tmp_path / "managed_voices" / "recovered-demo"
    managed_dir.mkdir(parents=True)
    (managed_dir / "model.ckpt").write_bytes(b"fake-gpt")
    (managed_dir / "model.pth").write_bytes(b"fake-sovits")
    (managed_dir / "reference.wav").write_bytes(b"RIFFfake")
    (managed_dir / "reference.json").write_text(
        json.dumps(
            {
                "ref_text": "reference text from sidecar",
                "ref_lang": "ja",
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
    assert voices[0]["ref_text"] == "reference text from sidecar"
    assert voices[0]["ref_lang"] == "ja"


def test_list_voices_backfills_reference_sidecar_for_existing_managed_profile_from_config(tmp_path):
    managed_dir = tmp_path / "managed_voices" / "managed-demo"
    managed_dir.mkdir(parents=True)
    (managed_dir / "model.ckpt").write_bytes(b"fake-gpt")
    (managed_dir / "model.pth").write_bytes(b"fake-sovits")
    (managed_dir / "reference.wav").write_bytes(b"RIFFfake")
    voices_config = tmp_path / "voices.json"
    voices_config.write_text(
        json.dumps(
            {
                "managed-demo": {
                    "gpt_path": "managed_voices/managed-demo/model.ckpt",
                    "sovits_path": "managed_voices/managed-demo/model.pth",
                    "ref_audio": "managed_voices/managed-demo/reference.wav",
                    "ref_text": "backfilled reference text",
                    "ref_lang": "en",
                    "description": "managed voice",
                    "defaults": {
                        "speed": 1.1,
                        "top_k": 12,
                        "top_p": 0.9,
                        "temperature": 0.8,
                        "pause_length": 0.4,
                    },
                    "managed": True,
                    "created_at": "2026-04-12T00:00:00Z",
                    "updated_at": "2026-04-12T00:00:00Z",
                }
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    settings = AppSettings(
        project_root=tmp_path,
        voices_config_path=voices_config,
        managed_voices_dir=tmp_path / "managed_voices",
    )
    repository = VoiceRepository(settings=settings)

    voices = repository.list_voices()

    assert [voice["name"] for voice in voices] == ["managed-demo"]
    reference_sidecar = json.loads((managed_dir / "reference.json").read_text(encoding="utf-8"))
    assert reference_sidecar == {
        "ref_text": "backfilled reference text",
        "ref_lang": "en",
    }


def test_create_uploaded_voice_writes_reference_sidecar(tmp_path):
    settings = AppSettings(
        project_root=tmp_path,
        voices_config_path=tmp_path / "voices.json",
        managed_voices_dir=tmp_path / "managed_voices",
    )
    repository = VoiceRepository(settings=settings)

    repository.create_uploaded_voice(
        name="uploaded-demo",
        description="uploaded voice",
        ref_text="reference text",
        ref_lang="zh",
        defaults=VoiceDefaults(),
        gpt_filename="model.ckpt",
        gpt_bytes=b"fake-gpt",
        sovits_filename="model.pth",
        sovits_bytes=b"fake-sovits",
        ref_audio_filename="reference.wav",
        ref_audio_bytes=b"RIFFfake",
    )

    reference_sidecar = json.loads(
        (tmp_path / "managed_voices" / "uploaded-demo" / "reference.json").read_text(
            encoding="utf-8",
        ),
    )
    assert reference_sidecar == {
        "ref_text": "reference text",
        "ref_lang": "zh",
    }


def test_update_managed_voice_updates_metadata_and_reference_sidecar(tmp_path):
    managed_dir = tmp_path / "managed_voices" / "managed-demo"
    managed_dir.mkdir(parents=True)
    (managed_dir / "model.ckpt").write_bytes(b"fake-gpt")
    (managed_dir / "model.pth").write_bytes(b"fake-sovits")
    (managed_dir / "reference.wav").write_bytes(b"RIFFfake")
    voices_config = tmp_path / "voices.json"
    voices_config.write_text(
        json.dumps(
            {
                "managed-demo": {
                    "gpt_path": "managed_voices/managed-demo/model.ckpt",
                    "sovits_path": "managed_voices/managed-demo/model.pth",
                    "ref_audio": "managed_voices/managed-demo/reference.wav",
                    "ref_text": "reference text",
                    "ref_lang": "en",
                    "description": "managed voice",
                    "defaults": {
                        "speed": 1.1,
                        "top_k": 12,
                        "top_p": 0.9,
                        "temperature": 0.8,
                        "pause_length": 0.4,
                    },
                    "managed": True,
                    "created_at": "2026-04-12T00:00:00Z",
                    "updated_at": "2026-04-12T00:00:00Z",
                }
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    settings = AppSettings(
        project_root=tmp_path,
        voices_config_path=voices_config,
        managed_voices_dir=tmp_path / "managed_voices",
    )
    repository = VoiceRepository(settings=settings)

    updated = repository.update_managed_voice(
        voice_name="managed-demo",
        description="updated voice",
        ref_text="updated reference text",
        ref_lang="ja",
    )

    assert updated["description"] == "updated voice"
    assert updated["ref_text"] == "updated reference text"
    assert updated["ref_lang"] == "ja"
    assert json.loads((managed_dir / "reference.json").read_text(encoding="utf-8")) == {
        "ref_text": "updated reference text",
        "ref_lang": "ja",
    }


def test_update_managed_voice_replaces_existing_files(tmp_path):
    managed_dir = tmp_path / "managed_voices" / "managed-demo"
    managed_dir.mkdir(parents=True)
    (managed_dir / "old.ckpt").write_bytes(b"old-gpt")
    (managed_dir / "old.pth").write_bytes(b"old-sovits")
    (managed_dir / "old.wav").write_bytes(b"old-audio")
    voices_config = tmp_path / "voices.json"
    voices_config.write_text(
        json.dumps(
            {
                "managed-demo": {
                    "gpt_path": "managed_voices/managed-demo/old.ckpt",
                    "sovits_path": "managed_voices/managed-demo/old.pth",
                    "ref_audio": "managed_voices/managed-demo/old.wav",
                    "ref_text": "reference text",
                    "ref_lang": "en",
                    "description": "managed voice",
                    "defaults": {
                        "speed": 1.1,
                        "top_k": 12,
                        "top_p": 0.9,
                        "temperature": 0.8,
                        "pause_length": 0.4,
                    },
                    "managed": True,
                }
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    settings = AppSettings(
        project_root=tmp_path,
        voices_config_path=voices_config,
        managed_voices_dir=tmp_path / "managed_voices",
    )
    repository = VoiceRepository(settings=settings)

    updated = repository.update_managed_voice(
        voice_name="managed-demo",
        gpt_filename="new.ckpt",
        gpt_bytes=b"new-gpt",
        sovits_filename="new.pth",
        sovits_bytes=b"new-sovits",
        ref_audio_filename="new.wav",
        ref_audio_bytes=b"new-audio",
    )

    assert updated["gpt_path"] == "managed_voices/managed-demo/new.ckpt"
    assert updated["sovits_path"] == "managed_voices/managed-demo/new.pth"
    assert updated["ref_audio"] == "managed_voices/managed-demo/new.wav"
    assert not (managed_dir / "old.ckpt").exists()
    assert not (managed_dir / "old.pth").exists()
    assert not (managed_dir / "old.wav").exists()
    assert (managed_dir / "new.ckpt").read_bytes() == b"new-gpt"
    assert (managed_dir / "new.pth").read_bytes() == b"new-sovits"
    assert (managed_dir / "new.wav").read_bytes() == b"new-audio"


def test_update_managed_voice_rejects_static_voice(sample_voice_config):
    settings = AppSettings(
        project_root=sample_voice_config.parent,
        voices_config_path=sample_voice_config,
        managed_voices_dir=sample_voice_config.parent / "managed_voices",
    )
    repository = VoiceRepository(config_path=sample_voice_config, settings=settings)

    with pytest.raises(ValueError, match="Voice 'demo' is not managed and cannot be edited."):
        repository.update_managed_voice(
            voice_name="demo",
            description="updated voice",
            ref_text="updated reference text",
            ref_lang="ja",
        )
