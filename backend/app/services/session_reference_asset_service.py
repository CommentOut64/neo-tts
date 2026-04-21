from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from uuid import uuid4

from pydantic import BaseModel, Field

from backend.app.core.exceptions import AssetNotFoundError
from backend.app.inference.asset_fingerprint import fingerprint_file, fingerprint_text


class SessionReferenceAsset(BaseModel):
    reference_asset_id: str = Field(description="会话临时参考资产 ID。")
    session_id: str = Field(description="所属会话 ID。")
    binding_key: str | None = Field(default=None, description="可选的绑定键。")
    audio_path: str = Field(description="会话临时参考音频绝对路径。")
    audio_fingerprint: str = Field(description="参考音频指纹。")
    reference_text: str = Field(default="", description="参考文本。")
    reference_text_fingerprint: str = Field(default="", description="参考文本指纹。")
    reference_language: str = Field(default="", description="参考语言。")
    created_at: datetime = Field(description="资产创建时间。")


class SessionReferenceAssetService:
    def __init__(self, *, assets_root: Path) -> None:
        self._references_root = assets_root / "references"
        self._references_root.mkdir(parents=True, exist_ok=True)

    def create_asset(
        self,
        *,
        session_id: str,
        filename: str,
        payload: bytes,
        binding_key: str | None = None,
        reference_text: str = "",
        reference_language: str = "",
    ) -> SessionReferenceAsset:
        asset_id = uuid4().hex
        suffix = Path(filename).suffix.lower()
        asset_dir = self._asset_dir(session_id=session_id, reference_asset_id=asset_id)
        asset_dir.mkdir(parents=True, exist_ok=False)
        audio_path = asset_dir / f"audio{suffix}"
        audio_path.write_bytes(payload)
        asset = SessionReferenceAsset(
            reference_asset_id=asset_id,
            session_id=session_id,
            binding_key=binding_key,
            audio_path=str(audio_path),
            audio_fingerprint=fingerprint_file(str(audio_path)),
            reference_text=reference_text,
            reference_text_fingerprint=fingerprint_text(reference_text),
            reference_language=reference_language,
            created_at=datetime.now(timezone.utc),
        )
        self._write_metadata(asset)
        return asset

    def get_asset(self, *, session_id: str, reference_asset_id: str) -> SessionReferenceAsset:
        metadata_path = self._metadata_path(session_id=session_id, reference_asset_id=reference_asset_id)
        if not metadata_path.is_file():
            raise AssetNotFoundError(f"Session reference asset '{reference_asset_id}' not found.")
        try:
            payload = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise AssetNotFoundError(f"Session reference asset '{reference_asset_id}' metadata is unavailable.") from exc
        return SessionReferenceAsset.model_validate(payload)

    def update_asset(
        self,
        *,
        session_id: str,
        reference_asset_id: str,
        binding_key: str | None = None,
        reference_text: str | None = None,
        reference_language: str | None = None,
    ) -> SessionReferenceAsset:
        current = self.get_asset(session_id=session_id, reference_asset_id=reference_asset_id)
        next_asset = current.model_copy(
            update={
                "binding_key": binding_key if binding_key is not None else current.binding_key,
                "reference_text": reference_text if reference_text is not None else current.reference_text,
                "reference_text_fingerprint": fingerprint_text(
                    reference_text if reference_text is not None else current.reference_text
                ),
                "reference_language": reference_language if reference_language is not None else current.reference_language,
            }
        )
        self._write_metadata(next_asset)
        return next_asset

    def _write_metadata(self, asset: SessionReferenceAsset) -> None:
        metadata_path = self._metadata_path(
            session_id=asset.session_id,
            reference_asset_id=asset.reference_asset_id,
        )
        metadata_path.parent.mkdir(parents=True, exist_ok=True)
        metadata_path.write_text(
            json.dumps(asset.model_dump(mode="json"), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _asset_dir(self, *, session_id: str, reference_asset_id: str) -> Path:
        return self._references_root / self._safe_leaf(session_id) / self._safe_leaf(reference_asset_id)

    def _metadata_path(self, *, session_id: str, reference_asset_id: str) -> Path:
        return self._asset_dir(session_id=session_id, reference_asset_id=reference_asset_id) / "metadata.json"

    @staticmethod
    def _safe_leaf(raw_value: str) -> str:
        value = raw_value.strip()
        if not value or any(token in value for token in ("..", "/", "\\")):
            raise ValueError(f"Invalid session reference asset path leaf '{raw_value}'.")
        return value
