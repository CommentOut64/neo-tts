from pathlib import Path
import json
import sys

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.core.settings import AppSettings


@pytest.fixture()
def sample_voice_config(tmp_path: Path) -> Path:
    config = {
        "demo": {
            "gpt_path": "pretrained_models/demo.ckpt",
            "sovits_path": "pretrained_models/demo.pth",
            "ref_audio": "pretrained_models/demo.wav",
            "ref_text": "hello world",
            "ref_lang": "en",
            "description": "demo voice",
            "defaults": {
                "speed": 1.0,
                "top_k": 15,
                "top_p": 1.0,
                "temperature": 1.0,
                "pause_length": 0.3,
            },
        }
    }
    path = tmp_path / "voices.json"
    path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


@pytest.fixture()
def empty_voice_config(tmp_path: Path) -> Path:
    path = tmp_path / "voices.json"
    path.write_text("{}", encoding="utf-8")
    return path


@pytest.fixture()
def test_app_settings(sample_voice_config: Path) -> AppSettings:
    project_root = sample_voice_config.parent
    return AppSettings(
        project_root=project_root,
        voices_config_path=sample_voice_config,
        managed_voices_dir=project_root / "managed_voices",
        synthesis_results_dir=project_root / "synthesis_results",
        inference_params_cache_file=project_root / "state" / "params_cache.json",
        edit_session_db_file=project_root / "storage" / "edit_session" / "session.db",
        edit_session_assets_dir=project_root / "storage" / "edit_session" / "assets",
        edit_session_staging_ttl_seconds=60,
    )
