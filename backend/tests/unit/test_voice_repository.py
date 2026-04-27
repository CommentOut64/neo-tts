import json
import threading

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
    assert voices[0]["weight_storage_mode"] == "external"
    assert voices[0]["gpt_fingerprint"]
    assert voices[0]["sovits_fingerprint"]


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
    assert voices[0]["weight_storage_mode"] == "managed"
    assert voices[0]["gpt_fingerprint"]
    assert voices[0]["sovits_fingerprint"]


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
    assert reference_sidecar["reference_asset_id"] == "reference"
    assert reference_sidecar["ref_audio"] == "managed_voices/managed-demo/reference.wav"
    assert reference_sidecar["ref_audio_fingerprint"]
    assert reference_sidecar["ref_text"] == "backfilled reference text"
    assert reference_sidecar["ref_text_fingerprint"]
    assert reference_sidecar["ref_lang"] == "en"
    assert reference_sidecar["updated_at"] == "2026-04-12T00:00:00Z"


def test_create_uploaded_voice_writes_reference_sidecar(tmp_path):
    settings = AppSettings(
        project_root=tmp_path,
        voices_config_path=tmp_path / "voices.json",
        managed_voices_dir=tmp_path / "managed_voices",
    )
    repository = VoiceRepository(settings=settings)

    created = repository.create_uploaded_voice(
        name="uploaded-demo",
        description="uploaded voice",
        copy_weights_into_project=True,
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

    assert created["gpt_path"] == "managed_voices/uploaded-demo/weights/model.ckpt"
    assert created["sovits_path"] == "managed_voices/uploaded-demo/weights/model.pth"
    assert created["ref_audio"].startswith("managed_voices/uploaded-demo/references/ref-")
    reference_sidecar = json.loads(
        (tmp_path / "managed_voices" / "uploaded-demo" / "reference.json").read_text(
            encoding="utf-8",
        ),
    )
    assert reference_sidecar["reference_asset_id"]
    assert reference_sidecar["ref_audio"] == created["ref_audio"]
    assert reference_sidecar["ref_audio_fingerprint"]
    assert reference_sidecar["ref_text"] == "reference text"
    assert "ref_text_fingerprint" in reference_sidecar
    assert reference_sidecar["ref_lang"] == "zh"
    assert "updated_at" in reference_sidecar


def test_create_uploaded_voice_external_mode_keeps_absolute_weights_and_stores_reference_under_references_dir(tmp_path):
    external_dir = tmp_path / "external-models"
    external_dir.mkdir(parents=True)
    gpt_path = external_dir / "demo.ckpt"
    sovits_path = external_dir / "demo.pth"
    gpt_path.write_bytes(b"fake-gpt")
    sovits_path.write_bytes(b"fake-sovits")
    settings = AppSettings(
        project_root=tmp_path,
        voices_config_path=tmp_path / "voices.json",
        managed_voices_dir=tmp_path / "managed_voices",
    )
    repository = VoiceRepository(settings=settings)

    created = repository.create_uploaded_voice(
        name="external-demo",
        description="external voice",
        copy_weights_into_project=False,
        ref_text="reference text",
        ref_lang="zh",
        defaults=VoiceDefaults(),
        gpt_external_path=str(gpt_path.resolve()),
        sovits_external_path=str(sovits_path.resolve()),
        ref_audio_filename="reference.wav",
        ref_audio_bytes=b"RIFFfake",
    )

    assert created["weight_storage_mode"] == "external"
    assert created["gpt_path"] == gpt_path.resolve().as_posix()
    assert created["sovits_path"] == sovits_path.resolve().as_posix()
    assert created["ref_audio"].startswith("managed_voices/external-demo/references/ref-")
    assert (tmp_path / created["ref_audio"]).exists()


def test_create_uploaded_voice_serializes_same_voice_name_to_avoid_reference_audio_race(tmp_path):
    external_dir = tmp_path / "external-models"
    external_dir.mkdir(parents=True)
    gpt_path = external_dir / "demo.ckpt"
    sovits_path = external_dir / "demo.pth"
    gpt_path.write_bytes(b"fake-gpt")
    sovits_path.write_bytes(b"fake-sovits")
    settings = AppSettings(
        project_root=tmp_path,
        voices_config_path=tmp_path / "voices.json",
        managed_voices_dir=tmp_path / "managed_voices",
    )
    first_repository = VoiceRepository(settings=settings)
    second_repository = VoiceRepository(settings=settings)
    original_write_reference_sidecar = first_repository._write_managed_voice_reference_sidecar
    first_request_blocked = threading.Event()
    allow_first_request_to_continue = threading.Event()
    second_request_finished = threading.Event()
    first_result: dict[str, object] = {}
    second_result: dict[str, object] = {}
    first_error: list[Exception] = []
    second_error: list[Exception] = []

    def blocked_write_reference_sidecar(*, profile, target_dir):
        first_request_blocked.set()
        assert allow_first_request_to_continue.wait(timeout=5), "timed out waiting for second request"
        return original_write_reference_sidecar(profile=profile, target_dir=target_dir)

    first_repository._write_managed_voice_reference_sidecar = blocked_write_reference_sidecar

    def run_first_request() -> None:
        try:
            first_result["value"] = first_repository.create_uploaded_voice(
                name="race-demo",
                description="first request",
                copy_weights_into_project=False,
                ref_text="reference text",
                ref_lang="zh",
                defaults=VoiceDefaults(),
                gpt_external_path=str(gpt_path.resolve()),
                sovits_external_path=str(sovits_path.resolve()),
                ref_audio_filename="reference.wav",
                ref_audio_bytes=b"RIFFfake",
            )
        except Exception as exc:  # pragma: no cover - asserted below
            first_error.append(exc)

    def run_second_request() -> None:
        try:
            second_result["value"] = second_repository.create_uploaded_voice(
                name="race-demo",
                description="second request",
                copy_weights_into_project=False,
                ref_text="reference text",
                ref_lang="zh",
                defaults=VoiceDefaults(),
                gpt_external_path=str(gpt_path.resolve()),
                sovits_external_path=str(sovits_path.resolve()),
                ref_audio_filename="reference.wav",
                ref_audio_bytes=b"RIFFfake",
            )
        except Exception as exc:  # pragma: no cover - asserted below
            second_error.append(exc)
        finally:
            second_request_finished.set()

    first_thread = threading.Thread(target=run_first_request)
    first_thread.start()
    assert first_request_blocked.wait(timeout=5), "first request did not reach reference sidecar write"
    second_thread = threading.Thread(target=run_second_request)
    second_thread.start()
    assert not second_request_finished.wait(timeout=0.2), "second request should wait for first request to finish"

    allow_first_request_to_continue.set()
    first_thread.join(timeout=5)
    second_thread.join(timeout=5)
    assert not first_thread.is_alive(), "first request thread did not finish"
    assert not second_thread.is_alive(), "second request thread did not finish"
    assert not first_error
    created = first_result["value"]
    assert isinstance(created, dict)
    assert created["name"] == "race-demo"
    assert (tmp_path / created["ref_audio"]).exists()
    assert not second_result
    assert len(second_error) == 1
    assert isinstance(second_error[0], ValueError)
    assert str(second_error[0]) == "Voice 'race-demo' already exists."


def test_create_uploaded_voice_cleans_up_partial_directory_when_write_fails(tmp_path, monkeypatch):
    external_dir = tmp_path / "external-models"
    external_dir.mkdir(parents=True)
    gpt_path = external_dir / "demo.ckpt"
    sovits_path = external_dir / "demo.pth"
    gpt_path.write_bytes(b"fake-gpt")
    sovits_path.write_bytes(b"fake-sovits")
    voices_config = tmp_path / "voices.json"
    settings = AppSettings(
        project_root=tmp_path,
        voices_config_path=voices_config,
        managed_voices_dir=tmp_path / "managed_voices",
    )
    repository = VoiceRepository(settings=settings)

    def fail_write_reference_sidecar(*, profile, target_dir):
        raise RuntimeError("reference sidecar write failed")

    monkeypatch.setattr(repository, "_write_managed_voice_reference_sidecar", fail_write_reference_sidecar)

    with pytest.raises(RuntimeError, match="reference sidecar write failed"):
        repository.create_uploaded_voice(
            name="rollback-demo",
            description="rollback voice",
            copy_weights_into_project=False,
            ref_text="reference text",
            ref_lang="zh",
            defaults=VoiceDefaults(),
            gpt_external_path=str(gpt_path.resolve()),
            sovits_external_path=str(sovits_path.resolve()),
            ref_audio_filename="reference.wav",
            ref_audio_bytes=b"RIFFfake",
        )

    assert not (tmp_path / "managed_voices" / "rollback-demo").exists()
    assert not voices_config.exists()


def test_create_uploaded_voice_stores_same_reference_audio_as_distinct_assets(tmp_path):
    external_dir = tmp_path / "external-models"
    external_dir.mkdir(parents=True)
    gpt_path = external_dir / "demo.ckpt"
    sovits_path = external_dir / "demo.pth"
    gpt_path.write_bytes(b"fake-gpt")
    sovits_path.write_bytes(b"fake-sovits")
    settings = AppSettings(
        project_root=tmp_path,
        voices_config_path=tmp_path / "voices.json",
        managed_voices_dir=tmp_path / "managed_voices",
    )
    repository = VoiceRepository(settings=settings)

    first = repository.create_uploaded_voice(
        name="ref-a",
        description="voice a",
        copy_weights_into_project=False,
        ref_text="reference text",
        ref_lang="zh",
        defaults=VoiceDefaults(),
        gpt_external_path=str(gpt_path.resolve()),
        sovits_external_path=str(sovits_path.resolve()),
        ref_audio_filename="reference.wav",
        ref_audio_bytes=b"RIFFsame",
    )
    second = repository.create_uploaded_voice(
        name="ref-b",
        description="voice b",
        copy_weights_into_project=False,
        ref_text="reference text",
        ref_lang="zh",
        defaults=VoiceDefaults(),
        gpt_external_path=str(gpt_path.resolve()),
        sovits_external_path=str(sovits_path.resolve()),
        ref_audio_filename="reference.wav",
        ref_audio_bytes=b"RIFFsame",
    )

    assert first["ref_audio"] != second["ref_audio"]
    assert (tmp_path / first["ref_audio"]).read_bytes() == b"RIFFsame"
    assert (tmp_path / second["ref_audio"]).read_bytes() == b"RIFFsame"


def test_create_uploaded_voice_supports_user_data_relative_managed_paths_in_development(tmp_path):
    storage_root = tmp_path / "storage"
    external_dir = tmp_path / "external-models"
    external_dir.mkdir(parents=True)
    gpt_path = external_dir / "demo.ckpt"
    sovits_path = external_dir / "demo.pth"
    gpt_path.write_bytes(b"fake-gpt")
    sovits_path.write_bytes(b"fake-sovits")
    settings = AppSettings(
        project_root=tmp_path,
        user_data_root=storage_root,
        voices_config_path=tmp_path / "config" / "voices.json",
        managed_voices_dir=storage_root / "managed_voices",
    )
    repository = VoiceRepository(settings=settings)

    created = repository.create_uploaded_voice(
        name="storage-demo",
        description="storage voice",
        copy_weights_into_project=False,
        ref_text="reference text",
        ref_lang="zh",
        defaults=VoiceDefaults(),
        gpt_external_path=str(gpt_path.resolve()),
        sovits_external_path=str(sovits_path.resolve()),
        ref_audio_filename="reference.wav",
        ref_audio_bytes=b"RIFFfake",
    )

    assert created["ref_audio"].startswith("managed_voices/storage-demo/references/ref-")
    assert (storage_root / created["ref_audio"]).exists()
    reference_sidecar = json.loads(
        (storage_root / "managed_voices" / "storage-demo" / "reference.json").read_text(encoding="utf-8")
    )
    assert reference_sidecar["ref_audio"] == created["ref_audio"]
    assert reference_sidecar["ref_audio_fingerprint"]


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
    reference_sidecar = json.loads((managed_dir / "reference.json").read_text(encoding="utf-8"))
    assert reference_sidecar["ref_audio"] == updated["ref_audio"]
    assert reference_sidecar["ref_text"] == "updated reference text"
    assert reference_sidecar["ref_lang"] == "ja"


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

    assert updated["gpt_path"] == "managed_voices/managed-demo/weights/new.ckpt"
    assert updated["sovits_path"] == "managed_voices/managed-demo/weights/new.pth"
    assert updated["ref_audio"].startswith("managed_voices/managed-demo/references/ref-")
    assert not (managed_dir / "old.ckpt").exists()
    assert not (managed_dir / "old.pth").exists()
    assert not (managed_dir / "old.wav").exists()
    assert (managed_dir / "weights" / "new.ckpt").read_bytes() == b"new-gpt"
    assert (managed_dir / "weights" / "new.pth").read_bytes() == b"new-sovits"
    assert (tmp_path / updated["ref_audio"]).read_bytes() == b"new-audio"


def test_update_managed_voice_keeps_old_reference_audio_until_config_write_succeeds(tmp_path, monkeypatch):
    managed_dir = tmp_path / "managed_voices" / "managed-demo"
    managed_dir.mkdir(parents=True)
    (managed_dir / "old.ckpt").write_bytes(b"old-gpt")
    (managed_dir / "old.pth").write_bytes(b"old-sovits")
    old_audio_path = managed_dir / "old.wav"
    old_audio_path.write_bytes(b"old-audio")
    metadata_path = managed_dir / "voice.json"
    metadata_path.write_text(
        json.dumps(
            {
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
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    reference_sidecar_path = managed_dir / "reference.json"
    reference_sidecar_path.write_text(
        json.dumps(
            {
                "reference_asset_id": "old",
                "ref_audio": "managed_voices/managed-demo/old.wav",
                "ref_audio_fingerprint": "",
                "ref_text": "reference text",
                "ref_text_fingerprint": "",
                "ref_lang": "en",
                "updated_at": "2026-04-21T00:00:00Z",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
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
    original_metadata = metadata_path.read_text(encoding="utf-8")
    original_reference_sidecar = reference_sidecar_path.read_text(encoding="utf-8")

    def fail_write(_: dict[str, dict[str, object]]) -> None:
        raise RuntimeError("config write failed")

    monkeypatch.setattr(repository, "_write", fail_write)

    with pytest.raises(RuntimeError, match="config write failed"):
        repository.update_managed_voice(
            voice_name="managed-demo",
            ref_audio_filename="new.wav",
            ref_audio_bytes=b"new-audio",
        )

    assert old_audio_path.exists()
    assert old_audio_path.read_bytes() == b"old-audio"
    references_dir = managed_dir / "references"
    assert list(references_dir.glob("*")) == []
    assert metadata_path.read_text(encoding="utf-8") == original_metadata
    assert reference_sidecar_path.read_text(encoding="utf-8") == original_reference_sidecar


def test_delete_external_voice_keeps_external_weight_files_but_removes_managed_reference_audio(tmp_path):
    external_dir = tmp_path / "external-models"
    external_dir.mkdir(parents=True)
    gpt_path = external_dir / "demo.ckpt"
    sovits_path = external_dir / "demo.pth"
    gpt_path.write_bytes(b"fake-gpt")
    sovits_path.write_bytes(b"fake-sovits")
    settings = AppSettings(
        project_root=tmp_path,
        voices_config_path=tmp_path / "voices.json",
        managed_voices_dir=tmp_path / "managed_voices",
    )
    repository = VoiceRepository(settings=settings)

    created = repository.create_uploaded_voice(
        name="external-demo",
        description="external voice",
        copy_weights_into_project=False,
        ref_text="reference text",
        ref_lang="zh",
        defaults=VoiceDefaults(),
        gpt_external_path=str(gpt_path.resolve()),
        sovits_external_path=str(sovits_path.resolve()),
        ref_audio_filename="reference.wav",
        ref_audio_bytes=b"RIFFfake",
    )

    repository.delete_voice("external-demo")

    assert gpt_path.exists()
    assert sovits_path.exists()
    assert not (tmp_path / created["ref_audio"]).exists()


def test_list_voices_recovers_external_profile_from_voice_metadata_when_weight_files_are_external(tmp_path):
    managed_dir = tmp_path / "managed_voices" / "external-demo"
    references_dir = managed_dir / "references"
    references_dir.mkdir(parents=True)
    (references_dir / "ref-demo.wav").write_bytes(b"RIFFfake")
    (managed_dir / "voice.json").write_text(
        json.dumps(
            {
                "gpt_path": "F:/GPT-SoVITS-v2pro-20250604/demo.ckpt",
                "sovits_path": "F:/GPT-SoVITS-v2pro-20250604/demo.pth",
                "weight_storage_mode": "external",
                "ref_audio": "managed_voices/external-demo/references/ref-demo.wav",
                "ref_text": "reference text",
                "ref_lang": "en",
                "description": "external voice",
                "defaults": {
                    "speed": 1.1,
                    "top_k": 12,
                    "top_p": 0.9,
                    "temperature": 0.8,
                    "pause_length": 0.4,
                },
                "managed": True,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    (managed_dir / "reference.json").write_text(
        json.dumps(
            {
                "reference_asset_id": "ref-demo",
                "ref_audio": "managed_voices/external-demo/references/ref-demo.wav",
                "ref_audio_fingerprint": "",
                "ref_text": "reference text",
                "ref_text_fingerprint": "",
                "ref_lang": "en",
                "updated_at": "2026-04-21T00:00:00Z",
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

    assert [voice["name"] for voice in voices] == ["external-demo"]
    assert voices[0]["weight_storage_mode"] == "external"
    assert voices[0]["gpt_path"] == "F:/GPT-SoVITS-v2pro-20250604/demo.ckpt"
    assert voices[0]["sovits_path"] == "F:/GPT-SoVITS-v2pro-20250604/demo.pth"
    assert voices[0]["ref_audio"] == "managed_voices/external-demo/references/ref-demo.wav"


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


def test_product_mode_normalizes_models_prefixed_paths_against_models_root(tmp_path):
    voices_config = tmp_path / "voices.json"
    voices_config.write_text(
        json.dumps(
            {
                "builtin-demo": {
                    "gpt_path": "models/builtin/demo/demo.ckpt",
                    "sovits_path": "models/builtin/demo/demo.pth",
                    "ref_audio": "config/reference.wav",
                    "ref_text": "reference text",
                    "ref_lang": "zh",
                    "description": "builtin voice",
                    "defaults": {},
                    "managed": False,
                }
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    settings = AppSettings(
        project_root=tmp_path,
        distribution_kind="installed",
        resources_root=tmp_path / "packages" / "app-core" / "v0.0.1",
        app_core_root=tmp_path / "packages" / "app-core" / "v0.0.1",
        runtime_root=tmp_path / "packages" / "runtime" / "py311-cu128-v1",
        models_root=tmp_path / "packages" / "models" / "builtin-v1",
        pretrained_models_root=tmp_path / "packages" / "pretrained-models" / "support-v1",
        user_data_root=tmp_path / "data",
        builtin_voices_config_path=voices_config,
        voices_config_path=tmp_path / "data" / "config" / "voices.json",
        managed_voices_dir=tmp_path / "data" / "managed_voices",
    )
    repository = VoiceRepository(settings=settings)

    voice = repository.get_voice("builtin-demo")

    assert voice["gpt_path"] == str((settings.models_root / "models" / "builtin" / "demo" / "demo.ckpt").resolve())
    assert voice["sovits_path"] == str((settings.models_root / "models" / "builtin" / "demo" / "demo.pth").resolve())
    assert voice["ref_audio"] == str((settings.app_core_root / "config" / "reference.wav").resolve())


def test_product_mode_normalizes_pretrained_models_prefixed_paths_against_pretrained_models_root(tmp_path):
    voices_config = tmp_path / "voices.json"
    voices_config.write_text(
        json.dumps(
            {
                "support-demo": {
                    "gpt_path": "pretrained_models/GPT_weights/demo.ckpt",
                    "sovits_path": "pretrained_models/SoVITS_weights/demo.pth",
                    "ref_audio": "pretrained_models/reference.wav",
                    "ref_text": "reference text",
                    "ref_lang": "zh",
                    "description": "support voice",
                    "defaults": {},
                    "managed": False,
                }
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    settings = AppSettings(
        project_root=tmp_path,
        distribution_kind="portable",
        resources_root=tmp_path / "packages" / "app-core" / "v0.0.1",
        app_core_root=tmp_path / "packages" / "app-core" / "v0.0.1",
        runtime_root=tmp_path / "packages" / "runtime" / "py311-cu128-v1",
        models_root=tmp_path / "packages" / "models" / "builtin-v1",
        pretrained_models_root=tmp_path / "packages" / "pretrained-models" / "support-v1",
        user_data_root=tmp_path / "data",
        builtin_voices_config_path=voices_config,
        voices_config_path=tmp_path / "data" / "config" / "voices.json",
        managed_voices_dir=tmp_path / "data" / "managed_voices",
    )
    repository = VoiceRepository(settings=settings)

    voice = repository.get_voice("support-demo")

    assert voice["gpt_path"] == str((settings.pretrained_models_root / "pretrained_models" / "GPT_weights" / "demo.ckpt").resolve())
    assert voice["sovits_path"] == str((settings.pretrained_models_root / "pretrained_models" / "SoVITS_weights" / "demo.pth").resolve())
    assert voice["ref_audio"] == str((settings.pretrained_models_root / "pretrained_models" / "reference.wav").resolve())


def test_product_mode_keeps_managed_voice_paths_under_user_data_root(tmp_path):
    managed_dir = tmp_path / "data" / "managed_voices" / "managed-demo"
    managed_dir.mkdir(parents=True)
    (managed_dir / "weights").mkdir(parents=True)
    (managed_dir / "references").mkdir(parents=True)
    (managed_dir / "weights" / "demo.ckpt").write_bytes(b"fake-gpt")
    (managed_dir / "weights" / "demo.pth").write_bytes(b"fake-sovits")
    (managed_dir / "references" / "ref-demo.wav").write_bytes(b"RIFFfake")
    voices_config = tmp_path / "user-voices.json"
    voices_config.write_text(
        json.dumps(
            {
                "managed-demo": {
                    "gpt_path": "managed_voices/managed-demo/weights/demo.ckpt",
                    "sovits_path": "managed_voices/managed-demo/weights/demo.pth",
                    "ref_audio": "managed_voices/managed-demo/references/ref-demo.wav",
                    "ref_text": "reference text",
                    "ref_lang": "zh",
                    "description": "managed voice",
                    "defaults": {},
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
        distribution_kind="installed",
        resources_root=tmp_path / "packages" / "app-core" / "v0.0.1",
        app_core_root=tmp_path / "packages" / "app-core" / "v0.0.1",
        runtime_root=tmp_path / "packages" / "runtime" / "py311-cu128-v1",
        models_root=tmp_path / "packages" / "models" / "builtin-v1",
        pretrained_models_root=tmp_path / "packages" / "pretrained-models" / "support-v1",
        user_data_root=tmp_path / "data",
        builtin_voices_config_path=tmp_path / "builtin-voices.json",
        voices_config_path=voices_config,
        managed_voices_dir=tmp_path / "data" / "managed_voices",
    )
    repository = VoiceRepository(settings=settings)

    voice = repository.get_voice("managed-demo")

    assert voice["gpt_path"] == str((settings.user_data_root / "managed_voices" / "managed-demo" / "weights" / "demo.ckpt").resolve())
    assert voice["sovits_path"] == str((settings.user_data_root / "managed_voices" / "managed-demo" / "weights" / "demo.pth").resolve())
    assert voice["ref_audio"] == str((settings.user_data_root / "managed_voices" / "managed-demo" / "references" / "ref-demo.wav").resolve())
