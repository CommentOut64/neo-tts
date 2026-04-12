from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path


@dataclass(frozen=True)
class AppSettings:
    project_root: Path
    voices_config_path: Path
    owner_control_origin: str | None = None
    owner_control_token: str | None = None
    owner_session_id: str | None = None
    managed_voices_dir: Path = Path("storage/managed_voices")
    synthesis_results_dir: Path = Path("storage/synthesis_results")
    inference_params_cache_file: Path = Path("storage/inference/params_cache.json")
    edit_session_db_file: Path = Path("storage/edit_session/session.db")
    edit_session_assets_dir: Path = Path("storage/edit_session/assets")
    edit_session_exports_dir: Path = Path("storage/edit_session/exports")
    edit_session_staging_ttl_seconds: int = 3600
    cnhubert_base_path: Path = Path("pretrained_models/chinese-hubert-base")
    bert_path: Path = Path("pretrained_models/chinese-roberta-wwm-ext-large")


def get_settings() -> AppSettings:
    project_root = Path(__file__).resolve().parents[3]
    voices_config_env = os.environ.get("GPT_SOVITS_VOICES_CONFIG")
    managed_voices_dir_env = os.environ.get("GPT_SOVITS_MANAGED_VOICES_DIR")
    synthesis_results_dir_env = os.environ.get("GPT_SOVITS_SYNTHESIS_RESULTS_DIR")
    inference_params_cache_file_env = os.environ.get("GPT_SOVITS_INFERENCE_PARAMS_CACHE_FILE")
    edit_session_db_file_env = os.environ.get("GPT_SOVITS_EDIT_SESSION_DB_FILE")
    edit_session_assets_dir_env = os.environ.get("GPT_SOVITS_EDIT_SESSION_ASSETS_DIR")
    edit_session_exports_dir_env = os.environ.get("GPT_SOVITS_EDIT_SESSION_EXPORTS_DIR")
    edit_session_staging_ttl_env = os.environ.get("GPT_SOVITS_EDIT_SESSION_STAGING_TTL_SECONDS")
    cnhubert_path_env = os.environ.get("CNHUBERT_PATH") or os.environ.get("GPT_SOVITS_CNHUBERT_PATH")
    bert_path_env = os.environ.get("BERT_PATH") or os.environ.get("GPT_SOVITS_BERT_PATH")
    owner_control_origin = os.environ.get("NEO_TTS_OWNER_CONTROL_ORIGIN")
    owner_control_token = os.environ.get("NEO_TTS_OWNER_CONTROL_TOKEN")
    owner_session_id = os.environ.get("NEO_TTS_OWNER_SESSION_ID")
    voices_config_path = Path(voices_config_env) if voices_config_env else project_root / "config" / "voices.json"
    managed_voices_dir = (
        Path(managed_voices_dir_env) if managed_voices_dir_env else Path("storage/managed_voices")
    )
    synthesis_results_dir = (
        Path(synthesis_results_dir_env) if synthesis_results_dir_env else Path("storage/synthesis_results")
    )
    inference_params_cache_file = (
        Path(inference_params_cache_file_env)
        if inference_params_cache_file_env
        else Path("storage/inference/params_cache.json")
    )
    edit_session_db_file = (
        Path(edit_session_db_file_env) if edit_session_db_file_env else Path("storage/edit_session/session.db")
    )
    edit_session_assets_dir = (
        Path(edit_session_assets_dir_env) if edit_session_assets_dir_env else Path("storage/edit_session/assets")
    )
    edit_session_exports_dir = (
        Path(edit_session_exports_dir_env) if edit_session_exports_dir_env else Path("storage/edit_session/exports")
    )
    edit_session_staging_ttl_seconds = int(edit_session_staging_ttl_env or 3600)
    cnhubert_base_path = Path(cnhubert_path_env) if cnhubert_path_env else Path("pretrained_models/chinese-hubert-base")
    bert_path = Path(bert_path_env) if bert_path_env else Path("pretrained_models/chinese-roberta-wwm-ext-large")
    return AppSettings(
        project_root=project_root,
        voices_config_path=voices_config_path,
        owner_control_origin=owner_control_origin,
        owner_control_token=owner_control_token,
        owner_session_id=owner_session_id,
        managed_voices_dir=managed_voices_dir,
        synthesis_results_dir=synthesis_results_dir,
        inference_params_cache_file=inference_params_cache_file,
        edit_session_db_file=edit_session_db_file,
        edit_session_assets_dir=edit_session_assets_dir,
        edit_session_exports_dir=edit_session_exports_dir,
        edit_session_staging_ttl_seconds=edit_session_staging_ttl_seconds,
        cnhubert_base_path=cnhubert_base_path,
        bert_path=bert_path,
    )
