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
                    "preset_id": "speaker-a",
                    "display_name": "Speaker A",
                    "assets": {
                        "gpt_weight": "weights/demo.ckpt",
                        "sovits_weight": "weights/demo.pth",
                        "reference_audio": "refs/demo.wav",
                    },
                    "defaults": {
                        "reference_text": "测试参考文本",
                        "reference_language": "zh",
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


def test_tts_registry_workspace_scoped_gpt_sovits_import_creates_formal_workspace_tree(tmp_path: Path):
    settings = _build_settings(tmp_path)
    _write_json(settings.voices_config_path, {})
    package_root = _build_local_package(tmp_path / "source-package")

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

        imported = client.post(
            f"/v1/tts-registry/workspaces/{workspace_id}/imports/model-package",
            json={
                "source_path": str(package_root),
                "storage_mode": "managed",
            },
        )
        detail = client.get(f"/v1/tts-registry/workspaces/{workspace_id}")

    assert imported.status_code == 201
    assert imported.json()["main_model"]["main_model_id"] == "gpt_sovits"
    assert detail.status_code == 200
    main_model = detail.json()["main_models"][0]
    assert main_model["shared_assets"]["bert"]["source_path"].endswith("pretrained/bert.bin")
    assert main_model["submodels"][0]["submodel_id"] == "speaker_a"
    assert main_model["submodels"][0]["presets"][0]["preset_id"] == "default"
