import json
from datetime import datetime, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from backend.app.core.settings import AppSettings
from backend.app.main import create_app
from backend.app.schemas.edit_session import (
    ActiveDocumentState,
    DocumentSnapshot,
    EditableSegment,
    InitializeEditSessionRequest,
    VoiceBinding,
)


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


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _build_local_package(package_root: Path) -> Path:
    _write_json(
        package_root / "neo-tts-model.json",
        {
            "schema_version": 1,
            "package_id": "demo-gpt-sovits",
            "display_name": "Demo Voice",
            "adapter_id": "gpt_sovits_local",
            "source_type": "local_package",
            "instance": {
                "assets": {
                    "pretrained_base": "base",
                    "bert": "pretrained/bert.bin",
                }
            },
            "presets": [
                {
                    "preset_id": "default",
                    "display_name": "Default",
                    "assets": {
                        "gpt_weight": "weights/demo.ckpt",
                        "sovits_weight": "weights/demo.pth",
                        "reference_audio": "refs/demo.wav",
                    },
                    "defaults": {
                        "reference_text": "测试参考文本",
                        "reference_language": "zh",
                        "speed": 1.0,
                    },
                }
            ],
        },
    )
    _write_text(package_root / "base" / "README.txt", "base data")
    _write_text(package_root / "pretrained" / "bert.bin", "bert")
    _write_text(package_root / "weights" / "demo.ckpt", "ckpt")
    _write_text(package_root / "weights" / "demo.pth", "pth")
    _write_text(package_root / "refs" / "demo.wav", "wav")
    return package_root


def _build_external_package(package_root: Path) -> Path:
    _write_json(
        package_root / "neo-tts-model.json",
        {
            "schema_version": 1,
            "package_id": "remote-provider-a",
            "display_name": "Remote Provider A",
            "adapter_id": "external_http_tts",
            "source_type": "external_api",
            "instance": {
                "endpoint_url": "https://api.example.com/tts",
                "account_binding": {
                    "provider": "example",
                    "account_id": "acct-1",
                },
                "auth": {
                    "required_secrets": ["api_key"],
                },
            },
            "presets": [
                {
                    "preset_id": "voice-a",
                    "display_name": "Voice A",
                    "fixed_fields": {
                        "remote_voice_id": "voice_a",
                    },
                }
            ],
        },
    )
    return package_root


def _seed_active_session_for_voice(app, *, voice_id: str) -> None:
    repository = app.state.edit_session_repository
    snapshot = DocumentSnapshot(
        snapshot_id=f"head-{voice_id}",
        document_id="doc-1",
        snapshot_kind="head",
        document_version=1,
        default_voice_binding_id="binding-1",
        voice_bindings=[
            VoiceBinding(
                voice_binding_id="binding-1",
                scope="session",
                voice_id=voice_id,
                model_key="gpt-sovits-v2",
            )
        ],
        segments=[
            EditableSegment(
                segment_id="seg-1",
                document_id="doc-1",
                order_key=1,
                stem="测试句子",
                text_language="zh",
            )
        ],
        edges=[],
    )
    repository.save_snapshot(snapshot)
    repository.upsert_active_session(
        ActiveDocumentState(
            document_id="doc-1",
            session_status="ready",
            baseline_snapshot_id=snapshot.snapshot_id,
            head_snapshot_id=snapshot.snapshot_id,
            active_job_id="job-active-1",
            editable_mode="segment",
            initialize_request=InitializeEditSessionRequest(
                raw_text="测试句子。",
                voice_id=voice_id,
            ),
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
    )


def test_tts_registry_empty_state_and_health_are_valid(tmp_path: Path):
    settings = _build_settings(tmp_path)
    _write_json(settings.voices_config_path, {})

    with TestClient(create_app(settings=settings)) as client:
        adapters = client.get("/v1/tts-registry/adapters")
        models = client.get("/v1/tts-registry/models")
        voices = client.get("/v1/voices")
        health = client.get("/health")

    assert adapters.status_code == 200
    assert sorted(item["adapter_id"] for item in adapters.json()) == ["external_http_tts", "gpt_sovits_local"]
    external_adapter = next(item for item in adapters.json() if item["adapter_id"] == "external_http_tts")
    assert sorted(external_adapter["option_schema"]["properties"].keys()) == [
        "acquire_timeout_ms",
        "default_retry_backoff_ms",
        "max_concurrent_requests",
        "max_retry_attempts",
        "max_retry_backoff_ms",
        "requests_per_minute",
        "retry_on_429",
        "tokens_per_minute",
    ]
    assert models.status_code == 200
    assert models.json() == []
    assert voices.status_code == 200
    assert voices.json() == []
    assert health.status_code == 200
    assert health.json() == {"status": "ok"}


def test_tts_registry_imports_local_package_exposes_projection_and_supports_model_and_preset_crud(tmp_path: Path):
    settings = _build_settings(tmp_path)
    _write_json(settings.voices_config_path, {})
    package_root = _build_local_package(tmp_path / "local-package")

    with TestClient(create_app(settings=settings)) as client:
        imported = client.post(
            "/v1/tts-registry/models/import",
            json={"package_path": str(package_root), "storage_mode": "managed"},
        )
        models = client.get("/v1/tts-registry/models")
        detail = client.get("/v1/tts-registry/models/demo-gpt-sovits")
        presets = client.get("/v1/tts-registry/models/demo-gpt-sovits/presets")
        voices = client.get("/v1/voices")
        patched_model = client.patch(
            "/v1/tts-registry/models/demo-gpt-sovits",
            json={"display_name": "Demo Voice Updated", "status": "disabled"},
        )
        created_preset = client.post(
            "/v1/tts-registry/models/demo-gpt-sovits/presets",
            json={
                "preset_id": "user-a",
                "display_name": "User A",
                "kind": "user",
                "defaults": {"speed": 0.9},
            },
        )
        patched_preset = client.patch(
            "/v1/tts-registry/models/demo-gpt-sovits/presets/user-a",
            json={"display_name": "User A Updated", "status": "disabled"},
        )
        deleted_preset = client.delete("/v1/tts-registry/models/demo-gpt-sovits/presets/user-a")
        reloaded = client.post("/v1/tts-registry/reload")
        deleted_model = client.delete("/v1/tts-registry/models/demo-gpt-sovits")
        empty_voices = client.get("/v1/voices")

    assert imported.status_code == 201
    assert imported.json()["storage_mode"] == "managed"
    assert models.status_code == 200
    assert len(models.json()) == 1
    assert detail.status_code == 200
    assert detail.json()["model_instance_id"] == "demo-gpt-sovits"
    assert presets.status_code == 200
    assert presets.json()[0]["preset_id"] == "default"
    assert voices.status_code == 200
    assert voices.json()[0]["name"] == "demo-gpt-sovits"
    assert voices.json()[0]["model_instance_id"] == "demo-gpt-sovits"
    assert patched_model.status_code == 200
    assert patched_model.json()["display_name"] == "Demo Voice Updated"
    assert patched_model.json()["status"] == "disabled"
    assert created_preset.status_code == 201
    assert created_preset.json()["preset_id"] == "user-a"
    assert patched_preset.status_code == 200
    assert patched_preset.json()["display_name"] == "User A Updated"
    assert patched_preset.json()["status"] == "disabled"
    assert deleted_preset.status_code == 200
    assert deleted_preset.json()["preset_id"] == "user-a"
    assert reloaded.status_code == 200
    assert reloaded.json() == {"status": "success", "count": 1}
    assert deleted_model.status_code == 200
    assert deleted_model.json() == {"status": "deleted", "model_instance_id": "demo-gpt-sovits"}
    assert empty_voices.status_code == 200
    assert empty_voices.json() == []


def test_tts_registry_external_api_secret_flow_uses_standard_payload_without_plaintext_leak(tmp_path: Path):
    settings = _build_settings(tmp_path)
    _write_json(settings.voices_config_path, {})
    package_root = _build_external_package(tmp_path / "remote-package")

    with TestClient(create_app(settings=settings)) as client:
        imported = client.post(
            "/v1/tts-registry/models/import",
            json={"package_path": str(package_root), "storage_mode": "managed"},
        )
        before_secret = client.get("/v1/tts-registry/models/remote-provider-a")
        secret_response = client.put(
            "/v1/tts-registry/models/remote-provider-a/secrets",
            json={"secrets": {"api_key": "top-secret"}},
        )
        after_secret = client.get("/v1/tts-registry/models/remote-provider-a")

    assert imported.status_code == 201
    assert imported.json()["status"] == "needs_secret"
    assert imported.json()["endpoint"] == {"url": "https://api.example.com/tts"}
    assert imported.json()["account_binding"] == {
        "provider": "example",
        "account_id": "acct-1",
        "required_secrets": ["api_key"],
        "secret_handles": {},
    }
    assert before_secret.status_code == 200
    assert before_secret.json()["status"] == "needs_secret"
    assert secret_response.status_code == 200
    assert secret_response.json()["status"] == "ready"
    assert secret_response.json()["account_binding"]["secret_handles"] == {
        "api_key": "secret://remote-provider-a/api_key"
    }
    assert after_secret.status_code == 200
    assert after_secret.json()["status"] == "ready"
    assert "top-secret" not in (settings.tts_registry_root / "registry.json").read_text(encoding="utf-8")


def test_tts_registry_can_create_external_model_without_import_package(tmp_path: Path):
    settings = _build_settings(tmp_path)
    _write_json(settings.voices_config_path, {})

    with TestClient(create_app(settings=settings)) as client:
        created = client.post(
            "/v1/tts-registry/models",
            json={
                "model_instance_id": "remote-direct",
                "display_name": "Remote Direct",
                "adapter_id": "external_http_tts",
                "endpoint": {"url": "https://api.example.com/tts"},
                "account_binding": {
                    "provider": "example",
                    "account_id": "acct-direct",
                    "required_secrets": ["api_key"],
                },
                "adapter_options": {
                    "max_concurrent_requests": 2,
                    "requests_per_minute": 30,
                },
                "presets": [
                    {
                        "preset_id": "voice-a",
                        "display_name": "Voice A",
                        "kind": "remote",
                        "fixed_fields": {"remote_voice_id": "voice_a"},
                        "defaults": {
                            "reference_text": "远端参考文本",
                            "reference_language": "zh",
                        },
                    }
                ],
            },
        )
        detail = client.get("/v1/tts-registry/models/remote-direct")

    assert created.status_code == 201
    assert created.json()["model_instance_id"] == "remote-direct"
    assert created.json()["source_type"] == "external_api"
    assert created.json()["status"] == "needs_secret"
    assert created.json()["endpoint"] == {"url": "https://api.example.com/tts"}
    assert created.json()["account_binding"] == {
        "provider": "example",
        "account_id": "acct-direct",
        "required_secrets": ["api_key"],
        "secret_handles": {},
    }
    assert created.json()["adapter_options"] == {
        "max_concurrent_requests": 2,
        "requests_per_minute": 30,
    }
    assert created.json()["presets"][0]["fixed_fields"] == {"remote_voice_id": "voice_a"}
    assert detail.status_code == 200
    assert detail.json()["status"] == "needs_secret"


def test_tts_registry_external_model_preset_crud_routes_work_for_direct_create_flow(tmp_path: Path):
    settings = _build_settings(tmp_path)
    _write_json(settings.voices_config_path, {})

    with TestClient(create_app(settings=settings)) as client:
        created_model = client.post(
            "/v1/tts-registry/models",
            json={
                "model_instance_id": "remote-direct",
                "display_name": "Remote Direct",
                "adapter_id": "external_http_tts",
                "endpoint": {"url": "https://api.example.com/tts"},
                "account_binding": {
                    "provider": "example",
                    "account_id": "acct-direct",
                    "required_secrets": ["api_key"],
                },
                "presets": [],
            },
        )
        created_preset = client.post(
            "/v1/tts-registry/models/remote-direct/presets",
            json={
                "preset_id": "voice-a",
                "display_name": "Voice A",
                "kind": "remote",
                "fixed_fields": {"remote_voice_id": "voice_a"},
                "defaults": {"reference_text": "参考文本", "reference_language": "zh"},
            },
        )
        patched_preset = client.patch(
            "/v1/tts-registry/models/remote-direct/presets/voice-a",
            json={"display_name": "Voice A Updated", "defaults": {"reference_text": "更新后的参考文本"}},
        )
        listed = client.get("/v1/tts-registry/models/remote-direct/presets")
        deleted = client.delete("/v1/tts-registry/models/remote-direct/presets/voice-a")

    assert created_model.status_code == 201
    assert created_preset.status_code == 201
    assert created_preset.json()["kind"] == "remote"
    assert patched_preset.status_code == 200
    assert patched_preset.json()["display_name"] == "Voice A Updated"
    assert patched_preset.json()["defaults"] == {"reference_text": "更新后的参考文本"}
    assert listed.status_code == 200
    assert listed.json()[0]["preset_id"] == "voice-a"
    assert deleted.status_code == 200
    assert deleted.json() == {
        "status": "deleted",
        "model_instance_id": "remote-direct",
        "preset_id": "voice-a",
    }


def test_delete_model_returns_conflict_when_active_job_uses_projected_voice(tmp_path: Path):
    settings = _build_settings(tmp_path)
    _write_json(settings.voices_config_path, {})
    package_root = _build_local_package(tmp_path / "local-package")
    app = create_app(settings=settings)

    with TestClient(app) as client:
        imported = client.post(
            "/v1/tts-registry/models/import",
            json={"package_path": str(package_root), "storage_mode": "managed"},
        )
        assert imported.status_code == 201
        _seed_active_session_for_voice(app, voice_id="demo-gpt-sovits")

        response = client.delete("/v1/tts-registry/models/demo-gpt-sovits")

    assert response.status_code == 409
    assert response.json()["error_code"] == "model_in_use"
    assert response.json()["details"]["model_instance_id"] == "demo-gpt-sovits"


def test_delete_preset_returns_conflict_when_active_job_uses_projected_voice(tmp_path: Path):
    settings = _build_settings(tmp_path)
    _write_json(settings.voices_config_path, {})
    package_root = _build_local_package(tmp_path / "local-package")
    app = create_app(settings=settings)

    with TestClient(app) as client:
        imported = client.post(
            "/v1/tts-registry/models/import",
            json={"package_path": str(package_root), "storage_mode": "managed"},
        )
        assert imported.status_code == 201
        created_preset = client.post(
            "/v1/tts-registry/models/demo-gpt-sovits/presets",
            json={
                "preset_id": "style-a",
                "display_name": "Style A",
                "kind": "user",
                "defaults": {"speed": 0.9},
            },
        )
        assert created_preset.status_code == 201
        _seed_active_session_for_voice(app, voice_id="demo-gpt-sovits__style-a")

        response = client.delete("/v1/tts-registry/models/demo-gpt-sovits/presets/style-a")

    assert response.status_code == 409
    assert response.json()["error_code"] == "preset_in_use"
    assert response.json()["details"]["model_instance_id"] == "demo-gpt-sovits"
    assert response.json()["details"]["preset_id"] == "style-a"
