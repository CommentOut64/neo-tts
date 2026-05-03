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
from backend.app.schemas.edit_session import BindingReference
from backend.app.tts_registry.gpt_sovits_binding_bootstrap import ensure_gpt_sovits_binding_for_voice


REAL_MODEL_VOICE_ID = "neuro2"
REAL_MODEL_WORKSPACE_ID = "ws_real_gpt_sovits"
REAL_MODEL_WORKSPACE_SLUG = "real-gpt-sovits"
REAL_MODEL_WORKSPACE_DISPLAY_NAME = "Real GPT-SoVITS"
TEST_MODEL_VOICE_ID = "demo"
TEST_MODEL_WORKSPACE_ID = "ws_test_gpt_sovits"
TEST_MODEL_WORKSPACE_SLUG = "test-gpt-sovits"
TEST_MODEL_WORKSPACE_DISPLAY_NAME = "Test GPT-SoVITS"
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
    binding_ref: dict[str, str]
    reference_audio_path: Path
    reference_text: str
    tts_text: str
    expected_segments: list[str]
    updated_first_segment_text: str
    text_language: str
    segment_boundary_mode: str


def _ensure_real_model_binding(settings: AppSettings) -> tuple[object, BindingReference, dict[str, object]]:
    return ensure_gpt_sovits_binding_for_voice(
        settings=settings,
        workspace_slug=REAL_MODEL_WORKSPACE_SLUG,
        workspace_display_name=REAL_MODEL_WORKSPACE_DISPLAY_NAME,
        voice_id=REAL_MODEL_VOICE_ID,
        allow_legacy_bootstrap=True,
    )


def require_real_model_env(*, settings: AppSettings | None = None) -> RealModelEnv:
    enabled = os.getenv("GPT_SOVITS_E2E") == "1"
    if not enabled:
        pytest.skip("未启用真实模型 E2E，请设置 GPT_SOVITS_E2E=1。")

    resolved_settings = settings or get_settings()
    try:
        _, binding_ref, resolved_binding = _ensure_real_model_binding(resolved_settings)
    except LookupError as exc:
        pytest.skip(f"真实模型 E2E 缺少正式 binding_ref '{REAL_MODEL_VOICE_ID}': {exc}")

    reference_audio_raw = str(resolved_binding.get("reference_audio_path") or "")
    if not reference_audio_raw:
        pytest.skip(f"真实模型 binding_ref '{REAL_MODEL_VOICE_ID}' 缺少 reference_audio_path。")
    reference_audio_path = Path(reference_audio_raw)
    if not reference_audio_path.is_absolute():
        reference_audio_path = (resolved_settings.project_root / reference_audio_path).resolve()
    if not reference_audio_path.exists():
        pytest.skip(f"真实模型参考音频不存在: {reference_audio_path}")

    return RealModelEnv(
        enabled=True,
        binding_ref=binding_ref.model_dump(mode="json"),
        reference_audio_path=reference_audio_path,
        reference_text=str(resolved_binding.get("reference_text") or ""),
        tts_text=REAL_MODEL_TTS_TEXT,
        expected_segments=list(REAL_MODEL_EXPECTED_SEGMENTS),
        updated_first_segment_text=REAL_MODEL_UPDATED_FIRST_SEGMENT,
        text_language=REAL_MODEL_TEXT_LANGUAGE,
        segment_boundary_mode=REAL_MODEL_SEGMENT_BOUNDARY_MODE,
    )


def _ensure_test_binding(settings: AppSettings, *, voice_id: str = TEST_MODEL_VOICE_ID) -> BindingReference:
    _, binding_ref, _ = ensure_gpt_sovits_binding_for_voice(
        settings=settings,
        workspace_slug=TEST_MODEL_WORKSPACE_SLUG,
        workspace_display_name=TEST_MODEL_WORKSPACE_DISPLAY_NAME,
        voice_id=voice_id,
        allow_legacy_bootstrap=True,
    )
    return binding_ref


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
    settings = AppSettings(
        project_root=project_root,
        voices_config_path=sample_voice_config,
        user_data_root=project_root / "storage",
        tts_registry_root=project_root / "storage" / "tts-registry",
        gpt_sovits_adapter_installed=True,
        managed_voices_dir=project_root / "managed_voices",
        synthesis_results_dir=project_root / "synthesis_results",
        inference_params_cache_file=project_root / "state" / "params_cache.json",
        edit_session_db_file=project_root / "storage" / "edit_session" / "session.db",
        edit_session_assets_dir=project_root / "storage" / "edit_session" / "assets",
        edit_session_exports_dir=project_root / "storage" / "edit_session" / "exports",
        edit_session_staging_ttl_seconds=60,
    )
    _ensure_test_binding(settings, voice_id=TEST_MODEL_VOICE_ID)
    return settings


@pytest.fixture()
def real_model_env(real_model_app_settings: AppSettings) -> RealModelEnv:
    return require_real_model_env(settings=real_model_app_settings)


@pytest.fixture()
def demo_binding_ref(test_app_settings: AppSettings) -> dict[str, str]:
    binding_ref = _ensure_test_binding(test_app_settings, voice_id=TEST_MODEL_VOICE_ID)
    return binding_ref.model_dump(mode="json")


@pytest.fixture()
def real_model_app_settings(tmp_path: Path) -> AppSettings:
    base_settings = get_settings()
    settings = AppSettings(
        project_root=base_settings.project_root,
        voices_config_path=base_settings.voices_config_path,
        user_data_root=tmp_path,
        tts_registry_root=tmp_path / "tts-registry",
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
    _ensure_real_model_binding(settings)
    return settings
