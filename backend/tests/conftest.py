from dataclasses import dataclass
import json
import os
from pathlib import Path
import sys

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.core.settings import AppSettings, get_settings
from backend.app.repositories.voice_repository import VoiceRepository
from backend.app.services.voice_service import VoiceService


REAL_MODEL_VOICE_ID = "neuro2"
REAL_MODEL_SEGMENT_BOUNDARY_MODE = "zh_period"
REAL_MODEL_TEXT_LANGUAGE = "zh"
REAL_MODEL_TTS_TEXT = (
    "他急忙冲到马路对面，回到办公室，厉声吩咐秘书不要来打扰他，然后抓起话筒，刚要拨通家里的电话，临时又变了卦。"
    "他放下话筒，摸着胡须，琢磨起来。"
    "不，他太愚蠢了。"
    "波特并不是一个稀有的姓，肯定有许多人姓波特，而且有儿子叫哈利。"
    "想到这里，他甚至连自己的外甥是不是哈利波特都拿不定了。"
)
REAL_MODEL_EXPECTED_SEGMENTS = [
    "他急忙冲到马路对面，回到办公室，厉声吩咐秘书不要来打扰他，然后抓起话筒，刚要拨通家里的电话，临时又变了卦。",
    "他放下话筒，摸着胡须，琢磨起来。",
    "不，他太愚蠢了。",
    "波特并不是一个稀有的姓，肯定有许多人姓波特，而且有儿子叫哈利。",
    "想到这里，他甚至连自己的外甥是不是哈利波特都拿不定了。",
]
REAL_MODEL_UPDATED_FIRST_SEGMENT = (
    "他急忙冲到马路对面，回到办公室，沉声吩咐秘书不要来打扰他，然后抓起话筒，刚要拨通家里的电话，临时又变了卦。"
)


@dataclass(frozen=True)
class RealModelEnv:
    enabled: bool
    voice_id: str
    reference_audio_path: Path
    reference_text: str
    tts_text: str
    expected_segments: list[str]
    updated_first_segment_text: str
    text_language: str
    segment_boundary_mode: str


def require_real_model_env() -> RealModelEnv:
    enabled = os.getenv("GPT_SOVITS_E2E") == "1"
    if not enabled:
        pytest.skip("未启用真实模型 E2E，请设置 GPT_SOVITS_E2E=1。")

    settings = get_settings()
    try:
        voice = VoiceService(VoiceRepository(settings=settings)).get_voice(REAL_MODEL_VOICE_ID)
    except LookupError as exc:
        pytest.skip(f"真实模型 E2E 缺少预设 voice '{REAL_MODEL_VOICE_ID}': {exc}")

    reference_audio_path = Path(voice.ref_audio)
    if not reference_audio_path.is_absolute():
        reference_audio_path = (settings.project_root / reference_audio_path).resolve()
    if not reference_audio_path.exists():
        pytest.skip(f"真实模型参考音频不存在: {reference_audio_path}")

    return RealModelEnv(
        enabled=True,
        voice_id=REAL_MODEL_VOICE_ID,
        reference_audio_path=reference_audio_path,
        reference_text=voice.ref_text,
        tts_text=REAL_MODEL_TTS_TEXT,
        expected_segments=list(REAL_MODEL_EXPECTED_SEGMENTS),
        updated_first_segment_text=REAL_MODEL_UPDATED_FIRST_SEGMENT,
        text_language=REAL_MODEL_TEXT_LANGUAGE,
        segment_boundary_mode=REAL_MODEL_SEGMENT_BOUNDARY_MODE,
    )


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
        gpt_sovits_adapter_installed=True,
        managed_voices_dir=project_root / "managed_voices",
        synthesis_results_dir=project_root / "synthesis_results",
        inference_params_cache_file=project_root / "state" / "params_cache.json",
        edit_session_db_file=project_root / "storage" / "edit_session" / "session.db",
        edit_session_assets_dir=project_root / "storage" / "edit_session" / "assets",
        edit_session_exports_dir=project_root / "storage" / "edit_session" / "exports",
        edit_session_staging_ttl_seconds=60,
    )


@pytest.fixture()
def real_model_env() -> RealModelEnv:
    return require_real_model_env()


@pytest.fixture()
def real_model_app_settings(tmp_path: Path) -> AppSettings:
    base_settings = get_settings()
    return AppSettings(
        project_root=base_settings.project_root,
        voices_config_path=base_settings.voices_config_path,
        managed_voices_dir=base_settings.managed_voices_dir,
        synthesis_results_dir=tmp_path / "synthesis_results",
        inference_params_cache_file=tmp_path / "state" / "params_cache.json",
        edit_session_db_file=tmp_path / "storage" / "edit_session" / "session.db",
        edit_session_assets_dir=tmp_path / "storage" / "edit_session" / "assets",
        edit_session_exports_dir=tmp_path / "storage" / "edit_session" / "exports",
        edit_session_staging_ttl_seconds=base_settings.edit_session_staging_ttl_seconds,
        cnhubert_base_path=base_settings.cnhubert_base_path,
        bert_path=base_settings.bert_path,
    )
