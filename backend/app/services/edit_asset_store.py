from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import shutil


class EditAssetStore:
    def __init__(self, *, project_root: Path, assets_dir: Path, staging_ttl_seconds: int) -> None:
        self._project_root = project_root
        self._assets_dir = self._resolve_path(assets_dir)
        self._staging_ttl = timedelta(seconds=staging_ttl_seconds)
        self._assets_dir.mkdir(parents=True, exist_ok=True)
        self._staging_root.mkdir(parents=True, exist_ok=True)
        self._formal_root.mkdir(parents=True, exist_ok=True)

    def segment_asset_path(self, render_asset_id: str) -> Path:
        return self._formal_root / "segments" / self._validate_leaf_name(render_asset_id)

    def boundary_asset_path(self, boundary_asset_id: str) -> Path:
        return self._formal_root / "boundaries" / self._validate_leaf_name(boundary_asset_id)

    def write_staging_bytes(self, job_id: str, relative_path: str, payload: bytes) -> Path:
        job_root = self._staging_root / self._validate_leaf_name(job_id)
        relative = self._validate_relative_path(relative_path)
        target_path = (job_root / relative).resolve()
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_bytes(payload)
        return target_path

    def promote_staging_tree(self, job_id: str, target_prefix: str) -> list[Path]:
        job_root = self._staging_root / self._validate_leaf_name(job_id)
        if not job_root.exists():
            raise FileNotFoundError(f"Staging tree for job '{job_id}' not found.")

        target_root = self._assets_dir / self._validate_relative_path(target_prefix)
        promoted_paths: list[Path] = []
        for source_path in sorted(path for path in job_root.rglob("*") if path.is_file()):
            relative_path = source_path.relative_to(job_root)
            destination_path = target_root / relative_path
            destination_path.parent.mkdir(parents=True, exist_ok=True)
            source_path.replace(destination_path)
            promoted_paths.append(destination_path)

        shutil.rmtree(job_root, ignore_errors=False)
        return promoted_paths

    def cleanup_expired_staging(self, *, now: datetime | None = None) -> int:
        now = now or datetime.now(timezone.utc)
        removed = 0
        if not self._staging_root.exists():
            return 0

        for child in self._staging_root.iterdir():
            if not child.is_dir():
                continue
            modified_at = datetime.fromtimestamp(child.stat().st_mtime, tz=timezone.utc)
            if now - modified_at <= self._staging_ttl:
                continue
            shutil.rmtree(child, ignore_errors=False)
            removed += 1
        return removed

    @property
    def _staging_root(self) -> Path:
        return self._assets_dir / "staging"

    @property
    def _formal_root(self) -> Path:
        return self._assets_dir / "formal"

    def _resolve_path(self, value: Path) -> Path:
        if value.is_absolute():
            return value
        return (self._project_root / value).resolve()

    @staticmethod
    def _validate_leaf_name(value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Asset identifier must not be empty.")
        if normalized in {".", ".."} or any(separator in normalized for separator in ("/", "\\")):
            raise ValueError("Asset identifier must not contain path separators.")
        return normalized

    @staticmethod
    def _validate_relative_path(value: str) -> Path:
        path = Path(value)
        if path.is_absolute():
            raise ValueError("Relative path must not be absolute.")
        if ".." in path.parts:
            raise ValueError("Relative path must not escape the asset root.")
        return path
