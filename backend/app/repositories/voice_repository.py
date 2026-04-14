from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
import shutil
from typing import Any

from backend.app.core.settings import AppSettings, get_settings
from backend.app.schemas.voice import VoiceDefaults, VoiceProfile


class VoiceRepository:
    _MANAGED_VOICE_METADATA_FILENAME = "voice.json"
    _MANAGED_VOICE_REFERENCE_FILENAME = "reference.json"
    _REFERENCE_AUDIO_EXTENSIONS = (".wav", ".mp3", ".flac")

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
        ref_text: str,
        ref_lang: str,
        defaults: VoiceDefaults,
        gpt_filename: str,
        gpt_bytes: bytes,
        sovits_filename: str,
        sovits_bytes: bytes,
        ref_audio_filename: str,
        ref_audio_bytes: bytes,
    ) -> dict[str, Any]:
        normalized_name = self._normalize_voice_name(name)
        configured_data = self._load_config_only()
        if normalized_name in configured_data:
            raise ValueError(f"Voice '{normalized_name}' already exists.")

        target_dir = self._managed_voices_dir / normalized_name
        if target_dir.exists():
            self._remove_orphaned_managed_directory(target_dir, voice_name=normalized_name)

        data = self._load()
        target_dir.mkdir(parents=True, exist_ok=False)
        gpt_path = self._write_binary_file(target_dir / Path(gpt_filename).name, gpt_bytes)
        sovits_path = self._write_binary_file(target_dir / Path(sovits_filename).name, sovits_bytes)
        ref_audio_path = self._write_binary_file(target_dir / Path(ref_audio_filename).name, ref_audio_bytes)

        timestamp = self._now_isoformat()
        profile = VoiceProfile(
            name=normalized_name,
            gpt_path=self._to_relative_path(gpt_path),
            sovits_path=self._to_relative_path(sovits_path),
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

    def update_managed_voice(
        self,
        *,
        voice_name: str,
        description: str | None = None,
        ref_text: str | None = None,
        ref_lang: str | None = None,
        gpt_filename: str | None = None,
        gpt_bytes: bytes | None = None,
        sovits_filename: str | None = None,
        sovits_bytes: bytes | None = None,
        ref_audio_filename: str | None = None,
        ref_audio_bytes: bytes | None = None,
    ) -> dict[str, Any]:
        data = self._load()
        if voice_name not in data:
            raise LookupError(f"Voice '{voice_name}' not found.")

        existing = VoiceProfile.model_validate(self._build_entry(name=voice_name, config=data[voice_name]))
        if not existing.managed:
            raise ValueError(f"Voice '{voice_name}' is not managed and cannot be edited.")

        target_dir = self._managed_voices_dir / voice_name
        target_dir.mkdir(parents=True, exist_ok=True)

        gpt_path = existing.gpt_path
        if gpt_filename is not None and gpt_bytes is not None:
            gpt_path = self._replace_managed_file(
                target_dir=target_dir,
                current_path=existing.gpt_path,
                filename=gpt_filename,
                payload=gpt_bytes,
                allowed_extensions={".ckpt"},
            )

        sovits_path = existing.sovits_path
        if sovits_filename is not None and sovits_bytes is not None:
            sovits_path = self._replace_managed_file(
                target_dir=target_dir,
                current_path=existing.sovits_path,
                filename=sovits_filename,
                payload=sovits_bytes,
                allowed_extensions={".pth"},
            )

        ref_audio_path = existing.ref_audio
        if ref_audio_filename is not None and ref_audio_bytes is not None:
            ref_audio_path = self._replace_managed_file(
                target_dir=target_dir,
                current_path=existing.ref_audio,
                filename=ref_audio_filename,
                payload=ref_audio_bytes,
                allowed_extensions=set(self._REFERENCE_AUDIO_EXTENSIONS),
            )

        updated = existing.model_copy(
            update={
                "gpt_path": gpt_path,
                "sovits_path": sovits_path,
                "ref_audio": ref_audio_path,
                "description": description if description is not None else existing.description,
                "ref_text": ref_text if ref_text is not None else existing.ref_text,
                "ref_lang": ref_lang if ref_lang is not None else existing.ref_lang,
                "updated_at": self._now_isoformat(),
            },
        )
        self._write_managed_voice_metadata(profile=updated, target_dir=target_dir)
        self._write_managed_voice_reference_sidecar(profile=updated, target_dir=target_dir)
        data[voice_name] = updated.model_dump(exclude={"name"})
        self._write(data)
        return updated.model_dump()

    def delete_voice(self, voice_name: str) -> None:
        data = self._load()
        if voice_name not in data:
            raise LookupError(f"Voice '{voice_name}' not found.")

        profile = VoiceProfile.model_validate(self._build_entry(name=voice_name, config=data[voice_name]))
        del data[voice_name]
        self._write(data)

        if profile.managed:
            for raw_path in (profile.gpt_path, profile.sovits_path, profile.ref_audio):
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
        gpt_path = self._find_single_file(directory=directory, suffix=".ckpt")
        sovits_path = self._find_single_file(directory=directory, suffix=".pth")
        ref_audio_path = self._find_reference_audio_file(directory=directory)
        if gpt_path is None or sovits_path is None or ref_audio_path is None:
            return None

        reference_payload = self._read_managed_voice_reference_sidecar(directory)
        metadata_path = self._managed_voice_metadata_path(directory)
        if metadata_path.exists():
            payload = json.loads(metadata_path.read_text(encoding="utf-8"))
            profile = VoiceProfile(
                name=voice_name,
                gpt_path=payload.get("gpt_path") or self._to_relative_path(gpt_path),
                sovits_path=payload.get("sovits_path") or self._to_relative_path(sovits_path),
                ref_audio=payload.get("ref_audio") or self._to_relative_path(ref_audio_path),
                ref_text=payload.get("ref_text") or reference_payload.get("ref_text", ""),
                ref_lang=payload.get("ref_lang") or reference_payload.get("ref_lang", "zh"),
                description=payload.get("description", ""),
                defaults=VoiceDefaults.model_validate(payload.get("defaults", {})),
                managed=True,
                created_at=payload.get("created_at"),
                updated_at=payload.get("updated_at"),
            )
            return profile.model_dump(exclude={"name"})

        return VoiceProfile(
            name=voice_name,
            gpt_path=self._to_relative_path(gpt_path),
            sovits_path=self._to_relative_path(sovits_path),
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
                    "ref_text": profile.ref_text,
                    "ref_lang": profile.ref_lang,
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
        matches = sorted(path for path in directory.iterdir() if path.is_file() and path.suffix.lower() == suffix)
        if len(matches) != 1:
            return None
        return matches[0]

    def _find_reference_audio_file(self, *, directory: Path) -> Path | None:
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

    def _replace_managed_file(
        self,
        *,
        target_dir: Path,
        current_path: str,
        filename: str,
        payload: bytes,
        allowed_extensions: set[str],
    ) -> str:
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
        path = Path(raw_path)
        if not path.is_absolute():
            path = self._settings.project_root / path
        return path

    def _read_config_file(self, config_path: Path) -> dict[str, dict[str, Any]]:
        if not config_path.exists():
            return {}
        with config_path.open("r", encoding="utf-8") as file:
            return json.load(file)

    def _normalize_product_entry(self, entry: dict[str, Any]) -> dict[str, Any]:
        normalized = dict(entry)
        is_managed = bool(normalized.get("managed"))
        base_dir = self._settings.user_data_root if is_managed else self._settings.resources_root
        for field_name in ("gpt_path", "sovits_path", "ref_audio"):
            raw_value = normalized.get(field_name)
            if not isinstance(raw_value, str):
                continue
            candidate = Path(raw_value)
            if candidate.is_absolute() or base_dir is None:
                normalized[field_name] = str(candidate)
                continue
            normalized[field_name] = str((base_dir / candidate).resolve())
        return normalized

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
