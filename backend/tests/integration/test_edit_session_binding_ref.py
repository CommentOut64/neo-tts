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


def test_initialize_edit_session_openapi_uses_binding_ref_instead_of_voice_id(tmp_path: Path):
    settings = _build_settings(tmp_path)
    _write_json(settings.voices_config_path, {})

    with TestClient(create_app(settings=settings)) as client:
        openapi = client.get("/openapi.json")

    assert openapi.status_code == 200
    schema = openapi.json()["components"]["schemas"]["InitializeEditSessionRequest"]
    properties = schema["properties"]
    assert "binding_ref" in properties
    assert "voice_id" not in properties
    assert "binding_ref" in schema.get("required", [])


def test_voice_binding_patch_openapi_switches_to_binding_ref_contract(tmp_path: Path):
    settings = _build_settings(tmp_path)
    _write_json(settings.voices_config_path, {})

    with TestClient(create_app(settings=settings)) as client:
        openapi = client.get("/openapi.json")

    assert openapi.status_code == 200
    schema = openapi.json()["components"]["schemas"]["SynthesisBindingPatchRequest"]
    properties = schema["properties"]
    assert "binding_ref" in properties
    assert "voice_id" not in properties
    assert "model_key" not in properties


def test_edit_session_openapi_promotes_synthesis_binding_routes_instead_of_voice_binding(tmp_path: Path):
    settings = _build_settings(tmp_path)
    _write_json(settings.voices_config_path, {})

    with TestClient(create_app(settings=settings)) as client:
        openapi = client.get("/openapi.json")

    assert openapi.status_code == 200
    paths = openapi.json()["paths"]
    assert "/v1/edit-session/synthesis-bindings" in paths
    assert "/v1/edit-session/session/synthesis-binding" in paths
    assert "/v1/edit-session/segments/{segment_id}/synthesis-binding" in paths
    assert "/v1/edit-session/voice-bindings" not in paths
    assert "/v1/edit-session/session/voice-binding" not in paths
    assert "/v1/edit-session/segments/{segment_id}/voice-binding" not in paths
