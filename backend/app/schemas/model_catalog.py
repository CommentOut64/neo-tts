from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator


class ModelRecord(BaseModel):
    model_id: str
    model_revision: str
    source: Literal["builtin", "external", "managed"]
    gpt_path_hint: str
    sovits_path_hint: str
    gpt_content_sha256: str = ""
    sovits_content_sha256: str = ""
    version_status: Literal["supported", "unverified", "incompatible", "missing", "stale", "failed"] = "unverified"
    capabilities: tuple[str, ...] = ()
    path_probe: dict[str, str | int] = Field(default_factory=dict)
    created_at: str | None = None
    updated_at: str | None = None


class PresetRecord(BaseModel):
    preset_id: str
    preset_revision: str
    model_id: str
    model_revision: str
    speaker_reference_audio_path: str
    speaker_reference_text: str
    speaker_reference_language: str
    style_reference_audio_path: str | None = None
    style_reference_text: str | None = None
    style_reference_language: str | None = None
    defaults: dict[str, float | int] = Field(default_factory=dict)
    name: str = "default"
    emotion_label: str | None = None

    @model_validator(mode="after")
    def _validate_style_reference(self) -> "PresetRecord":
        values = (self.style_reference_audio_path, self.style_reference_text, self.style_reference_language)
        if any(value is not None for value in values) and not all(values):
            raise ValueError("Style reference requires audio_path, text, and language together.")
        return self


class CatalogTreeItem(BaseModel):
    model: ModelRecord
    presets: list[PresetRecord] = Field(default_factory=list)


class ExternalModelImportRequest(BaseModel):
    model_id: str
    gpt_path: str
    sovits_path: str
    capabilities: tuple[str, ...] = ()


class PresetCreateRequest(BaseModel):
    preset_id: str
    speaker_reference_audio_path: str
    speaker_reference_text: str
    speaker_reference_language: str
    style_reference_audio_path: str | None = None
    style_reference_text: str | None = None
    style_reference_language: str | None = None
    defaults: dict[str, float | int] = Field(default_factory=dict)
    name: str = "default"
    emotion_label: str | None = None

    @model_validator(mode="after")
    def _validate_style_reference(self) -> "PresetCreateRequest":
        values = (self.style_reference_audio_path, self.style_reference_text, self.style_reference_language)
        if any(value is not None for value in values) and not all(values):
            raise ValueError("Style reference requires audio_path, text, and language together.")
        return self


class PresetPatchRequest(BaseModel):
    speaker_reference_audio_path: str | None = None
    speaker_reference_text: str | None = None
    speaker_reference_language: str | None = None
    style_reference_audio_path: str | None = None
    style_reference_text: str | None = None
    style_reference_language: str | None = None
    defaults: dict[str, float | int] | None = None
    name: str | None = None
    emotion_label: str | None = None
