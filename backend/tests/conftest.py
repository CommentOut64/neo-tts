from pathlib import Path
import json

import pytest


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
