from __future__ import annotations

from typing import Any, Mapping

from backend.app.schemas.edit_session import BindingReference
from backend.app.schemas.edit_session import ReferenceBindingOverride


def build_binding_key(
    *,
    voice_id: str | None = None,
    model_key: str | None = None,
    binding_ref: BindingReference | Mapping[str, Any] | None = None,
) -> str:
    if binding_ref is not None:
        if isinstance(binding_ref, BindingReference):
            normalized_binding_ref = binding_ref.model_dump(mode="json")
        else:
            normalized_binding_ref = dict(binding_ref)
        return ":".join(
            [
                str(normalized_binding_ref.get("workspace_id") or ""),
                str(normalized_binding_ref.get("main_model_id") or ""),
                str(normalized_binding_ref.get("submodel_id") or ""),
                str(normalized_binding_ref.get("preset_id") or ""),
            ]
        )
    return f"{voice_id}:{model_key}"


def merge_reference_override(
    *,
    preset_reference: Mapping[str, Any] | None = None,
    override: ReferenceBindingOverride | Mapping[str, Any] | None,
) -> dict[str, str]:
    if isinstance(override, Mapping):
        override_payload = dict(override)
    elif override is not None:
        override_payload = override.model_dump(mode="json")
    else:
        override_payload = {}

    if preset_reference is not None:
        preset_reference_payload = dict(preset_reference)
        fallback_audio_path = str(preset_reference_payload.get("reference_audio_path") or "")
        fallback_text = str(preset_reference_payload.get("reference_text") or "")
        fallback_language = str(preset_reference_payload.get("reference_language") or "")
    else:
        fallback_audio_path = ""
        fallback_text = ""
        fallback_language = ""

    return {
        "reference_audio_path": _pick_reference_value(
            override_payload.get("reference_audio_path"),
            fallback_audio_path,
        ),
        "reference_text": _pick_reference_value(
            override_payload.get("reference_text"),
            fallback_text,
        ),
        "reference_language": _pick_reference_value(
            override_payload.get("reference_language"),
            fallback_language,
        ),
    }


def migrate_legacy_render_profile_payload(
    payload: Mapping[str, Any],
    *,
    binding_key: str,
) -> dict[str, Any]:
    migrated = dict(payload)
    overrides_by_binding = migrated.get("reference_overrides_by_binding")
    normalized_overrides = dict(overrides_by_binding) if isinstance(overrides_by_binding, Mapping) else {}
    extra_overrides = migrated.get("extra_overrides")
    normalized_extra_overrides = dict(extra_overrides) if isinstance(extra_overrides, Mapping) else {}
    legacy_override = {
        "reference_audio_path": payload.get("reference_audio_path"),
        "reference_text": payload.get("reference_text"),
        "reference_language": payload.get("reference_language"),
    }
    if any(_has_reference_value(value) for value in legacy_override.values()):
        current_entry = normalized_overrides.get(binding_key)
        entry_payload = dict(current_entry) if isinstance(current_entry, Mapping) else {}
        for field_name, field_value in legacy_override.items():
            if _has_reference_value(field_value):
                entry_payload[field_name] = field_value
        normalized_overrides[binding_key] = entry_payload
        normalized_extra_overrides["legacy_reference_binding_fallback"] = True

    migrated["reference_overrides_by_binding"] = normalized_overrides
    migrated["extra_overrides"] = normalized_extra_overrides
    migrated.pop("reference_audio_path", None)
    migrated.pop("reference_text", None)
    migrated.pop("reference_language", None)
    return migrated


def _pick_reference_value(candidate: Any, fallback: str) -> str:
    if isinstance(candidate, str) and candidate.strip():
        return candidate
    return fallback


def _has_reference_value(value: Any) -> bool:
    return value is not None and value != ""
