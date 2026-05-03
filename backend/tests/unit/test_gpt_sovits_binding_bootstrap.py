import importlib
import json
from pathlib import Path

from backend.app.core.settings import AppSettings


def _load_binding_bootstrap_module():
    try:
        return importlib.import_module("backend.app.tts_registry.gpt_sovits_binding_bootstrap")
    except ModuleNotFoundError as exc:
        raise AssertionError("缺少正式 GPT-SoVITS binding bootstrap helper 模块。") from exc


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _build_settings(tmp_path: Path, voices_config_path: Path) -> AppSettings:
    return AppSettings(
        project_root=tmp_path,
        voices_config_path=voices_config_path,
        user_data_root=tmp_path / "storage",
        tts_registry_root=tmp_path / "storage" / "tts-registry",
        gpt_sovits_adapter_installed=True,
        managed_voices_dir=tmp_path / "managed_voices",
        synthesis_results_dir=tmp_path / "synthesis_results",
        inference_params_cache_file=tmp_path / "state" / "params_cache.json",
        edit_session_db_file=tmp_path / "storage" / "edit_session" / "session.db",
        edit_session_assets_dir=tmp_path / "storage" / "edit_session" / "assets",
        edit_session_exports_dir=tmp_path / "storage" / "edit_session" / "exports",
        edit_session_staging_ttl_seconds=60,
    )


def test_ensure_gpt_sovits_binding_for_voice_requires_existing_formal_binding_by_default(tmp_path: Path):
    module = _load_binding_bootstrap_module()
    voices_config_path = tmp_path / "voices.json"
    _write_json(
        voices_config_path,
        {
            "Demo Voice": {
                "gpt_path": "weights/demo.ckpt",
                "sovits_path": "weights/demo.pth",
                "ref_audio": "refs/demo.wav",
                "ref_text": "hello world",
                "ref_lang": "en",
            }
        },
    )
    settings = _build_settings(tmp_path, voices_config_path)

    try:
        module.ensure_gpt_sovits_binding_for_voice(
            settings=settings,
            workspace_slug="formal-gpt-sovits",
            workspace_display_name="Formal GPT-SoVITS",
            voice_id="Demo Voice",
        )
    except LookupError as exc:
        assert "正式 binding_ref" in str(exc)
    else:
        raise AssertionError("默认模式下不应再从 voices.json 自动自举正式 binding。")


def test_ensure_gpt_sovits_binding_for_voice_can_bootstrap_requested_voice_when_legacy_compat_enabled(tmp_path: Path):
    module = _load_binding_bootstrap_module()
    voices_config_path = tmp_path / "voices.json"
    _write_json(
        voices_config_path,
        {
            "Demo Voice": {
                "gpt_path": "weights/demo.ckpt",
                "sovits_path": "weights/demo.pth",
                "ref_audio": "refs/demo.wav",
                "ref_text": "hello world",
                "ref_lang": "en",
            }
        },
    )
    settings = _build_settings(tmp_path, voices_config_path)

    workspace_service, binding_ref, resolved = module.ensure_gpt_sovits_binding_for_voice(
        settings=settings,
        workspace_slug="formal-gpt-sovits",
        workspace_display_name="Formal GPT-SoVITS",
        voice_id="Demo Voice",
        allow_legacy_bootstrap=True,
    )

    assert binding_ref.model_dump(mode="json") == {
        "workspace_id": "ws_formal_gpt_sovits",
        "main_model_id": "demo_voice",
        "submodel_id": "default",
        "preset_id": "default",
    }
    assert workspace_service.list_workspaces()[0].workspace_id == "ws_formal_gpt_sovits"
    assert resolved["gpt_path"] == "weights/demo.ckpt"
    assert resolved["sovits_path"] == "weights/demo.pth"
    assert resolved["reference_audio_path"] == "refs/demo.wav"


def test_ensure_gpt_sovits_binding_for_voice_reuses_existing_formal_binding(tmp_path: Path):
    module = _load_binding_bootstrap_module()
    voices_config_path = tmp_path / "voices.json"
    _write_json(
        voices_config_path,
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
    settings = _build_settings(tmp_path, voices_config_path)

    first_workspace_service, first_binding_ref, _ = module.ensure_gpt_sovits_binding_for_voice(
        settings=settings,
        workspace_slug="test-gpt-sovits",
        workspace_display_name="Test GPT-SoVITS",
        voice_id="demo",
        allow_legacy_bootstrap=True,
    )
    second_workspace_service, second_binding_ref, _ = module.ensure_gpt_sovits_binding_for_voice(
        settings=settings,
        workspace_slug="test-gpt-sovits",
        workspace_display_name="Test GPT-SoVITS",
        voice_id="demo",
        allow_legacy_bootstrap=True,
    )

    assert first_binding_ref == second_binding_ref
    assert [item.workspace_id for item in second_workspace_service.list_workspaces()] == ["ws_test_gpt_sovits"]
    tree = first_workspace_service.get_workspace_tree("ws_test_gpt_sovits")
    assert [item.main_model_id for item in tree.main_models] == ["demo"]
