from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import io
import os
from pathlib import Path
import shutil
import wave
import json
from uuid import uuid4

import numpy as np
from pydantic import TypeAdapter

from backend.app.inference.editable_types import (
    BlockCompositionAssetPayload,
    BlockMarkerEntry,
    BoundaryAssetPayload,
    EdgeCompositionEntry,
    SegmentCompositionEntry,
    SegmentRenderAssetPayload,
)
from backend.app.schemas.edit_session import TimelineManifest


@dataclass(frozen=True)
class PreviewAssetRecord:
    job_id: str
    preview_asset_id: str
    preview_kind: str
    expires_at: datetime
    asset_path: Path
    audio_file_path: Path


@dataclass(frozen=True)
class AssetGcReport:
    deleted_asset_paths: list[Path]
    kept_asset_paths: list[Path]


class EditAssetStore:
    def __init__(
        self,
        *,
        project_root: Path,
        assets_dir: Path,
        export_root: Path,
        staging_ttl_seconds: int,
    ) -> None:
        self._project_root = project_root
        self._assets_dir = self._resolve_path(assets_dir)
        self._export_root = self._resolve_path(export_root)
        self._staging_ttl = timedelta(seconds=staging_ttl_seconds)
        self._assets_dir.mkdir(parents=True, exist_ok=True)
        self._staging_root.mkdir(parents=True, exist_ok=True)
        self._formal_root.mkdir(parents=True, exist_ok=True)
        self._export_root.mkdir(parents=True, exist_ok=True)

    def segment_asset_path(self, render_asset_id: str) -> Path:
        return self._formal_root / "segments" / self._validate_leaf_name(render_asset_id)

    def boundary_asset_path(self, boundary_asset_id: str) -> Path:
        return self._formal_root / "boundaries" / self._validate_leaf_name(boundary_asset_id)

    def block_asset_path(self, block_asset_id: str) -> Path:
        return self._formal_root / "blocks" / self._validate_leaf_name(block_asset_id)

    def composition_asset_path(self, composition_manifest_id: str) -> Path:
        return self._formal_root / "compositions" / self._validate_leaf_name(composition_manifest_id)

    def timeline_manifest_path(self, timeline_manifest_id: str) -> Path:
        return self._formal_root / "timelines" / self._validate_leaf_name(timeline_manifest_id)

    def preview_asset_path(self, preview_asset_id: str) -> Path:
        return self._formal_root / "previews" / self._validate_leaf_name(preview_asset_id)

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

    def clear_all(self) -> None:
        if self._assets_dir.exists():
            shutil.rmtree(self._assets_dir, ignore_errors=False)
        self._assets_dir.mkdir(parents=True, exist_ok=True)
        self._staging_root.mkdir(parents=True, exist_ok=True)
        self._formal_root.mkdir(parents=True, exist_ok=True)

    def cleanup_staging_job(self, job_id: str) -> bool:
        job_root = self._staging_root / self._validate_leaf_name(job_id)
        if not job_root.exists():
            return False
        shutil.rmtree(job_root, ignore_errors=False)
        return True

    def write_preview_bytes(self, preview_asset_id: str, payload: bytes) -> Path:
        asset_dir = self.preview_asset_path(preview_asset_id)
        asset_dir.mkdir(parents=True, exist_ok=True)
        target_path = asset_dir / "audio.wav"
        target_path.write_bytes(payload)
        return target_path

    def create_preview_asset(
        self,
        *,
        job_id: str,
        preview_asset_id: str,
        preview_kind: str,
        payload: bytes,
        ttl_seconds: int,
        now: datetime | None = None,
    ) -> PreviewAssetRecord:
        asset_dir = self.preview_asset_path(preview_asset_id)
        asset_dir.mkdir(parents=True, exist_ok=True)
        expires_at = (now or datetime.now(timezone.utc)) + timedelta(seconds=ttl_seconds)
        audio_file_path = asset_dir / "audio.wav"
        audio_file_path.write_bytes(payload)
        metadata_path = asset_dir / "metadata.json"
        metadata_path.write_text(
            json.dumps(
                {
                    "job_id": job_id,
                    "preview_asset_id": preview_asset_id,
                    "preview_kind": preview_kind,
                    "expires_at": expires_at.isoformat(),
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        return PreviewAssetRecord(
            job_id=job_id,
            preview_asset_id=preview_asset_id,
            preview_kind=preview_kind,
            expires_at=expires_at,
            asset_path=asset_dir,
            audio_file_path=audio_file_path,
        )

    def get_preview_asset_record(self, preview_asset_id: str) -> PreviewAssetRecord:
        asset_dir = self.preview_asset_path(preview_asset_id)
        metadata = self._read_json(asset_dir / "metadata.json")
        expires_at_raw = metadata.get("expires_at")
        if not expires_at_raw:
            raise ValueError(f"Preview asset '{preview_asset_id}' is missing expires_at metadata.")
        return PreviewAssetRecord(
            job_id=metadata.get("job_id", preview_asset_id),
            preview_asset_id=metadata["preview_asset_id"],
            preview_kind=metadata["preview_kind"],
            expires_at=datetime.fromisoformat(expires_at_raw),
            asset_path=asset_dir,
            audio_file_path=asset_dir / "audio.wav",
        )

    def purge_expired_preview_assets(self, *, now: datetime | None = None) -> int:
        now = now or datetime.now(timezone.utc)
        preview_root = self._formal_root / "previews"
        if not preview_root.exists():
            return 0

        removed = 0
        for child in preview_root.iterdir():
            if not child.is_dir():
                continue
            try:
                record = self.get_preview_asset_record(child.name)
            except (FileNotFoundError, ValueError, KeyError):
                continue
            if record.expires_at > now:
                continue
            shutil.rmtree(child, ignore_errors=False)
            removed += 1
        return removed

    def collect_unreferenced_formal_assets(
        self,
        referenced_asset_ids: set[str],
        *,
        dry_run: bool = False,
    ) -> AssetGcReport:
        deleted_asset_paths: list[Path] = []
        kept_asset_paths: list[Path] = []
        if not self._formal_root.exists():
            return AssetGcReport(deleted_asset_paths=deleted_asset_paths, kept_asset_paths=kept_asset_paths)

        for category_root in sorted(path for path in self._formal_root.iterdir() if path.is_dir()):
            if category_root.name == "previews":
                continue
            for asset_path in sorted(path for path in category_root.iterdir() if path.is_dir()):
                relative_key = asset_path.relative_to(self._formal_root).as_posix()
                if relative_key in referenced_asset_ids:
                    kept_asset_paths.append(asset_path)
                    continue
                deleted_asset_paths.append(asset_path)
                if not dry_run:
                    shutil.rmtree(asset_path, ignore_errors=False)

        return AssetGcReport(deleted_asset_paths=deleted_asset_paths, kept_asset_paths=kept_asset_paths)

    def cleanup_orphan_preview_assets(self, referenced_preview_ids: set[str]) -> int:
        preview_root = self._formal_root / "previews"
        if not preview_root.exists():
            return 0

        removed = 0
        for child in preview_root.iterdir():
            if not child.is_dir():
                continue
            if child.name in referenced_preview_ids:
                continue
            shutil.rmtree(child, ignore_errors=False)
            removed += 1
        return removed

    def write_formal_json(self, relative_path: str, payload: dict) -> Path:
        target_path = (self._formal_root / self._validate_relative_path(relative_path)).resolve()
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return target_path

    def write_formal_bytes_atomic(self, relative_path: str, payload: bytes) -> Path:
        target_path = (self._formal_root / self._validate_relative_path(relative_path)).resolve()
        target_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = target_path.with_name(f"{target_path.name}.tmp-{uuid4().hex}")
        temp_path.write_bytes(payload)
        os.replace(temp_path, target_path)
        return target_path

    def write_formal_json_atomic(self, relative_path: str, payload: dict) -> Path:
        return self.write_formal_bytes_atomic(
            relative_path,
            json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8"),
        )

    def resolve_export_target_dir(self, raw_target_dir: str) -> Path:
        raw_path = Path(raw_target_dir)
        if raw_path.is_absolute():
            return raw_path.resolve()
        raise ValueError("Export root directory must be an absolute path.")

    def prepare_export_staging_dir(self, *, export_job_id: str, target_dir: str | Path) -> tuple[Path, Path]:
        resolved_target = self.resolve_export_target_dir(str(target_dir))
        resolved_target.mkdir(parents=True, exist_ok=True)
        staging_dir = resolved_target / f".tmp-export-{self._validate_leaf_name(export_job_id)}"
        if staging_dir.exists():
            self._remove_path(staging_dir)
        staging_dir.mkdir(parents=True, exist_ok=False)
        return resolved_target, staging_dir

    def finalize_export_staging_dir(
        self,
        *,
        staging_dir: str | Path,
        target_dir: str | Path,
        overwrite_policy: str,
    ) -> Path:
        resolved_target = Path(target_dir).resolve()
        resolved_staging = Path(staging_dir)
        if not resolved_staging.exists():
            raise FileNotFoundError(f"Export staging directory not found: {resolved_staging}")
        final_target = self._resolve_export_destination(resolved_target, overwrite_policy=overwrite_policy)
        if overwrite_policy == "replace" and final_target.exists():
            self._remove_path(final_target)
        elif overwrite_policy == "fail" and final_target.exists():
            raise ValueError(f"Export target already exists: {final_target}")
        os.replace(resolved_staging, final_target)
        return final_target

    def finalize_export_file(
        self,
        *,
        staging_file: str | Path,
        target_file: str | Path,
        overwrite_policy: str,
    ) -> Path:
        resolved_staging = Path(staging_file)
        if not resolved_staging.exists():
            raise FileNotFoundError(f"Export staging file not found: {resolved_staging}")
        resolved_target = self._resolve_export_destination(Path(target_file).resolve(), overwrite_policy=overwrite_policy)
        resolved_target.parent.mkdir(parents=True, exist_ok=True)
        if overwrite_policy == "replace" and resolved_target.exists():
            self._remove_path(resolved_target)
        elif overwrite_policy == "fail" and resolved_target.exists():
            raise ValueError(f"Export target already exists: {resolved_target}")
        os.replace(resolved_staging, resolved_target)
        return resolved_target

    def cleanup_export_staging_dir(self, staging_dir: str | Path) -> bool:
        path = Path(staging_dir)
        if not path.exists():
            return False
        self._remove_path(path)
        return True

    def load_segment_asset(self, render_asset_id: str) -> SegmentRenderAssetPayload:
        asset_dir = self.segment_asset_path(render_asset_id)
        metadata = self._read_json(asset_dir / "metadata.json")
        sample_rate, audio = self.load_wav_asset(asset_dir)
        del sample_rate
        left_count = int(metadata["left_margin_sample_count"])
        core_count = int(metadata["core_sample_count"])
        right_count = int(metadata["right_margin_sample_count"])
        if int(audio.size) != left_count + core_count + right_count:
            raise ValueError(f"Segment asset '{render_asset_id}' metadata does not match audio sample count.")
        return SegmentRenderAssetPayload(
            render_asset_id=metadata["render_asset_id"],
            segment_id=metadata["segment_id"],
            render_version=int(metadata["render_version"]),
            semantic_tokens=list(metadata["semantic_tokens"]),
            phone_ids=list(metadata["phone_ids"]),
            decoder_frame_count=int(metadata["decoder_frame_count"]),
            audio_sample_count=int(metadata["audio_sample_count"]),
            left_margin_sample_count=left_count,
            core_sample_count=core_count,
            right_margin_sample_count=right_count,
            left_margin_audio=audio[:left_count],
            core_audio=audio[left_count : left_count + core_count],
            right_margin_audio=audio[left_count + core_count : left_count + core_count + right_count],
            trace=metadata.get("trace"),
        )

    def load_boundary_asset(self, boundary_asset_id: str) -> BoundaryAssetPayload:
        asset_dir = self.boundary_asset_path(boundary_asset_id)
        metadata = self._read_json(asset_dir / "metadata.json")
        sample_rate, audio = self.load_wav_asset(asset_dir)
        del sample_rate
        return BoundaryAssetPayload(
            boundary_asset_id=metadata["boundary_asset_id"],
            left_segment_id=metadata["left_segment_id"],
            left_render_version=int(metadata["left_render_version"]),
            right_segment_id=metadata["right_segment_id"],
            right_render_version=int(metadata["right_render_version"]),
            edge_version=int(metadata["edge_version"]),
            boundary_strategy=metadata["boundary_strategy"],
            boundary_sample_count=int(metadata["boundary_sample_count"]),
            boundary_audio=audio,
            trace=metadata.get("trace"),
        )

    def load_block_asset(self, block_asset_id: str) -> BlockCompositionAssetPayload:
        asset_dir = self.block_asset_path(block_asset_id)
        metadata = self._read_json(asset_dir / "metadata.json")
        sample_rate, audio = self.load_wav_asset(asset_dir)
        segment_entries = [
            SegmentCompositionEntry(
                segment_id=entry["segment_id"],
                audio_sample_span=tuple(entry["audio_sample_span"]),
                order_key=int(entry.get("order_key", 0)),
                render_asset_id=entry.get("render_asset_id"),
            )
            for entry in metadata["segment_entries"]
        ]
        edge_entries = [
            EdgeCompositionEntry(
                edge_id=entry["edge_id"],
                left_segment_id=entry["left_segment_id"],
                right_segment_id=entry["right_segment_id"],
                boundary_strategy=entry["boundary_strategy"],
                effective_boundary_strategy=entry.get("effective_boundary_strategy", entry["boundary_strategy"]),
                pause_duration_seconds=float(entry.get("pause_duration_seconds", 0.0)),
                boundary_sample_span=tuple(entry.get("boundary_sample_span", (0, 0))),
                pause_sample_span=tuple(entry.get("pause_sample_span", (0, 0))),
            )
            for entry in metadata.get("edge_entries", [])
        ]
        marker_entries = [
            BlockMarkerEntry(
                marker_type=entry["marker_type"],
                sample=int(entry["sample"]),
                related_id=entry["related_id"],
            )
            for entry in metadata.get("marker_entries", [])
        ]
        return BlockCompositionAssetPayload(
            block_id=metadata["block_id"],
            block_asset_id=metadata.get("block_asset_id", metadata["block_id"]),
            segment_ids=list(metadata["segment_ids"]),
            sample_rate=sample_rate,
            audio=audio,
            audio_sample_count=int(metadata["audio_sample_count"]),
            segment_entries=segment_entries,
            edge_entries=edge_entries,
            marker_entries=marker_entries,
        )

    def load_timeline_manifest(self, timeline_manifest_id: str) -> TimelineManifest:
        asset_dir = self.timeline_manifest_path(timeline_manifest_id)
        return TimelineManifest.model_validate(self._read_json(asset_dir / "manifest.json"))

    def load_wav_asset(self, asset_path: Path) -> tuple[int, np.ndarray]:
        wav_path = asset_path / "audio.wav"
        if not wav_path.exists():
            raise FileNotFoundError(f"Asset audio file not found: {wav_path}")
        with wave.open(io.BytesIO(wav_path.read_bytes()), "rb") as wav_file:
            sample_rate = wav_file.getframerate()
            frames = wav_file.readframes(wav_file.getnframes())
        audio_int16 = np.frombuffer(frames, dtype=np.int16)
        if audio_int16.size == 0:
            return sample_rate, np.zeros(0, dtype=np.float32)
        return sample_rate, (audio_int16.astype(np.float32) / 32767.0).astype(np.float32, copy=False)

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
    def _read_json(path: Path) -> dict:
        if not path.exists():
            raise FileNotFoundError(f"Asset metadata file not found: {path}")
        return TypeAdapter(dict).validate_json(path.read_text(encoding="utf-8"))

    @staticmethod
    def _remove_path(path: Path) -> None:
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=False)
            return
        path.unlink(missing_ok=False)

    def _resolve_export_destination(self, target_dir: Path, *, overwrite_policy: str) -> Path:
        if overwrite_policy == "new_folder":
            if not target_dir.exists():
                return target_dir
            index = 1
            while True:
                suffix = "".join(target_dir.suffixes)
                base_name = target_dir.name[:-len(suffix)] if suffix else target_dir.name
                candidate = target_dir.with_name(f"{base_name}-{index}{suffix}")
                if not candidate.exists():
                    return candidate
                index += 1
        if overwrite_policy not in {"fail", "replace"}:
            raise ValueError(f"Unsupported overwrite policy: {overwrite_policy}")
        return target_dir

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
