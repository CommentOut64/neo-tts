from __future__ import annotations

import json
from pathlib import Path
import time
from types import SimpleNamespace

import numpy as np
from fastapi.testclient import TestClient

from backend.app.core.settings import AppSettings
from backend.app.main import create_app


def _build_settings(tmp_path: Path) -> AppSettings:
    return AppSettings(
        project_root=tmp_path,
        voices_config_path=tmp_path / "voices.json",
        tts_registry_root=tmp_path / "tts-registry",
        qwen3_tts_root=tmp_path,
        qwen3_tts_adapter_installed=True,
        gpt_sovits_adapter_installed=False,
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


def _build_qwen3_package(package_root: Path) -> Path:
    _write_json(
        package_root / "neo-tts-model.json",
        {
            "schema_version": 1,
            "package_id": "qwen3-tts-12hz-1-7b-customvoice",
            "display_name": "Qwen3-TTS 1.7B CustomVoice",
            "adapter_id": "qwen3_tts_local",
            "source_type": "local_package",
            "instance": {
                "assets": {
                    "model_dir": "model",
                }
            },
            "presets": [
                {
                    "preset_id": "vivian",
                    "display_name": "Vivian",
                    "defaults": {
                        "speaker": "Vivian",
                        "language": "Chinese",
                    },
                    "fixed_fields": {
                        "generation_mode": "custom_voice",
                    },
                }
            ],
        },
    )
    _write_text(package_root / "model" / "config.json", "{}")
    _write_text(package_root / "model" / "tokenizer_config.json", "{}")
    _write_text(package_root / "model" / "model.safetensors", "weights")
    return package_root


class _FakeQwenRuntime:
    def __init__(self) -> None:
        self.calls: list[object] = []

    def render_segment(self, request):
        self.calls.append(request)
        value = 0.1 if request.segment_id.endswith("1") else 0.2
        return SimpleNamespace(
            segment_id=request.segment_id,
            audio=np.asarray([value], dtype=np.float32),
            sample_rate=4,
            trace={"generation_mode": request.generation_mode},
        )


def _wait_until(predicate, *, timeout: float = 5.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return
        time.sleep(0.05)
    raise AssertionError("Condition not met before timeout.")


def test_block_first_qwen3_local_adapter_initialize_job_completes_with_binding_ref(tmp_path: Path):
    settings = _build_settings(tmp_path)
    _write_json(settings.voices_config_path, {})
    package_root = _build_qwen3_package(tmp_path / "qwen3-package")
    app = create_app(settings=settings)

    with TestClient(app) as client:
        client.app.state.qwen3_tts_runtime = _FakeQwenRuntime()
        families = client.get("/v1/tts-registry/adapters/qwen3_tts_local/families")
        assert families.status_code == 200
        family = families.json()[0]
        created_workspace = client.post(
            "/v1/tts-registry/workspaces",
            json={
                "adapter_id": "qwen3_tts_local",
                "family_id": family["family_id"],
                "display_name": "Qwen3 Workspace",
                "slug": "qwen3-workspace",
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
        assert imported.status_code == 201
        main_model_id = imported.json()["main_model"]["main_model_id"]
        initialize = client.post(
            "/v1/edit-session/initialize",
            json={
                "raw_text": "第一句。第二句。",
                "binding_ref": {
                    "workspace_id": workspace_id,
                    "main_model_id": main_model_id,
                    "submodel_id": "default",
                    "preset_id": "vivian",
                },
            },
        )
        assert initialize.status_code == 202
        _wait_until(lambda: client.get("/v1/edit-session/snapshot").json()["session_status"] == "ready")
        snapshot = client.get("/v1/edit-session/snapshot").json()
        timeline = client.get("/v1/edit-session/timeline").json()
        audio = client.get(timeline["block_entries"][0]["audio_url"])

    assert len(snapshot["segments"]) == 2
    assert timeline["block_entries"]
    assert audio.status_code == 200
    assert len(client.app.state.qwen3_tts_runtime.calls) == 2
