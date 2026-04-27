from __future__ import annotations

from contextlib import contextmanager
import json
from datetime import datetime, timezone
from pathlib import Path
import shutil
import threading
from uuid import uuid4
from typing import Any

from backend.app.core.settings import AppSettings, get_settings
from backend.app.core.path_resolution import resolve_runtime_path
from backend.app.inference.asset_fingerprint import fingerprint_file, fingerprint_text
from backend.app.schemas.voice import VoiceDefaults, VoiceProfile


class VoiceRepository:
    _MANAGED_VOICE_METADATA_FILENAME = "voice.json"
    _MANAGED_VOICE_REFERENCE_FILENAME = "reference.json"
    _MANAGED_WEIGHTS_DIRNAME = "weights"
    _MANAGED_REFERENCES_DIRNAME = "references"
    _REFERENCE_AUDIO_EXTENSIONS = (".wav", ".mp3", ".flac")
    _VOICE_MUTATION_LOCKS_GUARD = threading.Lock()
    _VOICE_MUTATION_LOCKS: dict[tuple[str, str], threading.Lock] = {}

    def __init__(self, config_path: str | Path | None = None, settings: AppSettings | None = None) -> None:
        settings = settings or get_settings()
        self._settings = settings
        raw_path = Path(config_path) if config_path is not None else settings.voices_config_path
        self._config_path = raw_path if raw_path.is_absolute() else settings.project_root / raw_path
        builtin_config_path = settings.builtin_voices_config_path or self._config_path
        self._builtin_config_path = (
            builtin_config_path if builtin_config_path.is_absolute() else settings.project_root / builtin_config_path
        )
        raw_managed_dir = settings.managed_voices_dir
        self._managed_voices_dir = (
            raw_managed_dir if raw_managed_dir.is_absolute() else settings.project_root / raw_managed_dir
        )

    def list_voices(self) -> list[dict[str, Any]]:
        data = self._load()
        voices: list[dict[str, Any]] = []
        for name, config in data.items():
            voices.append(self._build_entry(name=name, config=config))
        return voices

    def get_voice(self, voice_name: str) -> dict[str, Any]:
        data = self._load()
        if voice_name not in data:
            raise LookupError(f"Voice '{voice_name}' not found.")
        return self._build_entry(name=voice_name, config=data[voice_name])

    def reload(self) -> list[dict[str, Any]]:
        return self.list_voices()

    def create_uploaded_voice(
        self,
        *,
        name: str,
        description: str,
        copy_weights_into_project: bool = True,
        ref_text: str,
        ref_lang: str,
        defaults: VoiceDefaults,
        gpt_external_path: str | None = None,
        sovits_external_path: str | None = None,
        gpt_filename: str | None = None,
        gpt_bytes: bytes | None = None,
        sovits_filename: str | None = None,
        sovits_bytes: bytes | None = None,
        ref_audio_filename: str,
        ref_audio_bytes: bytes,
    ) -> dict[str, Any]:
        normalized_name = self._normalize_voice_name(name)
        with self._voice_mutation_guard(normalized_name):
            configured_data = self._load_config_only()
            if normalized_name in configured_data:
                raise ValueError(f"Voice '{normalized_name}' already exists.")

            target_dir = self._managed_voices_dir / normalized_name
            if target_dir.exists():
                self._remove_orphaned_managed_directory(target_dir, voice_name=normalized_name)

            data = self._load()
            target_dir.mkdir(parents=True, exist_ok=False)
            try:
                if copy_weights_into_project:
                    if gpt_filename is None or gpt_bytes is None or sovits_filename is None or sovits_bytes is None:
                        raise ValueError("Managed voice creation requires uploaded weight files.")
                    weights_dir = self._managed_voice_weights_dir(target_dir)
                    gpt_path = self._to_relative_path(
                        self._write_binary_file(weights_dir / Path(gpt_filename).name, gpt_bytes),
                    )
                    sovits_path = self._to_relative_path(
                        self._write_binary_file(weights_dir / Path(sovits_filename).name, sovits_bytes),
                    )
                    weight_storage_mode = "managed"
                else:
                    gpt_path = self._validate_external_weight_path(
                        raw_path=gpt_external_path,
                        expected_suffix=".ckpt",
                        field_name="gpt_external_path",
                    )
                    sovits_path = self._validate_external_weight_path(
                        raw_path=sovits_external_path,
                        expected_suffix=".pth",
                        field_name="sovits_external_path",
                    )
                    weight_storage_mode = "external"
                ref_audio_path = self._resolve_project_path(
                    self._write_reference_audio_file(
                        target_dir=target_dir,
                        filename=ref_audio_filename,
                        payload=ref_audio_bytes,
                    )
                )

                timestamp = self._now_isoformat()
                profile = VoiceProfile(
                    name=normalized_name,
                    gpt_path=gpt_path,
                    sovits_path=sovits_path,
                    weight_storage_mode=weight_storage_mode,
                    gpt_fingerprint=fingerprint_file(self._resolve_project_path(gpt_path)),
                    sovits_fingerprint=fingerprint_file(self._resolve_project_path(sovits_path)),
                    ref_audio=self._to_relative_path(ref_audio_path),
                    ref_text=ref_text,
                    ref_lang=ref_lang,
                    description=description,
                    defaults=defaults,
                    managed=True,
                    created_at=timestamp,
                    updated_at=timestamp,
                )
                self._write_managed_voice_metadata(profile=profile, target_dir=target_dir)
                self._write_managed_voice_reference_sidecar(profile=profile, target_dir=target_dir)
                data[normalized_name] = profile.model_dump(exclude={"name"})
                self._write(data)
                return profile.model_dump()
            except Exception:
                if target_dir.exists() and self._is_managed_file(target_dir):
                    shutil.rmtree(target_dir)
                raise

    def update_managed_voice(
        self,
        *,
        voice_name: str,
        description: str | None = None,
        copy_weights_into_project: bool | None = None,
        ref_text: str | None = None,
        ref_lang: str | None = None,
        gpt_external_path: str | None = None,
        sovits_external_path: str | None = None,
        gpt_filename: str | None = None,
        gpt_bytes: bytes | None = None,
        sovits_filename: str | None = None,
        sovits_bytes: bytes | None = None,
        ref_audio_filename: str | None = None,
        ref_audio_bytes: bytes | None = None,
    ) -> dict[str, Any]:
        with self._voice_mutation_guard(voice_name):
            target_dir = self._managed_voices_dir / voice_name
            metadata_path = self._managed_voice_metadata_path(target_dir)
            reference_sidecar_path = self._managed_voice_reference_path(target_dir)
            previous_metadata_content = self._read_text_file_if_exists(metadata_path)
            previous_reference_sidecar_content = self._read_text_file_if_exists(reference_sidecar_path)

            data = self._load()
            if voice_name not in data:
                raise LookupError(f"Voice '{voice_name}' not found.")

            existing = VoiceProfile.model_validate(self._build_entry(name=voice_name, config=data[voice_name]))
            if not existing.managed:
                raise ValueError(f"Voice '{voice_name}' is not managed and cannot be edited.")

            target_dir.mkdir(parents=True, exist_ok=True)

            gpt_path = existing.gpt_path
            sovits_path = existing.sovits_path
            weight_storage_mode = existing.weight_storage_mode
            should_replace_managed_weights = (
                copy_weights_into_project is True
                or (
                    copy_weights_into_project is None
                    and gpt_filename is not None
                    and gpt_bytes is not None
                    and sovits_filename is not None
                    and sovits_bytes is not None
                )
            )

            if copy_weights_into_project is False:
                gpt_path = self._validate_external_weight_path(
                    raw_path=gpt_external_path,
                    expected_suffix=".ckpt",
                    field_name="gpt_external_path",
                )
                sovits_path = self._validate_external_weight_path(
                    raw_path=sovits_external_path,
                    expected_suffix=".pth",
                    field_name="sovits_external_path",
                )
                weight_storage_mode = "external"
            elif should_replace_managed_weights:
                if gpt_filename is None or gpt_bytes is None or sovits_filename is None or sovits_bytes is None:
                    raise ValueError("Managed voice update requires uploaded weight files.")
                weights_dir = self._managed_voice_weights_dir(target_dir)
                gpt_path = self._replace_managed_file(
                    target_dir=weights_dir,
                    current_path=existing.gpt_path,
                    filename=gpt_filename,
                    payload=gpt_bytes,
                    allowed_extensions={".ckpt"},
                )
                sovits_path = self._replace_managed_file(
                    target_dir=weights_dir,
                    current_path=existing.sovits_path,
                    filename=sovits_filename,
                    payload=sovits_bytes,
                    allowed_extensions={".pth"},
                )
                weight_storage_mode = "managed"

            ref_audio_path = existing.ref_audio
            staged_reference_audio_path: str | None = None
            if ref_audio_filename is not None and ref_audio_bytes is not None:
                staged_reference_audio_path = self._write_reference_audio_file(
                    target_dir=target_dir,
                    filename=ref_audio_filename,
                    payload=ref_audio_bytes,
                )
                ref_audio_path = staged_reference_audio_path

            updated = existing.model_copy(
                update={
                    "gpt_path": gpt_path,
                    "sovits_path": sovits_path,
                    "weight_storage_mode": weight_storage_mode,
                    "gpt_fingerprint": fingerprint_file(self._resolve_project_path(gpt_path)),
                    "sovits_fingerprint": fingerprint_file(self._resolve_project_path(sovits_path)),
                    "ref_audio": ref_audio_path,
                    "description": description if description is not None else existing.description,
                    "ref_text": ref_text if ref_text is not None else existing.ref_text,
                    "ref_lang": ref_lang if ref_lang is not None else existing.ref_lang,
                    "updated_at": self._now_isoformat(),
                },
            )
            try:
                self._write_managed_voice_metadata(profile=updated, target_dir=target_dir)
                self._write_managed_voice_reference_sidecar(profile=updated, target_dir=target_dir)
                data[voice_name] = updated.model_dump(exclude={"name"})
                self._write(data)
            except Exception:
                if staged_reference_audio_path is not None and staged_reference_audio_path != existing.ref_audio:
                    self._remove_managed_file_if_exists(staged_reference_audio_path)
                    self._cleanup_empty_directories(self._managed_voice_references_dir(target_dir))
                self._restore_text_file(metadata_path, previous_metadata_content)
                self._restore_text_file(reference_sidecar_path, previous_reference_sidecar_content)
                raise
            if staged_reference_audio_path is not None and staged_reference_audio_path != existing.ref_audio:
                self._remove_managed_file_if_exists(existing.ref_audio)
                self._cleanup_empty_directories(self._managed_voice_references_dir(target_dir))
            return updated.model_dump()

    def delete_voice(self, voice_name: str) -> None:
        with self._voice_mutation_guard(voice_name):
            data = self._load()
            if voice_name not in data:
                raise LookupError(f"Voice '{voice_name}' not found.")

            profile = VoiceProfile.model_validate(self._build_entry(name=voice_name, config=data[voice_name]))
            del data[voice_name]
            self._write(data)

            if profile.managed:
                managed_weight_paths = (profile.gpt_path, profile.sovits_path) if profile.weight_storage_mode == "managed" else ()
                for raw_path in (*managed_weight_paths, profile.ref_audio):
                    resolved_path = self._resolve_project_path(raw_path)
                    if resolved_path.exists() and self._is_managed_file(resolved_path):
                        resolved_path.unlink()
                metadata_path = self._managed_voice_metadata_path(self._managed_voices_dir / voice_name)
                if metadata_path.exists() and self._is_managed_file(metadata_path):
                    metadata_path.unlink()
                reference_path = self._managed_voice_reference_path(self._managed_voices_dir / voice_name)
                if reference_path.exists() and self._is_managed_file(reference_path):
                    reference_path.unlink()
                self._cleanup_empty_directories(self._managed_voices_dir / voice_name)

    def _load(self) -> dict[str, dict[str, Any]]:
        data = self._load_config_only()
        self._sync_managed_voice_sidecars_from_config(data)
        recovered = self._discover_managed_voice_configs(existing_names=set(data))
        if recovered:
            merged = dict(data)
            merged.update(recovered)
            self._write(merged)
            return merged
        return data

    def _load_config_only(self) -> dict[str, dict[str, Any]]:
        data: dict[str, dict[str, Any]] = {}
        builtin_data = self._read_config_file(self._builtin_config_path)
        if builtin_data:
            data.update(builtin_data)
        user_data = self._read_config_file(self._config_path)
        if user_data:
            data.update(user_data)
        return data

    def _write(self, data: dict[str, dict[str, Any]]) -> None:
        payload = data
        if self._config_path != self._builtin_config_path:
            payload = {
                name: config
                for name, config in data.items()
                if config.get("managed")
            }
        self._config_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self._config_path.with_suffix(f"{self._config_path.suffix}.tmp")
        tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp_path.replace(self._config_path)

    def _build_entry(self, *, name: str, config: dict[str, Any]) -> dict[str, Any]:
        entry = dict(config)
        entry["name"] = name
        entry.setdefault("managed", False)
        entry.setdefault("weight_storage_mode", "managed" if entry["managed"] else "external")
        if not entry.get("gpt_fingerprint") and isinstance(entry.get("gpt_path"), str):
            entry["gpt_fingerprint"] = self._safe_fingerprint_file(entry["gpt_path"])
        else:
            entry.setdefault("gpt_fingerprint", "")
        if not entry.get("sovits_fingerprint") and isinstance(entry.get("sovits_path"), str):
            entry["sovits_fingerprint"] = self._safe_fingerprint_file(entry["sovits_path"])
        else:
            entry.setdefault("sovits_fingerprint", "")
        if self._settings.distribution_kind != "development":
            entry = self._normalize_product_entry(entry)
        return entry

    def _discover_managed_voice_configs(self, *, existing_names: set[str]) -> dict[str, dict[str, Any]]:
        if not self._managed_voices_dir.exists():
            return {}

        recovered: dict[str, dict[str, Any]] = {}
        for directory in sorted(self._managed_voices_dir.iterdir(), key=lambda item: item.name):
            if not directory.is_dir() or directory.name.startswith("_"):
                continue
            voice_name = directory.name
            if voice_name in existing_names:
                continue
            config = self._recover_managed_voice_config(directory=directory, voice_name=voice_name)
            if config is not None:
                recovered[voice_name] = config
        return recovered

    def _recover_managed_voice_config(self, *, directory: Path, voice_name: str) -> dict[str, Any] | None:
        reference_payload = self._read_managed_voice_reference_sidecar(directory)
        metadata_path = self._managed_voice_metadata_path(directory)
        if metadata_path.exists():
            payload = json.loads(metadata_path.read_text(encoding="utf-8"))
            weight_storage_mode = payload.get("weight_storage_mode") or "managed"
            ref_audio_value = payload.get("ref_audio") or reference_payload.get("ref_audio")
            if not ref_audio_value:
                ref_audio_path = self._find_reference_audio_file(directory=directory)
                if ref_audio_path is None:
                    return None
                ref_audio_value = self._to_relative_path(ref_audio_path)

            if weight_storage_mode == "external":
                gpt_path = payload.get("gpt_path")
                sovits_path = payload.get("sovits_path")
                if not gpt_path or not sovits_path:
                    return None
                profile = VoiceProfile(
                    name=voice_name,
                    gpt_path=gpt_path,
                    sovits_path=sovits_path,
                    weight_storage_mode="external",
                    gpt_fingerprint=payload.get("gpt_fingerprint") or self._safe_fingerprint_file(gpt_path),
                    sovits_fingerprint=payload.get("sovits_fingerprint") or self._safe_fingerprint_file(sovits_path),
                    ref_audio=ref_audio_value,
                    ref_text=payload.get("ref_text") or reference_payload.get("ref_text", ""),
                    ref_lang=payload.get("ref_lang") or reference_payload.get("ref_lang", "zh"),
                    description=payload.get("description", ""),
                    defaults=VoiceDefaults.model_validate(payload.get("defaults", {})),
                    managed=True,
                    created_at=payload.get("created_at"),
                    updated_at=payload.get("updated_at"),
                )
                return profile.model_dump(exclude={"name"})

            gpt_path = payload.get("gpt_path")
            sovits_path = payload.get("sovits_path")
            if not gpt_path:
                resolved_gpt_path = self._find_single_file(directory=directory, suffix=".ckpt")
                if resolved_gpt_path is None:
                    return None
                gpt_path = self._to_relative_path(resolved_gpt_path)
            if not sovits_path:
                resolved_sovits_path = self._find_single_file(directory=directory, suffix=".pth")
                if resolved_sovits_path is None:
                    return None
                sovits_path = self._to_relative_path(resolved_sovits_path)
            profile = VoiceProfile(
                name=voice_name,
                gpt_path=gpt_path,
                sovits_path=sovits_path,
                weight_storage_mode=weight_storage_mode,
                gpt_fingerprint=payload.get("gpt_fingerprint") or self._safe_fingerprint_file(gpt_path),
                sovits_fingerprint=payload.get("sovits_fingerprint") or self._safe_fingerprint_file(sovits_path),
                ref_audio=ref_audio_value,
                ref_text=payload.get("ref_text") or reference_payload.get("ref_text", ""),
                ref_lang=payload.get("ref_lang") or reference_payload.get("ref_lang", "zh"),
                description=payload.get("description", ""),
                defaults=VoiceDefaults.model_validate(payload.get("defaults", {})),
                managed=True,
                created_at=payload.get("created_at"),
                updated_at=payload.get("updated_at"),
            )
            return profile.model_dump(exclude={"name"})

        gpt_path = self._find_single_file(directory=directory, suffix=".ckpt")
        sovits_path = self._find_single_file(directory=directory, suffix=".pth")
        ref_audio_path = self._find_reference_audio_file(directory=directory)
        if gpt_path is None or sovits_path is None or ref_audio_path is None:
            return None

        return VoiceProfile(
            name=voice_name,
            gpt_path=self._to_relative_path(gpt_path),
            sovits_path=self._to_relative_path(sovits_path),
            weight_storage_mode="managed",
            gpt_fingerprint=fingerprint_file(gpt_path),
            sovits_fingerprint=fingerprint_file(sovits_path),
            ref_audio=self._to_relative_path(ref_audio_path),
            ref_text=reference_payload.get("ref_text", ""),
            ref_lang=reference_payload.get("ref_lang", "zh"),
            description="",
            defaults=VoiceDefaults(),
            managed=True,
        ).model_dump(exclude={"name"})

    def _write_managed_voice_metadata(self, *, profile: VoiceProfile, target_dir: Path) -> None:
        metadata_path = self._managed_voice_metadata_path(target_dir)
        metadata_path.write_text(
            json.dumps(profile.model_dump(exclude={"name"}), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _write_managed_voice_reference_sidecar(self, *, profile: VoiceProfile, target_dir: Path) -> None:
        reference_path = self._managed_voice_reference_path(target_dir)
        reference_path.write_text(
            json.dumps(
                {
                    "reference_asset_id": self._extract_reference_asset_id(profile.ref_audio),
                    "ref_audio": profile.ref_audio,
                    "ref_audio_fingerprint": fingerprint_file(self._resolve_project_path(profile.ref_audio)),
                    "ref_text": profile.ref_text,
                    "ref_text_fingerprint": fingerprint_text(profile.ref_text),
                    "ref_lang": profile.ref_lang,
                    "updated_at": profile.updated_at or profile.created_at or self._now_isoformat(),
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    def _managed_voice_metadata_path(self, directory: Path) -> Path:
        return directory / self._MANAGED_VOICE_METADATA_FILENAME

    def _managed_voice_reference_path(self, directory: Path) -> Path:
        return directory / self._MANAGED_VOICE_REFERENCE_FILENAME

    def _read_managed_voice_reference_sidecar(self, directory: Path) -> dict[str, Any]:
        reference_path = self._managed_voice_reference_path(directory)
        if not reference_path.exists():
            return {}
        return json.loads(reference_path.read_text(encoding="utf-8"))

    def _sync_managed_voice_sidecars_from_config(self, data: dict[str, dict[str, Any]]) -> None:
        for voice_name, config in data.items():
            if not config.get("managed"):
                continue

            target_dir = self._managed_voices_dir / voice_name
            if not target_dir.exists() or not target_dir.is_dir():
                continue

            profile = VoiceProfile.model_validate(self._build_entry(name=voice_name, config=config))
            self._write_managed_voice_metadata(profile=profile, target_dir=target_dir)
            self._write_managed_voice_reference_sidecar(profile=profile, target_dir=target_dir)

    def _find_single_file(self, *, directory: Path, suffix: str) -> Path | None:
        search_dir = self._managed_voice_weights_dir(directory)
        if search_dir.exists():
            matches = sorted(path for path in search_dir.iterdir() if path.is_file() and path.suffix.lower() == suffix)
        else:
            matches = sorted(path for path in directory.iterdir() if path.is_file() and path.suffix.lower() == suffix)
        if len(matches) != 1:
            return None
        return matches[0]

    def _find_reference_audio_file(self, *, directory: Path) -> Path | None:
        search_dir = self._managed_voice_references_dir(directory)
        if search_dir.exists():
            matches = sorted(
                path
                for path in search_dir.iterdir()
                if path.is_file() and path.suffix.lower() in self._REFERENCE_AUDIO_EXTENSIONS
            )
        else:
            matches = sorted(
                path
                for path in directory.iterdir()
                if path.is_file() and path.suffix.lower() in self._REFERENCE_AUDIO_EXTENSIONS
            )
        if len(matches) != 1:
            return None
        return matches[0]

    def _remove_orphaned_managed_directory(self, target_dir: Path, *, voice_name: str) -> None:
        if not self._is_managed_file(target_dir):
            raise ValueError(f"Voice storage for '{voice_name}' already exists.")
        shutil.rmtree(target_dir)

    def _write_binary_file(self, target_path: Path, payload: bytes) -> Path:
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_bytes(payload)
        return target_path

    def _write_reference_audio_file(
        self,
        *,
        target_dir: Path,
        filename: str,
        payload: bytes,
        current_path: str | None = None,
    ) -> str:
        references_dir = self._managed_voice_references_dir(target_dir)
        suffix = Path(filename).suffix.lower() or ".wav"
        reference_asset_id = uuid4().hex
        target_path = references_dir / f"ref-{reference_asset_id}{suffix}"
        written_path = self._write_binary_file(target_path, payload)
        return self._to_relative_path(written_path)

    def _replace_managed_file(
        self,
        *,
        target_dir: Path,
        current_path: str,
        filename: str,
        payload: bytes,
        allowed_extensions: set[str],
    ) -> str:
        target_dir.mkdir(parents=True, exist_ok=True)
        target_path = target_dir / Path(filename).name
        current_resolved = self._resolve_project_path(current_path)
        for path in list(target_dir.iterdir()):
            if not path.is_file() or path.suffix.lower() not in allowed_extensions:
                continue
            if path == target_path:
                continue
            path.unlink()
        if current_resolved.exists() and self._is_managed_file(current_resolved) and current_resolved != target_path:
            current_resolved.unlink(missing_ok=True)
        written_path = self._write_binary_file(target_path, payload)
        return self._to_relative_path(written_path)

    def _to_relative_path(self, path: Path) -> str:
        for base in (
            self._settings.user_data_root,
            self._settings.resources_root,
            self._settings.project_root,
        ):
            if base is None:
                continue
            try:
                return path.relative_to(base).as_posix()
            except ValueError:
                continue
        return path.resolve().as_posix()

    def _resolve_project_path(self, raw_path: str | Path) -> Path:
        candidate = Path(raw_path).expanduser()
        if self._settings.distribution_kind != "development":
            return self._resolve_packaged_relative_path(
                candidate,
                is_managed=_is_managed_relative_path(candidate),
            )
        return resolve_runtime_path(
            raw_path,
            project_root=self._settings.project_root,
            user_data_root=self._settings.user_data_root,
            resources_root=self._settings.resources_root,
            managed_voices_dir=self._managed_voices_dir,
        )

    def _validate_external_weight_path(self, *, raw_path: str | None, expected_suffix: str, field_name: str) -> str:
        if raw_path is None or not raw_path.strip():
            raise ValueError(f"{field_name} is required.")

        path = Path(raw_path)
        if not path.is_absolute():
            raise ValueError(f"{field_name} must be an absolute path.")
        if path.suffix.lower() != expected_suffix:
            raise ValueError(f"{field_name} must use {expected_suffix}.")
        if not path.exists() or not path.is_file():
            raise ValueError(f"{field_name} does not exist.")
        return path.resolve().as_posix()

    def _safe_fingerprint_file(self, raw_path: str | Path) -> str:
        resolved_path = self._resolve_project_path(raw_path)
        try:
            return fingerprint_file(resolved_path)
        except FileNotFoundError:
            return fingerprint_text(str(resolved_path.resolve()))

    def _remove_managed_file_if_exists(self, raw_path: str | Path) -> None:
        resolved_path = self._resolve_project_path(raw_path)
        if resolved_path.exists() and self._is_managed_file(resolved_path):
            resolved_path.unlink(missing_ok=True)

    @staticmethod
    def _read_text_file_if_exists(path: Path) -> str | None:
        if not path.exists():
            return None
        return path.read_text(encoding="utf-8")

    @staticmethod
    def _restore_text_file(path: Path, content: str | None) -> None:
        if content is None:
            path.unlink(missing_ok=True)
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def _managed_voice_weights_dir(self, target_dir: Path) -> Path:
        return target_dir / self._MANAGED_WEIGHTS_DIRNAME

    def _managed_voice_references_dir(self, target_dir: Path) -> Path:
        return target_dir / self._MANAGED_REFERENCES_DIRNAME

    @staticmethod
    def _extract_reference_asset_id(ref_audio_path: str) -> str:
        stem = Path(ref_audio_path).stem
        if stem.startswith("ref-"):
            return stem.removeprefix("ref-")
        return stem

    @contextmanager
    def _voice_mutation_guard(self, voice_name: str):
        managed_root = str(self._managed_voices_dir.resolve()).lower()
        lock_key = (managed_root, voice_name)
        with self._VOICE_MUTATION_LOCKS_GUARD:
            voice_lock = self._VOICE_MUTATION_LOCKS.setdefault(lock_key, threading.Lock())
        with voice_lock:
            yield


    def _read_config_file(self, config_path: Path) -> dict[str, dict[str, Any]]:
        if not config_path.exists():
            return {}
        with config_path.open("r", encoding="utf-8") as file:
            return json.load(file)

    def _normalize_product_entry(self, entry: dict[str, Any]) -> dict[str, Any]:
        normalized = dict(entry)
        is_managed = bool(normalized.get("managed"))
        for field_name in ("gpt_path", "sovits_path", "ref_audio"):
            raw_value = normalized.get(field_name)
            if not isinstance(raw_value, str):
                continue
            candidate = Path(raw_value)
            if candidate.is_absolute():
                normalized[field_name] = str(candidate.resolve())
                continue
            normalized[field_name] = str(
                self._resolve_packaged_relative_path(candidate, is_managed=is_managed)
            )
        return normalized

    def _resolve_packaged_relative_path(self, raw_path: Path, *, is_managed: bool) -> Path:
        if raw_path.is_absolute():
            return raw_path.resolve()

        if is_managed:
            base_dir = self._settings.user_data_root
        else:
            normalized = raw_path.as_posix()
            if normalized == "models" or normalized.startswith("models/"):
                base_dir = self._settings.models_root
            elif normalized == "pretrained_models" or normalized.startswith("pretrained_models/"):
                base_dir = self._settings.pretrained_models_root
            else:
                base_dir = self._settings.app_core_root or self._settings.resources_root

        if base_dir is None:
            return raw_path.resolve()
        return (base_dir / raw_path).resolve()

    def _is_managed_file(self, path: Path) -> bool:
        try:
            path.resolve().relative_to(self._managed_voices_dir.resolve())
            return True
        except ValueError:
            return False

    def _cleanup_empty_directories(self, directory: Path) -> None:
        current = directory
        managed_root = self._managed_voices_dir.resolve()
        while current.exists():
            try:
                current.resolve().relative_to(managed_root)
            except ValueError:
                break
            if any(current.iterdir()):
                break
            current.rmdir()
            if current.resolve() == managed_root:
                break
            current = current.parent

    @staticmethod
    def _now_isoformat() -> str:
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    @staticmethod
    def _normalize_voice_name(name: str) -> str:
        normalized = name.strip()
        if not normalized:
            raise ValueError("Voice name must not be empty.")
        if normalized in {".", ".."} or any(separator in normalized for separator in ("/", "\\")):
            raise ValueError("Voice name must not contain path separators.")
        return normalized


def _is_managed_relative_path(path_value: Path) -> bool:
    normalized = path_value.as_posix()
    return normalized == "managed_voices" or normalized.startswith("managed_voices/")
