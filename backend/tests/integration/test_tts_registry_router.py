import json
from datetime import datetime, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from backend.app.core.settings import AppSettings
from backend.app.main import create_app
from backend.app.schemas.edit_session import (
    ActiveDocumentState,
    BindingReference,
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
        qwen3_tts_adapter_installed=True,
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


def _seed_active_session_for_model(app, *, model_instance_id: str, preset_id: str = "default") -> None:
    repository = app.state.edit_session_repository
    voice_id = model_instance_id if preset_id == "default" else f"{model_instance_id}__{preset_id}"
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
                binding_ref=BindingReference(
                    workspace_id="legacy",
                    main_model_id=model_instance_id,
                    submodel_id="gpt-sovits-v2",
                    preset_id=preset_id,
                ),
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
        workspaces = client.get("/v1/tts-registry/workspaces")
        health = client.get("/health")

    assert adapters.status_code == 200
    assert sorted(item["adapter_id"] for item in adapters.json()) == [
        "external_http_tts",
        "gpt_sovits_local",
        "qwen3_tts_local",
    ]
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
    assert workspaces.status_code == 200
    assert workspaces.json() == []
    assert health.status_code == 200
    assert health.json() == {"status": "ok"}


def test_tts_registry_openapi_does_not_expose_legacy_flat_model_protocol(tmp_path: Path):
    settings = _build_settings(tmp_path)
    _write_json(settings.voices_config_path, {})

    with TestClient(create_app(settings=settings)) as client:
        openapi = client.get("/openapi.json")

    assert openapi.status_code == 200
    paths = openapi.json()["paths"]
    assert "/v1/tts-registry/workspaces" in paths
    assert "/v1/tts-registry/workspaces/{workspace_id}/main-models" in paths
    assert "/v1/tts-registry/workspaces/{workspace_id}/main-models/{main_model_id}/submodels" in paths
    assert (
        "/v1/tts-registry/workspaces/{workspace_id}/main-models/{main_model_id}/submodels/{submodel_id}/presets"
        in paths
    )
    assert "/v1/tts-registry/models" not in paths
    assert "/v1/tts-registry/models/import" not in paths
    assert "/v1/tts-registry/reload" not in paths


def test_tts_registry_legacy_flat_model_routes_are_not_found(tmp_path: Path):
    settings = _build_settings(tmp_path)
    _write_json(settings.voices_config_path, {})

    with TestClient(create_app(settings=settings)) as client:
        routes = [
            ("get", "/v1/tts-registry/models"),
            ("post", "/v1/tts-registry/models/import"),
            ("post", "/v1/tts-registry/models"),
            ("get", "/v1/tts-registry/models/remote-direct"),
            ("put", "/v1/tts-registry/models/remote-direct/secrets"),
            ("get", "/v1/tts-registry/models/remote-direct/presets"),
            ("post", "/v1/tts-registry/models/remote-direct/presets"),
            ("patch", "/v1/tts-registry/models/remote-direct/presets/voice-a"),
            ("delete", "/v1/tts-registry/models/remote-direct/presets/voice-a"),
            ("post", "/v1/tts-registry/reload"),
        ]
        responses = []
        for method, path in routes:
            kwargs = {"json": {}} if method in {"post", "put", "patch"} else {}
            response = getattr(client, method)(path, **kwargs)
            responses.append(response.status_code)

    assert responses == [404] * len(responses)


def test_tts_registry_adapter_family_catalog_declares_supported_families_and_schema_groups(tmp_path: Path):
    settings = _build_settings(tmp_path)
    _write_json(settings.voices_config_path, {})

    with TestClient(create_app(settings=settings)) as client:
        adapters = client.get("/v1/tts-registry/adapters")
        families = client.get("/v1/tts-registry/adapters/external_http_tts/families")

    assert adapters.status_code == 200
    external_adapter = next(item for item in adapters.json() if item["adapter_id"] == "external_http_tts")
    assert external_adapter["supported_families"]
    assert families.status_code == 200
    first_family = families.json()[0]
    assert first_family["family_id"]
    assert first_family["route_slug"]
    assert first_family["workspace_form_schema"] is not None
    assert first_family["main_model_form_schema"] is not None
    assert first_family["submodel_form_schema"] is not None
    assert first_family["preset_form_schema"] is not None


def test_tts_registry_gpt_sovits_family_exposes_explicit_submodel_and_preset_management(tmp_path: Path):
    settings = _build_settings(tmp_path)
    _write_json(settings.voices_config_path, {})

    with TestClient(create_app(settings=settings)) as client:
        families = client.get("/v1/tts-registry/adapters/gpt_sovits_local/families")

    assert families.status_code == 200
    family = families.json()[0]
    assert family["family_id"] == "gpt_sovits_local_default"
    assert family["supports_submodels"] is True
    assert family["auto_singleton_submodel"] is False
    assert any(field["field_key"] == "gpt_weight.path" for field in family["submodel_form_schema"])
    assert any(field["field_key"] == "sovits_weight.path" for field in family["submodel_form_schema"])
    assert any(field["field_key"] == "reference_text" for field in family["preset_form_schema"])
    assert any(field["field_key"] == "reference_audio.path" for field in family["preset_form_schema"])


def test_tts_registry_qwen3_family_exposes_workspace_model_and_preset_fields(tmp_path: Path):
    settings = _build_settings(tmp_path)
    _write_json(settings.voices_config_path, {})

    with TestClient(create_app(settings=settings)) as client:
        families = client.get("/v1/tts-registry/adapters/qwen3_tts_local/families")

    assert families.status_code == 200
    family = families.json()[0]
    assert family["family_id"] == "qwen3_tts_local_default"
    assert family["supports_submodels"] is True
    assert family["supports_presets"] is True
    assert family["auto_singleton_submodel"] is False
    assert any(field["field_key"] == "model_dir.path" for field in family["submodel_form_schema"])
    assert any(field["field_key"] == "generation_mode" for field in family["preset_form_schema"])
    assert any(field["field_key"] == "speaker" for field in family["preset_form_schema"])
    assert any(field["field_key"] == "reference_audio.path" for field in family["preset_form_schema"])
