from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.app.core.settings import AppSettings, get_settings
from backend.app.schemas.voice import VoiceDefaults, VoiceProfile


class VoiceRepository:
    def __init__(self, config_path: str | Path | None = None, settings: AppSettings | None = None) -> None:
        settings = settings or get_settings()
        self._settings = settings
        raw_path = Path(config_path) if config_path is not None else settings.voices_config_path
        self._config_path = raw_path if raw_path.is_absolute() else settings.project_root / raw_path
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
        data = self._load()
        if normalized_name in data:
            raise ValueError(f"Voice '{normalized_name}' already exists.")

        target_dir = self._managed_voices_dir / normalized_name
        if target_dir.exists():
            raise ValueError(f"Voice storage for '{normalized_name}' already exists.")

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
        data[normalized_name] = profile.model_dump(exclude={"name"})
        self._write(data)
        return profile.model_dump()

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
            self._cleanup_empty_directories(self._managed_voices_dir / voice_name)

    def _load(self) -> dict[str, dict[str, Any]]:
        if not self._config_path.exists():
            return {}
        with self._config_path.open("r", encoding="utf-8") as file:
            return json.load(file)

    def _write(self, data: dict[str, dict[str, Any]]) -> None:
        self._config_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self._config_path.with_suffix(f"{self._config_path.suffix}.tmp")
        tmp_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp_path.replace(self._config_path)

    def _build_entry(self, *, name: str, config: dict[str, Any]) -> dict[str, Any]:
        entry = dict(config)
        entry["name"] = name
        entry.setdefault("managed", False)
        return entry

    def _write_binary_file(self, target_path: Path, payload: bytes) -> Path:
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_bytes(payload)
        return target_path

    def _to_relative_path(self, path: Path) -> str:
        try:
            return path.relative_to(self._settings.project_root).as_posix()
        except ValueError:
            return path.resolve().as_posix()

    def _resolve_project_path(self, raw_path: str | Path) -> Path:
        path = Path(raw_path)
        if not path.is_absolute():
            path = self._settings.project_root / path
        return path

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
