from fastapi.testclient import TestClient

from backend.app.core.settings import AppSettings
from backend.app.main import create_app


def test_list_voices_returns_configured_profiles(sample_voice_config):
    settings = AppSettings(
        project_root=sample_voice_config.parent,
        voices_config_path=sample_voice_config,
    )
    client = TestClient(create_app(settings=settings))

    response = client.get("/v1/voices")

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["name"] == "demo"


def test_reload_voices_returns_reloaded_count(sample_voice_config):
    settings = AppSettings(
        project_root=sample_voice_config.parent,
        voices_config_path=sample_voice_config,
    )
    client = TestClient(create_app(settings=settings))

    response = client.post("/v1/voices/reload")

    assert response.status_code == 200
    assert response.json() == {"status": "success", "count": 1}


def test_reload_voices_recovers_managed_voice_when_config_missing(tmp_path):
    managed_voice_dir = tmp_path / "managed_voices" / "recovered-demo"
    managed_voice_dir.mkdir(parents=True)
    (managed_voice_dir / "model.ckpt").write_bytes(b"fake-gpt")
    (managed_voice_dir / "model.pth").write_bytes(b"fake-sovits")
    (managed_voice_dir / "reference.wav").write_bytes(b"RIFFfake")
    (managed_voice_dir / "voice.json").write_text(
        """
{
  "description": "recovered voice",
  "ref_text": "reference text",
  "ref_lang": "en",
  "defaults": {
    "speed": 1.0,
    "top_k": 15,
    "top_p": 1.0,
    "temperature": 1.0,
    "pause_length": 0.3
  }
}
""".strip(),
        encoding="utf-8",
    )
    settings = AppSettings(
        project_root=tmp_path,
        voices_config_path=tmp_path / "voices.json",
        managed_voices_dir=tmp_path / "managed_voices",
    )
    client = TestClient(create_app(settings=settings))

    reload_response = client.post("/v1/voices/reload")

    assert reload_response.status_code == 200
    assert reload_response.json() == {"status": "success", "count": 1}
    list_response = client.get("/v1/voices")
    assert list_response.status_code == 200
    assert [voice["name"] for voice in list_response.json()] == ["recovered-demo"]


def test_get_voice_detail_returns_profile(sample_voice_config):
    settings = AppSettings(
        project_root=sample_voice_config.parent,
        voices_config_path=sample_voice_config,
    )
    client = TestClient(create_app(settings=settings))

    response = client.get("/v1/voices/demo")

    assert response.status_code == 200
    assert response.json()["name"] == "demo"
    assert response.json()["managed"] is False


def test_upload_voice_persists_files_and_updates_config(empty_voice_config):
    managed_dir = empty_voice_config.parent / "managed_voices"
    settings = AppSettings(
        project_root=empty_voice_config.parent,
        voices_config_path=empty_voice_config,
        managed_voices_dir=managed_dir,
    )
    client = TestClient(create_app(settings=settings))

    response = client.post(
        "/v1/voices/upload",
        data={
            "name": "uploaded-demo",
            "description": "uploaded voice",
            "ref_text": "reference text",
            "ref_lang": "en",
            "speed": "1.1",
            "top_k": "12",
            "top_p": "0.9",
            "temperature": "0.8",
            "pause_length": "0.4",
        },
        files={
            "gpt_file": ("demo.ckpt", b"fake-gpt", "application/octet-stream"),
            "sovits_file": ("demo.pth", b"fake-sovits", "application/octet-stream"),
            "ref_audio_file": ("demo.wav", b"RIFFfake", "audio/wav"),
        },
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["name"] == "uploaded-demo"
    assert payload["managed"] is True
    assert payload["defaults"]["speed"] == 1.1
    assert (empty_voice_config.parent / payload["gpt_path"]).exists()
    assert (empty_voice_config.parent / payload["sovits_path"]).exists()
    assert (empty_voice_config.parent / payload["ref_audio"]).exists()

    reloaded = client.get("/v1/voices")
    assert reloaded.status_code == 200
    assert [voice["name"] for voice in reloaded.json()] == ["uploaded-demo"]


def test_upload_voice_overwrites_orphaned_managed_directory(empty_voice_config):
    managed_dir = empty_voice_config.parent / "managed_voices"
    orphan_dir = managed_dir / "uploaded-demo"
    orphan_dir.mkdir(parents=True)
    (orphan_dir / "stale.ckpt").write_bytes(b"stale-gpt")
    (orphan_dir / "stale.pth").write_bytes(b"stale-sovits")
    (orphan_dir / "stale.wav").write_bytes(b"stale-audio")
    settings = AppSettings(
        project_root=empty_voice_config.parent,
        voices_config_path=empty_voice_config,
        managed_voices_dir=managed_dir,
    )
    client = TestClient(create_app(settings=settings))

    response = client.post(
        "/v1/voices/upload",
        data={
            "name": "uploaded-demo",
            "description": "uploaded voice",
            "ref_text": "reference text",
            "ref_lang": "en",
        },
        files={
            "gpt_file": ("demo.ckpt", b"fresh-gpt", "application/octet-stream"),
            "sovits_file": ("demo.pth", b"fresh-sovits", "application/octet-stream"),
            "ref_audio_file": ("demo.wav", b"RIFFfresh", "audio/wav"),
        },
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["name"] == "uploaded-demo"
    assert not (orphan_dir / "stale.ckpt").exists()
    assert not (orphan_dir / "stale.pth").exists()
    assert not (orphan_dir / "stale.wav").exists()
    assert (empty_voice_config.parent / payload["gpt_path"]).read_bytes() == b"fresh-gpt"


def test_delete_voice_removes_uploaded_voice(empty_voice_config):
    managed_dir = empty_voice_config.parent / "managed_voices"
    settings = AppSettings(
        project_root=empty_voice_config.parent,
        voices_config_path=empty_voice_config,
        managed_voices_dir=managed_dir,
    )
    client = TestClient(create_app(settings=settings))

    upload_response = client.post(
        "/v1/voices/upload",
        data={
            "name": "uploaded-demo",
            "description": "uploaded voice",
            "ref_text": "reference text",
            "ref_lang": "en",
        },
        files={
            "gpt_file": ("demo.ckpt", b"fake-gpt", "application/octet-stream"),
            "sovits_file": ("demo.pth", b"fake-sovits", "application/octet-stream"),
            "ref_audio_file": ("demo.wav", b"RIFFfake", "audio/wav"),
        },
    )
    assert upload_response.status_code == 201
    uploaded = upload_response.json()

    response = client.delete("/v1/voices/uploaded-demo")

    assert response.status_code == 200
    assert response.json() == {"status": "success", "name": "uploaded-demo"}
    assert client.get("/v1/voices").json() == []
    assert not (empty_voice_config.parent / uploaded["gpt_path"]).exists()
    assert not (empty_voice_config.parent / uploaded["sovits_path"]).exists()
    assert not (empty_voice_config.parent / uploaded["ref_audio"]).exists()
