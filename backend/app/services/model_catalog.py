from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from uuid import uuid4

from backend.app.schemas.model_catalog import (
    CatalogTreeItem,
    ExternalModelImportRequest,
    ModelRecord,
    PresetCreateRequest,
    PresetRecord,
    PresetPatchRequest,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class ModelCatalogService:
    """Atomic JSON model/preset catalog. Runtime never imports this service."""

    SCHEMA_VERSION = 1

    def __init__(self, *, user_data_root: Path, builtin_voices: list[dict] | None = None) -> None:
        self._root = user_data_root.resolve() / "models"
        self._manifest = self._root / "catalog.json"
        self._lock = RLock()
        self._ensure_manifest()
        if builtin_voices:
            self._project_legacy_voices(builtin_voices)

    def list_tree(self) -> list[CatalogTreeItem]:
        with self._lock:
            data = self._read()
            models = [ModelRecord.model_validate(item) for item in data["models"]]
            presets = [PresetRecord.model_validate(self._normalize_preset(item)) for item in data["presets"]]
            return [CatalogTreeItem(model=model, presets=[p for p in presets if p.model_id == model.model_id]) for model in models]

    def get_model(self, model_id: str) -> ModelRecord:
        for item in self.list_tree():
            if item.model.model_id == model_id:
                return item.model
        raise LookupError(f"Model '{model_id}' not found.")

    def list_presets(self, model_id: str) -> list[PresetRecord]:
        for item in self.list_tree():
            if item.model.model_id == model_id:
                return item.presets
        raise LookupError(f"Model '{model_id}' not found.")

    def resolve(self, *, model_id: str, model_revision: str = "", preset_id: str | None = None, preset_revision: str = "") -> tuple[ModelRecord, PresetRecord]:
        model = self.get_model(model_id)
        if model_revision and model.model_revision != model_revision:
            raise ValueError("Requested model_revision does not match the catalog model.")
        if model.version_status in {"failed", "incompatible", "missing", "stale"}:
            raise ValueError("Requested model is read-only degraded and cannot render.")
        presets = self.list_presets(model_id)
        selected_id = preset_id or f"{model_id}:default"
        preset = next((item for item in presets if item.preset_id == selected_id), None)
        if preset is None:
            raise LookupError(f"Preset '{selected_id}' not found for model '{model_id}'.")
        if preset.model_revision != model.model_revision:
            raise ValueError("Preset does not belong to the requested model revision.")
        if preset_revision and preset.preset_revision != preset_revision:
            raise ValueError("Requested preset_revision does not match the catalog preset.")
        return model, preset

    def import_external(self, request: ExternalModelImportRequest) -> ModelRecord:
        gpt = Path(request.gpt_path).expanduser()
        sovits = Path(request.sovits_path).expanduser()
        if not gpt.is_absolute() or not sovits.is_absolute():
            raise ValueError("External model paths must be absolute.")
        return self._register_model(request.model_id, "external", gpt, sovits, request.capabilities)

    def register_builtin(self, *, model_id: str, gpt_path: Path, sovits_path: Path, capabilities: tuple[str, ...] = ()) -> ModelRecord:
        return self._register_model(model_id, "builtin", gpt_path.resolve(), sovits_path.resolve(), capabilities)

    def import_managed(self, *, model_id: str, gpt_name: str, gpt_bytes: bytes, sovits_name: str, sovits_bytes: bytes) -> ModelRecord:
        if Path(gpt_name).suffix.lower() != ".ckpt" or Path(sovits_name).suffix.lower() != ".pth":
            raise ValueError("GPT must use .ckpt and SoVITS must use .pth.")
        if not gpt_bytes or not sovits_bytes:
            raise ValueError("Both uploaded checkpoint files must be non-empty.")
        target = self._root / model_id
        if target.exists():
            raise ValueError(f"Managed model '{model_id}' already exists.")
        target.mkdir(parents=True)
        try:
            gpt = self._atomic_bytes(target, "gpt.ckpt", gpt_bytes)
            sovits = self._atomic_bytes(target, "sovits.pth", sovits_bytes)
            return self._register_model(model_id, "managed", gpt, sovits, ())
        except BaseException:
            for path in target.glob("*"):
                path.unlink(missing_ok=True)
            target.rmdir()
            raise

    def create_preset(self, model_id: str, request: PresetCreateRequest) -> PresetRecord:
        model = self.get_model(model_id)
        preset = PresetRecord(
            preset_id=request.preset_id,
            preset_revision=uuid4().hex,
            model_id=model.model_id,
            model_revision=model.model_revision,
            speaker_reference_audio_path=request.speaker_reference_audio_path,
            speaker_reference_text=request.speaker_reference_text,
            speaker_reference_language=request.speaker_reference_language,
            style_reference_audio_path=request.style_reference_audio_path,
            style_reference_text=request.style_reference_text,
            style_reference_language=request.style_reference_language,
            defaults=request.defaults,
            name=request.name,
            emotion_label=request.emotion_label,
        )
        with self._lock:
            data = self._read()
            if any(item["preset_id"] == preset.preset_id for item in data["presets"]):
                raise ValueError(f"Preset '{preset.preset_id}' already exists.")
            data["presets"].append(preset.model_dump(mode="json"))
            self._write(data)
        return preset

    def delete_model(self, model_id: str, *, retire=None) -> bool:
        with self._lock:
            data = self._read()
            model = next((m for m in data["models"] if m["model_id"] == model_id), None)
            if model is None:
                raise LookupError(f"Model '{model_id}' not found.")
            data["models"] = [m for m in data["models"] if m["model_id"] != model_id]
            data["presets"] = [p for p in data["presets"] if p["model_id"] != model_id]
            self._write(data)
        def remove_managed_copy() -> None:
            if model["source"] != "managed":
                return
            target = self._root / model_id
            if target.is_dir():
                for path in target.iterdir():
                    if path.is_file():
                        path.unlink()
                target.rmdir()

        if callable(retire):
            return bool(retire(
                gpt_fingerprint=model["gpt_content_sha256"],
                sovits_fingerprint=model["sovits_content_sha256"],
                on_retired=remove_managed_copy,
            ))
        remove_managed_copy()
        return False

    def delete_preset(self, model_id: str, preset_id: str) -> None:
        with self._lock:
            data = self._read()
            matched = next((p for p in data["presets"] if p["model_id"] == model_id and p["preset_id"] == preset_id), None)
            if matched is None:
                raise LookupError(f"Preset '{preset_id}' not found for model '{model_id}'.")
            data["presets"].remove(matched)
            self._write(data)

    def update_preset(self, model_id: str, preset_id: str, request: PresetPatchRequest) -> PresetRecord:
        with self._lock:
            data = self._read()
            matched = next(
                (item for item in data["presets"] if item["model_id"] == model_id and item["preset_id"] == preset_id),
                None,
            )
            if matched is None:
                raise LookupError(f"Preset '{preset_id}' not found for model '{model_id}'.")
            changes = request.model_dump(exclude_unset=True)
            matched.update(changes)
            matched["preset_revision"] = uuid4().hex
            updated = PresetRecord.model_validate(self._normalize_preset(matched))
            self._write(data)
            return updated

    def mark_runtime_failure(self, model_id: str, model_revision: str, error_code: str) -> None:
        """Persist only deterministic model failures; transient runtime errors stay request-local."""
        deterministic = {
            "CHECKPOINT_CORRUPTED", "CHECKPOINT_KEY_MISSING", "CHECKPOINT_SHAPE_MISMATCH",
            "MODEL_INCOMPATIBLE", "NAN_OR_INF_OUTPUT",
        }
        if error_code not in deterministic:
            return
        with self._lock:
            data = self._read()
            for model in data["models"]:
                if model["model_id"] == model_id and model["model_revision"] == model_revision:
                    model["version_status"] = "incompatible" if error_code == "MODEL_INCOMPATIBLE" else "failed"
                    model["updated_at"] = _now()
                    self._write(data)
                    return

    def _register_model(self, model_id: str, source: str, gpt: Path, sovits: Path, capabilities: tuple[str, ...]) -> ModelRecord:
        if not gpt.is_file() or not sovits.is_file():
            raise FileNotFoundError("Both GPT and SoVITS checkpoint files are required.")
        if gpt.suffix.lower() != ".ckpt" or sovits.suffix.lower() != ".pth":
            raise ValueError("GPT must use .ckpt and SoVITS must use .pth.")
        capabilities = tuple(sorted(set(capabilities) | set(self._static_validate(gpt, sovits))))
        gpt_hash, sovits_hash = _sha256(gpt), _sha256(sovits)
        revision = f"{gpt_hash}:{sovits_hash}"
        now = _now()
        record = ModelRecord(
            model_id=model_id,
            model_revision=revision,
            source=source,
            gpt_path_hint=str(gpt),
            sovits_path_hint=str(sovits),
            gpt_content_sha256=gpt_hash,
            sovits_content_sha256=sovits_hash,
            version_status="supported",
            capabilities=capabilities,
            created_at=now,
            updated_at=now,
            path_probe={
                "gpt_size": gpt.stat().st_size,
                "gpt_mtime_ns": gpt.stat().st_mtime_ns,
                "sovits_size": sovits.stat().st_size,
                "sovits_mtime_ns": sovits.stat().st_mtime_ns,
            },
        )
        with self._lock:
            data = self._read()
            existing = next((m for m in data["models"] if m["model_id"] == model_id), None)
            if existing is not None:
                # A logical model id is immutable.  A different content revision must
                # be imported under a new id so the old identity/presets remain intact.
                if existing.get("model_revision") != revision:
                    raise ValueError(
                        f"Model '{model_id}' already refers to a different content revision; "
                        "choose a new model_id."
                    )
                # Same content can be relocated; update only path/probe/source hints.
                existing.update(record.model_dump(mode="json"))
            else:
                data["models"].append(record.model_dump(mode="json"))
            self._write(data)
        return ModelRecord.model_validate(existing) if existing is not None else record

    @staticmethod
    def _static_validate(gpt_path: Path, sovits_path: Path) -> tuple[str, ...]:
        """Validate checkpoint structure without assembling models or synthesizing audio."""
        try:
            from runtime.gsv.loader import _as_namespace, _load_checkpoint, _resolve_sovits_version

            gpt, _ = _load_checkpoint(str(gpt_path), checkpoint="catalog.gpt.deserialize")
            sovits, header = _load_checkpoint(str(sovits_path), checkpoint="catalog.sovits.deserialize")
            if not isinstance(gpt, dict) or not isinstance(gpt.get("weight"), dict) or not isinstance(gpt.get("config"), dict):
                raise ValueError("CHECKPOINT_KEY_MISSING: GPT checkpoint must contain config and weight mappings.")
            if not isinstance(sovits, dict) or not isinstance(sovits.get("weight"), dict) or sovits.get("config") is None:
                raise ValueError("CHECKPOINT_KEY_MISSING: SoVITS checkpoint must contain config and weight mappings.")
            hps = _as_namespace(sovits["config"])
            if not all(hasattr(hps, field) for field in ("model", "data", "train")):
                raise ValueError("CHECKPOINT_KEY_MISSING: SoVITS checkpoint configuration is incomplete.")
            version = _resolve_sovits_version(hps, sovits["weight"], header)
            return (f"sovits_{version}",)
        except ValueError:
            raise
        except Exception as exc:
            code = getattr(getattr(exc, "info", None), "error_code", None)
            if code in {"CHECKPOINT_CORRUPTED", "CHECKPOINT_KEY_MISSING", "CHECKPOINT_SHAPE_MISMATCH", "MODEL_INCOMPATIBLE"}:
                raise ValueError(f"{code}: static checkpoint validation failed.") from exc
            raise ValueError(f"CHECKPOINT_CORRUPTED: static checkpoint validation failed: {type(exc).__name__}") from exc

    def _project_legacy_voices(self, voices: list[dict]) -> None:
        for voice in voices:
            model_id = str(voice.get("name", "")).strip()
            if not model_id:
                continue
            try:
                self.get_model(model_id)
                # Legacy projection is additive only. Never overwrite a user/external
                # catalog entry that happens to use the same voice id.
                continue
            except LookupError:
                pass
            try:
                self._register_model(model_id, "builtin", Path(voice["gpt_path"]).resolve(), Path(voice["sovits_path"]).resolve(), ())
                self.create_preset(model_id, PresetCreateRequest(
                    preset_id=f"{model_id}:default",
                    speaker_reference_audio_path=str(voice.get("ref_audio", "")),
                    speaker_reference_text=str(voice.get("ref_text", "")),
                    speaker_reference_language=str(voice.get("ref_lang", "zh")),
                    defaults=voice.get("defaults", {}), name="default",
                ))
            except (KeyError, FileNotFoundError):
                continue

    def _ensure_manifest(self) -> None:
        self._root.mkdir(parents=True, exist_ok=True)
        if not self._manifest.exists():
            self._write({"schema_version": self.SCHEMA_VERSION, "models": [], "presets": []})

    def _read(self) -> dict:
        try:
            payload = json.loads(self._manifest.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            payload = {"schema_version": self.SCHEMA_VERSION, "models": [], "presets": []}
        if payload.get("schema_version") != self.SCHEMA_VERSION:
            raise ValueError("Unsupported model catalog schema version.")
        return payload

    @staticmethod
    def _normalize_preset(raw: dict) -> dict:
        """Read pre-reference-contract manifests without making them selectable."""
        item = dict(raw)
        legacy_speaker = item.pop("speaker_reference", None)
        legacy_style = item.pop("style_reference", None)
        if legacy_speaker is not None:
            item.setdefault("speaker_reference_audio_path", legacy_speaker)
            item.setdefault("speaker_reference_text", "")
            item.setdefault("speaker_reference_language", "")
        if legacy_style is not None:
            item.setdefault("style_reference_audio_path", legacy_style)
            item.setdefault("style_reference_text", "")
            item.setdefault("style_reference_language", "")
        return item

    def _write(self, payload: dict) -> None:
        fd, name = tempfile.mkstemp(prefix="catalog.", suffix=".tmp", dir=self._root)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(name, self._manifest)
        finally:
            try:
                Path(name).unlink()
            except FileNotFoundError:
                pass

    @staticmethod
    def _atomic_bytes(directory: Path, filename: str, content: bytes) -> Path:
        fd, name = tempfile.mkstemp(prefix=f"{filename}.", suffix=".tmp", dir=directory)
        destination = directory / filename
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(name, destination)
        finally:
            Path(name).unlink(missing_ok=True)
        return destination
