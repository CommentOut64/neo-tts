import json
from pathlib import Path

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
    assert data[0]["weight_storage_mode"] == "external"
    assert data[0]["gpt_fingerprint"]
    assert data[0]["sovits_fingerprint"]


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


def test_reload_voices_recovers_external_voice_when_metadata_uses_external_weights(tmp_path):
    managed_voice_dir = tmp_path / "managed_voices" / "external-demo"
    references_dir = managed_voice_dir / "references"
    references_dir.mkdir(parents=True)
    (references_dir / "ref-demo.wav").write_bytes(b"RIFFfake")
    (managed_voice_dir / "voice.json").write_text(
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
                    "speed": 1.0,
                    "top_k": 15,
                    "top_p": 1.0,
                    "temperature": 1.0,
                    "pause_length": 0.3,
                },
                "managed": True,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    (managed_voice_dir / "reference.json").write_text(
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
    client = TestClient(create_app(settings=settings))

    reload_response = client.post("/v1/voices/reload")

    assert reload_response.status_code == 200
    assert reload_response.json() == {"status": "success", "count": 1}
    list_response = client.get("/v1/voices")
    assert list_response.status_code == 200
    payload = list_response.json()[0]
    assert payload["name"] == "external-demo"
    assert payload["weight_storage_mode"] == "external"
    assert payload["gpt_path"] == "F:/GPT-SoVITS-v2pro-20250604/demo.ckpt"
    assert payload["sovits_path"] == "F:/GPT-SoVITS-v2pro-20250604/demo.pth"


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
    assert response.json()["weight_storage_mode"] == "external"
    assert response.json()["gpt_fingerprint"]
    assert response.json()["sovits_fingerprint"]


def test_list_voices_migrates_legacy_profiles_into_registry_and_subsequent_reads_use_registry(sample_voice_config):
    settings = AppSettings(
        project_root=sample_voice_config.parent,
        voices_config_path=sample_voice_config,
        tts_registry_root=sample_voice_config.parent / "tts-registry",
    )
    client = TestClient(create_app(settings=settings))

    first_list = client.get("/v1/voices")

    assert first_list.status_code == 200
    assert [voice["name"] for voice in first_list.json()] == ["demo"]
    registry_payload = json.loads((settings.tts_registry_root / "registry.json").read_text(encoding="utf-8"))
    assert [model["model_instance_id"] for model in registry_payload["models"]] == ["demo"]
    assert registry_payload["models"][0]["presets"][0]["preset_id"] == "default"

    sample_voice_config.write_text("{}", encoding="utf-8")

    reload_response = client.post("/v1/voices/reload")
    detail_response = client.get("/v1/voices/demo")

    assert reload_response.status_code == 200
    assert reload_response.json() == {"status": "success", "count": 1}
    assert detail_response.status_code == 200
    assert detail_response.json()["name"] == "demo"


def test_upload_update_delete_voice_keep_registry_projection_in_sync(empty_voice_config):
    managed_dir = empty_voice_config.parent / "managed_voices"
    settings = AppSettings(
        project_root=empty_voice_config.parent,
        voices_config_path=empty_voice_config,
        managed_voices_dir=managed_dir,
        tts_registry_root=empty_voice_config.parent / "tts-registry",
    )
    client = TestClient(create_app(settings=settings))

    upload_response = client.post(
        "/v1/voices/upload",
        data={
            "name": "uploaded-demo",
            "description": "uploaded voice",
            "ref_text": "reference text",
            "ref_lang": "en",
            "copy_weights_into_project": "true",
        },
        files={
            "gpt_file": ("demo.ckpt", b"fake-gpt", "application/octet-stream"),
            "sovits_file": ("demo.pth", b"fake-sovits", "application/octet-stream"),
            "ref_audio_file": ("demo.wav", b"RIFFfake", "audio/wav"),
        },
    )
    assert upload_response.status_code == 201
    registry_after_upload = _load_registry(settings.tts_registry_root)
    assert [model["model_instance_id"] for model in registry_after_upload["models"]] == ["uploaded-demo"]

    update_response = client.patch(
        "/v1/voices/uploaded-demo",
        data={
            "description": "updated voice",
            "ref_text": "updated reference text",
            "ref_lang": "ja",
        },
    )

    assert update_response.status_code == 200
    detail_response = client.get("/v1/voices/uploaded-demo")
    assert detail_response.status_code == 200
    assert detail_response.json()["description"] == "updated voice"
    assert detail_response.json()["ref_text"] == "updated reference text"
    assert detail_response.json()["ref_lang"] == "ja"

    delete_response = client.delete("/v1/voices/uploaded-demo")

    assert delete_response.status_code == 200
    assert _load_registry(settings.tts_registry_root)["models"] == []


def _load_registry(registry_root: Path) -> dict:
    return json.loads((registry_root / "registry.json").read_text(encoding="utf-8"))


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
            "copy_weights_into_project": "true",
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
    assert payload["weight_storage_mode"] == "managed"
    assert payload["gpt_fingerprint"]
    assert payload["sovits_fingerprint"]
    assert payload["defaults"]["speed"] == 1.1
    assert (empty_voice_config.parent / payload["gpt_path"]).exists()
    assert (empty_voice_config.parent / payload["sovits_path"]).exists()
    assert (empty_voice_config.parent / payload["ref_audio"]).exists()
    reference_sidecar = json.loads(
        (managed_dir / "uploaded-demo" / "reference.json").read_text(encoding="utf-8"),
    )
    assert reference_sidecar["reference_asset_id"]
    assert reference_sidecar["ref_audio"] == payload["ref_audio"]
    assert reference_sidecar["ref_audio_fingerprint"]
    assert reference_sidecar["ref_text"] == "reference text"
    assert reference_sidecar["ref_text_fingerprint"]
    assert reference_sidecar["ref_lang"] == "en"
    assert reference_sidecar["updated_at"]

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
            "copy_weights_into_project": "true",
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


def test_upload_voice_supports_external_weight_paths_when_copy_disabled(empty_voice_config):
    managed_dir = empty_voice_config.parent / "managed_voices"
    external_dir = empty_voice_config.parent / "external-models"
    external_dir.mkdir(parents=True)
    gpt_path = (external_dir / "demo.ckpt")
    sovits_path = (external_dir / "demo.pth")
    gpt_path.write_bytes(b"fake-gpt")
    sovits_path.write_bytes(b"fake-sovits")
    settings = AppSettings(
        project_root=empty_voice_config.parent,
        voices_config_path=empty_voice_config,
        managed_voices_dir=managed_dir,
    )
    client = TestClient(create_app(settings=settings))

    response = client.post(
        "/v1/voices/upload",
        data={
            "name": "external-demo",
            "description": "external voice",
            "ref_text": "reference text",
            "ref_lang": "en",
            "copy_weights_into_project": "false",
            "gpt_external_path": str(gpt_path.resolve()),
            "sovits_external_path": str(sovits_path.resolve()),
        },
        files={
            "ref_audio_file": ("demo.wav", b"RIFFfake", "audio/wav"),
        },
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["name"] == "external-demo"
    assert payload["managed"] is True
    assert payload["weight_storage_mode"] == "external"
    assert payload["gpt_path"] == gpt_path.resolve().as_posix()
    assert payload["sovits_path"] == sovits_path.resolve().as_posix()
    assert (empty_voice_config.parent / payload["ref_audio"]).exists()


def test_upload_voice_rejects_conflicting_weight_inputs(empty_voice_config):
    managed_dir = empty_voice_config.parent / "managed_voices"
    external_dir = empty_voice_config.parent / "external-models"
    external_dir.mkdir(parents=True)
    gpt_path = external_dir / "demo.ckpt"
    sovits_path = external_dir / "demo.pth"
    gpt_path.write_bytes(b"fake-gpt")
    sovits_path.write_bytes(b"fake-sovits")
    settings = AppSettings(
        project_root=empty_voice_config.parent,
        voices_config_path=empty_voice_config,
        managed_voices_dir=managed_dir,
    )
    client = TestClient(create_app(settings=settings))

    response = client.post(
        "/v1/voices/upload",
        data={
            "name": "conflict-demo",
            "description": "conflict voice",
            "ref_text": "reference text",
            "ref_lang": "en",
            "copy_weights_into_project": "false",
            "gpt_external_path": str(gpt_path.resolve()),
            "sovits_external_path": str(sovits_path.resolve()),
        },
        files={
            "gpt_file": ("demo.ckpt", b"fake-gpt", "application/octet-stream"),
            "sovits_file": ("demo.pth", b"fake-sovits", "application/octet-stream"),
            "ref_audio_file": ("demo.wav", b"RIFFfake", "audio/wav"),
        },
    )

    assert response.status_code == 400
    assert response.json() == {
        "detail": "Provide either external weight paths or uploaded weight files, not both.",
    }


def test_upload_voice_requires_external_weight_paths_when_copy_disabled(empty_voice_config):
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
            "name": "external-demo",
            "description": "external voice",
            "ref_text": "reference text",
            "ref_lang": "en",
            "copy_weights_into_project": "false",
        },
        files={
            "ref_audio_file": ("demo.wav", b"RIFFfake", "audio/wav"),
        },
    )

    assert response.status_code == 400
    assert response.json() == {
        "detail": "gpt_external_path and sovits_external_path are required when copy_weights_into_project is false.",
    }


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
            "copy_weights_into_project": "true",
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


def test_delete_external_voice_keeps_external_weights_and_removes_managed_reference_asset(empty_voice_config):
    managed_dir = empty_voice_config.parent / "managed_voices"
    external_dir = empty_voice_config.parent / "external-models"
    external_dir.mkdir(parents=True)
    gpt_path = external_dir / "demo.ckpt"
    sovits_path = external_dir / "demo.pth"
    gpt_path.write_bytes(b"fake-gpt")
    sovits_path.write_bytes(b"fake-sovits")
    settings = AppSettings(
        project_root=empty_voice_config.parent,
        voices_config_path=empty_voice_config,
        managed_voices_dir=managed_dir,
    )
    client = TestClient(create_app(settings=settings))

    upload_response = client.post(
        "/v1/voices/upload",
        data={
            "name": "external-demo",
            "description": "external voice",
            "ref_text": "reference text",
            "ref_lang": "en",
            "copy_weights_into_project": "false",
            "gpt_external_path": str(gpt_path.resolve()),
            "sovits_external_path": str(sovits_path.resolve()),
        },
        files={
            "ref_audio_file": ("demo.wav", b"RIFFfake", "audio/wav"),
        },
    )
    assert upload_response.status_code == 201
    uploaded = upload_response.json()

    response = client.delete("/v1/voices/external-demo")

    assert response.status_code == 200
    assert response.json() == {"status": "success", "name": "external-demo"}
    assert gpt_path.exists()
    assert sovits_path.exists()
    assert not (empty_voice_config.parent / uploaded["ref_audio"]).exists()


def test_update_voice_updates_managed_voice_metadata_and_reference_sidecar(empty_voice_config):
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
            "copy_weights_into_project": "true",
        },
        files={
            "gpt_file": ("demo.ckpt", b"fake-gpt", "application/octet-stream"),
            "sovits_file": ("demo.pth", b"fake-sovits", "application/octet-stream"),
            "ref_audio_file": ("demo.wav", b"RIFFfake", "audio/wav"),
        },
    )
    assert upload_response.status_code == 201

    response = client.patch(
        "/v1/voices/uploaded-demo",
        data={
            "description": "updated voice",
            "ref_text": "updated reference text",
            "ref_lang": "ja",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["description"] == "updated voice"
    assert payload["ref_text"] == "updated reference text"
    assert payload["ref_lang"] == "ja"
    assert payload["weight_storage_mode"] == "managed"
    assert payload["gpt_fingerprint"]
    assert payload["sovits_fingerprint"]
    reference_sidecar = json.loads((managed_dir / "uploaded-demo" / "reference.json").read_text(encoding="utf-8"))
    assert reference_sidecar["reference_asset_id"]
    assert reference_sidecar["ref_audio"] == payload["ref_audio"]
    assert reference_sidecar["ref_audio_fingerprint"]
    assert reference_sidecar["ref_text"] == "updated reference text"
    assert reference_sidecar["ref_text_fingerprint"]
    assert reference_sidecar["ref_lang"] == "ja"
    assert reference_sidecar["updated_at"]


def test_update_voice_supports_external_weight_paths_for_managed_external_voice(empty_voice_config):
    managed_dir = empty_voice_config.parent / "managed_voices"
    external_dir = empty_voice_config.parent / "external-models"
    external_dir.mkdir(parents=True)
    first_gpt_path = external_dir / "demo-a.ckpt"
    first_sovits_path = external_dir / "demo-a.pth"
    second_gpt_path = external_dir / "demo-b.ckpt"
    second_sovits_path = external_dir / "demo-b.pth"
    first_gpt_path.write_bytes(b"fake-gpt-a")
    first_sovits_path.write_bytes(b"fake-sovits-a")
    second_gpt_path.write_bytes(b"fake-gpt-b")
    second_sovits_path.write_bytes(b"fake-sovits-b")
    settings = AppSettings(
        project_root=empty_voice_config.parent,
        voices_config_path=empty_voice_config,
        managed_voices_dir=managed_dir,
    )
    client = TestClient(create_app(settings=settings))

    upload_response = client.post(
        "/v1/voices/upload",
        data={
            "name": "external-demo",
            "description": "external voice",
            "ref_text": "reference text",
            "ref_lang": "en",
            "copy_weights_into_project": "false",
            "gpt_external_path": str(first_gpt_path.resolve()),
            "sovits_external_path": str(first_sovits_path.resolve()),
        },
        files={
            "ref_audio_file": ("demo.wav", b"RIFFfake", "audio/wav"),
        },
    )
    assert upload_response.status_code == 201

    response = client.patch(
        "/v1/voices/external-demo",
        data={
            "description": "updated external voice",
            "copy_weights_into_project": "false",
            "gpt_external_path": str(second_gpt_path.resolve()),
            "sovits_external_path": str(second_sovits_path.resolve()),
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["description"] == "updated external voice"
    assert payload["weight_storage_mode"] == "external"
    assert payload["gpt_path"] == second_gpt_path.resolve().as_posix()
    assert payload["sovits_path"] == second_sovits_path.resolve().as_posix()


def test_update_voice_rejects_static_voice(sample_voice_config):
    settings = AppSettings(
        project_root=sample_voice_config.parent,
        voices_config_path=sample_voice_config,
        managed_voices_dir=sample_voice_config.parent / "managed_voices",
    )
    client = TestClient(create_app(settings=settings))

    response = client.patch(
        "/v1/voices/demo",
        data={
            "description": "updated voice",
            "ref_text": "updated reference text",
            "ref_lang": "ja",
        },
    )

    assert response.status_code == 409
    assert response.json() == {"detail": "Voice 'demo' is not managed and cannot be edited."}
