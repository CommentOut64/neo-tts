import json
from pathlib import Path

from fastapi.testclient import TestClient

from backend.app.core.settings import AppSettings
from backend.app.main import create_app


def _build_settings(tmp_path: Path) -> AppSettings:
    return AppSettings(
        project_root=tmp_path,
        voices_config_path=tmp_path / "voices.json",
        tts_registry_root=tmp_path / "tts-registry",
        gpt_sovits_adapter_installed=True,
        managed_voices_dir=tmp_path / "managed_voices",
        synthesis_results_dir=tmp_path / "synthesis_results",
        inference_params_cache_file=tmp_path / "state" / "params_cache.json",
        edit_session_db_file=tmp_path / "storage" / "edit_session" / "session.db",
        edit_session_assets_dir=tmp_path / "storage" / "edit_session" / "assets",
        edit_session_exports_dir=tmp_path / "storage" / "edit_session" / "exports",
        edit_session_staging_ttl_seconds=60,
    )


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def test_tts_registry_workspace_crud_returns_tree_payload(tmp_path: Path):
    settings = _build_settings(tmp_path)
    _write_json(settings.voices_config_path, {})

    with TestClient(create_app(settings=settings)) as client:
        families = client.get("/v1/tts-registry/adapters/external_http_tts/families")
        assert families.status_code == 200
        family = families.json()[0]
        created = client.post(
            "/v1/tts-registry/workspaces",
            json={
                "adapter_id": "external_http_tts",
                "family_id": family["family_id"],
                "display_name": "Remote Workspace",
                "slug": "remote-workspace",
            },
        )
        assert created.status_code == 201
        workspace_id = created.json()["workspace_id"]
        listed = client.get("/v1/tts-registry/workspaces")
        detail = client.get(f"/v1/tts-registry/workspaces/{workspace_id}")

    assert listed.status_code == 200
    listed_item = next(item for item in listed.json() if item["workspace_id"] == workspace_id)
    assert listed_item["family_display_name"] == family["display_name"]
    assert listed_item["family_route_slug"] == family["route_slug"]
    assert listed_item["binding_display_strategy"] == family["binding_display_strategy"]
    assert detail.status_code == 200
    payload = detail.json()
    assert payload["workspace"]["workspace_id"] == workspace_id
    assert payload["workspace"]["adapter_id"] == "external_http_tts"
    assert payload["workspace"]["family_id"] == family["family_id"]
    assert payload["main_models"] == []
    assert created.json()["family_display_name"] == family["display_name"]
    assert created.json()["family_route_slug"] == family["route_slug"]
    assert created.json()["binding_display_strategy"] == family["binding_display_strategy"]


def test_tts_registry_workspace_main_model_creation_auto_normalizes_hidden_singletons(tmp_path: Path):
    settings = _build_settings(tmp_path)
    _write_json(settings.voices_config_path, {})

    with TestClient(create_app(settings=settings)) as client:
        families = client.get("/v1/tts-registry/adapters/external_http_tts/families")
        assert families.status_code == 200
        family = families.json()[0]
        created_workspace = client.post(
            "/v1/tts-registry/workspaces",
            json={
                "adapter_id": "external_http_tts",
                "family_id": family["family_id"],
                "display_name": "Remote Workspace",
                "slug": "remote-workspace",
            },
        )
        assert created_workspace.status_code == 201
        workspace_id = created_workspace.json()["workspace_id"]
        created_main_model = client.post(
            f"/v1/tts-registry/workspaces/{workspace_id}/main-models",
            json={
                "main_model_id": "qwen3-tts-1-7b",
                "display_name": "Qwen3-TTS 1.7B",
            },
        )
        detail = client.get(f"/v1/tts-registry/workspaces/{workspace_id}")

    assert created_main_model.status_code == 201
    assert detail.status_code == 200
    main_model = detail.json()["main_models"][0]
    assert main_model["main_model_id"] == "qwen3-tts-1-7b"
    assert main_model["default_submodel_id"] == "default"
    submodel = main_model["submodels"][0]
    assert submodel["submodel_id"] == "default"
    assert submodel["is_hidden_singleton"] is True
    preset = submodel["presets"][0]
    assert preset["preset_id"] == "default"
    assert preset["is_hidden_singleton"] is True


def test_tts_registry_startup_does_not_auto_migrate_legacy_voices_by_default(tmp_path: Path):
    settings = _build_settings(tmp_path)
    _write_json(
        settings.voices_config_path,
        {
            "demo": {
                "gpt_path": "weights/demo.ckpt",
                "sovits_path": "weights/demo.pth",
                "ref_audio": "refs/demo.wav",
                "ref_text": "hello world",
                "ref_lang": "en",
            }
        },
    )

    with TestClient(create_app(settings=settings)) as client:
        workspaces = client.get("/v1/tts-registry/workspaces")
        catalog = client.get("/v1/tts-registry/bindings/catalog")

    assert workspaces.status_code == 200
    assert workspaces.json() == []
    assert catalog.status_code == 200
    assert catalog.json()["items"] == []


def test_tts_registry_startup_can_opt_in_legacy_voice_migration(tmp_path: Path):
    settings = AppSettings(
        project_root=tmp_path,
        voices_config_path=tmp_path / "voices.json",
        tts_registry_root=tmp_path / "tts-registry",
        gpt_sovits_adapter_installed=True,
        managed_voices_dir=tmp_path / "managed_voices",
        synthesis_results_dir=tmp_path / "synthesis_results",
        inference_params_cache_file=tmp_path / "state" / "params_cache.json",
        edit_session_db_file=tmp_path / "storage" / "edit_session" / "session.db",
        edit_session_assets_dir=tmp_path / "storage" / "edit_session" / "assets",
        edit_session_exports_dir=tmp_path / "storage" / "edit_session" / "exports",
        edit_session_staging_ttl_seconds=60,
        auto_migrate_legacy_voices_on_start=True,
    )
    _write_json(
        settings.voices_config_path,
        {
            "demo": {
                "gpt_path": "weights/demo.ckpt",
                "sovits_path": "weights/demo.pth",
                "ref_audio": "refs/demo.wav",
                "ref_text": "hello world",
                "ref_lang": "en",
            }
        },
    )

    with TestClient(create_app(settings=settings)) as client:
        workspaces = client.get("/v1/tts-registry/workspaces")
        catalog = client.get("/v1/tts-registry/bindings/catalog")

    assert workspaces.status_code == 200
    assert [item["workspace_id"] for item in workspaces.json()] == ["ws_legacy_gpt_sovits"]
    assert catalog.status_code == 200
    assert catalog.json()["items"][0]["workspace_id"] == "ws_legacy_gpt_sovits"
    assert catalog.json()["items"][0]["main_models"][0]["main_model_id"] == "demo"


def test_tts_registry_gpt_sovits_main_model_creation_requires_explicit_submodel_management(tmp_path: Path):
    settings = _build_settings(tmp_path)
    _write_json(settings.voices_config_path, {})

    with TestClient(create_app(settings=settings)) as client:
        families = client.get("/v1/tts-registry/adapters/gpt_sovits_local/families")
        assert families.status_code == 200
        family = families.json()[0]
        created_workspace = client.post(
            "/v1/tts-registry/workspaces",
            json={
                "adapter_id": "gpt_sovits_local",
                "family_id": family["family_id"],
                "display_name": "GPT-SoVITS Workspace",
                "slug": "gpt-sovits-workspace",
            },
        )
        assert created_workspace.status_code == 201
        workspace_id = created_workspace.json()["workspace_id"]
        created_main_model = client.post(
            f"/v1/tts-registry/workspaces/{workspace_id}/main-models",
            json={
                "main_model_id": "demo_voice",
                "display_name": "Demo Voice",
            },
        )
        detail = client.get(f"/v1/tts-registry/workspaces/{workspace_id}")

    assert created_main_model.status_code == 201
    assert detail.status_code == 200
    main_model = detail.json()["main_models"][0]
    assert main_model["main_model_id"] == "demo_voice"
    assert main_model["default_submodel_id"] is None
    assert main_model["submodels"] == []


def test_tts_registry_main_model_persists_shared_assets_for_gpt_sovits_workspace(tmp_path: Path):
    settings = _build_settings(tmp_path)
    _write_json(settings.voices_config_path, {})

    with TestClient(create_app(settings=settings)) as client:
        families = client.get("/v1/tts-registry/adapters/gpt_sovits_local/families")
        assert families.status_code == 200
        family = families.json()[0]
        created_workspace = client.post(
            "/v1/tts-registry/workspaces",
            json={
                "adapter_id": "gpt_sovits_local",
                "family_id": family["family_id"],
                "display_name": "GPT-SoVITS Workspace",
                "slug": "gpt-sovits-workspace",
            },
        )
        assert created_workspace.status_code == 201
        workspace_id = created_workspace.json()["workspace_id"]
        created_main_model = client.post(
            f"/v1/tts-registry/workspaces/{workspace_id}/main-models",
            json={
                "main_model_id": "demo_voice",
                "display_name": "Demo Voice",
                "source_type": "local_package",
                "main_model_metadata": {"runtime": "gpt_sovits"},
                "shared_assets": {
                    "bert": {"path": "pretrained/bert.bin", "fingerprint": "bert-fp"},
                    "hubert": {"path": "pretrained/hubert.bin", "fingerprint": "hubert-fp"},
                },
            },
        )
        detail = client.get(f"/v1/tts-registry/workspaces/{workspace_id}")

    assert created_main_model.status_code == 201
    assert detail.status_code == 200
    main_model = detail.json()["main_models"][0]
    assert main_model["shared_assets"] == {
        "bert": {"path": "pretrained/bert.bin", "fingerprint": "bert-fp"},
        "hubert": {"path": "pretrained/hubert.bin", "fingerprint": "hubert-fp"},
    }
