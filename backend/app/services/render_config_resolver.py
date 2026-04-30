from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Literal

from backend.app.core.exceptions import EditSessionNotFoundError
from backend.app.inference.block_adapter_registry import AdapterRegistry
from backend.app.inference.block_adapter_types import ResolvedModelBinding
from backend.app.inference.asset_fingerprint import fingerprint_file, fingerprint_text
from backend.app.inference.editable_types import fingerprint_inference_config
from backend.app.schemas.edit_session import (
    DocumentSnapshot,
    EditableEdge,
    EditableSegment,
    ReferenceBindingOverride,
    RenderProfile,
    VoiceBinding,
)
from backend.app.services.reference_binding import build_binding_key, merge_reference_override
from backend.app.services.session_reference_asset_service import SessionReferenceAsset
from backend.app.tts_registry.model_registry import ModelRegistry
from backend.app.tts_registry.secret_store import SecretStore
from backend.app.tts_registry.types import ModelInstance, ModelPreset


@dataclass(frozen=True)
class ResolvedSegmentConfig:
    segment: EditableSegment
    render_profile: RenderProfile
    voice_binding: VoiceBinding
    render_context_fingerprint: str
    model_cache_key: str
    resolved_model_binding: ResolvedModelBinding | None = None
    resolved_reference: "ResolvedReferenceSelection | None" = None

    @property
    def render_profile_fingerprint(self) -> str:
        return self.render_context_fingerprint


@dataclass(frozen=True)
class ResolvedReferenceSelection:
    binding_key: str
    source: Literal["preset", "custom"]
    reference_scope: str
    reference_identity: str
    reference_audio_path: str
    reference_audio_fingerprint: str
    reference_text: str
    reference_text_fingerprint: str
    reference_language: str


@dataclass(frozen=True)
class ResolvedEdgeConfig:
    edge: EditableEdge
    left_binding: VoiceBinding
    right_binding: VoiceBinding
    effective_boundary_strategy: str


class RenderConfigResolver:
    def __init__(
        self,
        *,
        voice_service: object | None = None,
        model_registry: ModelRegistry | None = None,
        adapter_registry: AdapterRegistry | None = None,
        secret_store: SecretStore | None = None,
    ) -> None:
        self._voice_service = voice_service
        self._model_registry = model_registry
        self._adapter_registry = adapter_registry
        self._secret_store = secret_store

    def resolve_segment(self, *, snapshot: DocumentSnapshot, segment_id: str) -> ResolvedSegmentConfig:
        segment = next((item for item in snapshot.segments if item.segment_id == segment_id), None)
        if segment is None:
            raise EditSessionNotFoundError(f"Segment '{segment_id}' not found.")

        render_profile = self._resolve_render_profile(snapshot=snapshot, segment=segment)
        voice_binding = self._resolve_voice_binding(snapshot=snapshot, segment=segment)
        resolved_reference = self._resolve_reference_selection(
            render_profile=render_profile,
            voice_binding=voice_binding,
        )
        effective_render_profile = self._apply_effective_reference(
            render_profile=render_profile,
            resolved_reference=resolved_reference,
        )
        resolved_model_binding = self._resolve_model_binding(
            voice_binding=voice_binding,
            render_profile=effective_render_profile,
            resolved_reference=resolved_reference,
        )
        fingerprint_payload = json.dumps(
            {
                "speed": effective_render_profile.speed,
                "top_k": effective_render_profile.top_k,
                "top_p": effective_render_profile.top_p,
                "temperature": effective_render_profile.temperature,
                "noise_scale": effective_render_profile.noise_scale,
                "reference_audio_path": effective_render_profile.reference_audio_path or "",
                "reference_text": effective_render_profile.reference_text or "",
                "reference_language": effective_render_profile.reference_language or "",
                "reference_scope": resolved_reference.reference_scope if resolved_reference is not None else "",
                "reference_identity": resolved_reference.reference_identity if resolved_reference is not None else "",
                "reference_audio_fingerprint": (
                    resolved_reference.reference_audio_fingerprint if resolved_reference is not None else ""
                ),
                "reference_text_fingerprint": (
                    resolved_reference.reference_text_fingerprint if resolved_reference is not None else ""
                ),
            },
            ensure_ascii=True,
            sort_keys=True,
        )
        render_context_fingerprint = hashlib.sha1(fingerprint_payload.encode("utf-8")).hexdigest()
        model_cache_key = (
            resolved_model_binding.binding_fingerprint
            if resolved_model_binding is not None
            else build_binding_key(
                voice_id=voice_binding.voice_id,
                model_key=voice_binding.model_key,
            )
        )
        return ResolvedSegmentConfig(
            segment=segment,
            render_profile=effective_render_profile,
            voice_binding=voice_binding,
            render_context_fingerprint=render_context_fingerprint,
            model_cache_key=model_cache_key,
            resolved_model_binding=resolved_model_binding,
            resolved_reference=resolved_reference,
        )

    def resolve_edge(self, *, snapshot: DocumentSnapshot, edge_id: str) -> ResolvedEdgeConfig:
        edge = next((item for item in snapshot.edges if item.edge_id == edge_id), None)
        if edge is None:
            raise EditSessionNotFoundError(f"Edge '{edge_id}' not found.")

        left = self.resolve_segment(snapshot=snapshot, segment_id=edge.left_segment_id)
        right = self.resolve_segment(snapshot=snapshot, segment_id=edge.right_segment_id)
        return ResolvedEdgeConfig(
            edge=edge,
            left_binding=left.voice_binding,
            right_binding=right.voice_binding,
            effective_boundary_strategy=self.resolve_boundary_strategy(
                left_binding=left.voice_binding,
                right_binding=right.voice_binding,
                requested_strategy=edge.boundary_strategy,
            ),
        )

    def _resolve_render_profile(self, *, snapshot: DocumentSnapshot, segment: EditableSegment) -> RenderProfile:
        profile_id = snapshot.default_render_profile_id
        if segment.group_id is not None:
            group = next((item for item in snapshot.groups if item.group_id == segment.group_id), None)
            if group is None:
                raise EditSessionNotFoundError(f"Segment group '{segment.group_id}' not found.")
            if group.render_profile_id is not None:
                profile_id = group.render_profile_id
        if segment.render_profile_id is not None:
            profile_id = segment.render_profile_id
        if profile_id is None:
            raise EditSessionNotFoundError("Default render profile not found.")
        return self._get_render_profile(snapshot=snapshot, render_profile_id=profile_id)

    def _resolve_voice_binding(self, *, snapshot: DocumentSnapshot, segment: EditableSegment) -> VoiceBinding:
        binding_id = snapshot.default_voice_binding_id
        if segment.group_id is not None:
            group = next((item for item in snapshot.groups if item.group_id == segment.group_id), None)
            if group is None:
                raise EditSessionNotFoundError(f"Segment group '{segment.group_id}' not found.")
            if group.voice_binding_id is not None:
                binding_id = group.voice_binding_id
        if segment.voice_binding_id is not None:
            binding_id = segment.voice_binding_id
        if binding_id is None:
            raise EditSessionNotFoundError("Default voice binding not found.")
        return self._get_voice_binding(snapshot=snapshot, voice_binding_id=binding_id)

    @staticmethod
    def resolve_boundary_strategy(
        *,
        left_binding: VoiceBinding,
        right_binding: VoiceBinding,
        requested_strategy: str,
    ) -> str:
        if left_binding.voice_id != right_binding.voice_id:
            return "crossfade_only"
        if left_binding.model_key != right_binding.model_key:
            return "crossfade_only"
        return requested_strategy

    @staticmethod
    def _get_render_profile(*, snapshot: DocumentSnapshot, render_profile_id: str) -> RenderProfile:
        profile = next((item for item in snapshot.render_profiles if item.render_profile_id == render_profile_id), None)
        if profile is None:
            raise EditSessionNotFoundError(f"Render profile '{render_profile_id}' not found.")
        return profile

    @staticmethod
    def _get_voice_binding(*, snapshot: DocumentSnapshot, voice_binding_id: str) -> VoiceBinding:
        binding = next((item for item in snapshot.voice_bindings if item.voice_binding_id == voice_binding_id), None)
        if binding is None:
            raise EditSessionNotFoundError(f"Voice binding '{voice_binding_id}' not found.")
        return binding

    def _resolve_reference_selection(
        self,
        *,
        render_profile: RenderProfile,
        voice_binding: VoiceBinding,
    ) -> ResolvedReferenceSelection | None:
        binding_key = build_binding_key(
            voice_id=voice_binding.voice_id,
            model_key=voice_binding.model_key,
        )
        override = render_profile.reference_overrides_by_binding.get(binding_key)
        legacy_override = self._build_legacy_reference_override(render_profile)
        active_override = override or legacy_override or self._resolve_legacy_binding_fallback(render_profile)
        session_reference_asset = self._resolve_session_reference_asset(active_override)

        if self._voice_service is None:
            if active_override is None:
                return None
            payload = self._build_effective_override_payload(
                active_override=active_override,
                session_reference_asset=session_reference_asset,
            )
            return ResolvedReferenceSelection(
                binding_key=binding_key,
                source="custom",
                reference_scope="session_override",
                reference_identity=self._build_session_reference_identity(
                    binding_key=binding_key,
                    session_reference_asset=session_reference_asset,
                ),
                reference_audio_path=payload.get("reference_audio_path") or "",
                reference_audio_fingerprint=self._resolve_reference_audio_fingerprint(
                    payload.get("reference_audio_path") or "",
                    session_reference_asset=session_reference_asset,
                ),
                reference_text=payload.get("reference_text") or "",
                reference_text_fingerprint=fingerprint_text(payload.get("reference_text") or ""),
                reference_language=payload.get("reference_language") or "",
            )

        try:
            if hasattr(self._voice_service, "get_voice_profile"):
                preset_voice = self._voice_service.get_voice_profile(voice_binding.voice_id)
            elif hasattr(self._voice_service, "get_voice"):
                preset_voice = self._voice_service.get_voice(voice_binding.voice_id)
            else:
                if active_override is None:
                    return None
                payload = self._build_effective_override_payload(
                    active_override=active_override,
                    session_reference_asset=session_reference_asset,
                )
                return ResolvedReferenceSelection(
                    binding_key=binding_key,
                    source="custom",
                    reference_scope="session_override",
                    reference_identity=self._build_session_reference_identity(
                        binding_key=binding_key,
                        session_reference_asset=session_reference_asset,
                    ),
                    reference_audio_path=payload.get("reference_audio_path") or "",
                    reference_audio_fingerprint=self._resolve_reference_audio_fingerprint(
                        payload.get("reference_audio_path") or "",
                        session_reference_asset=session_reference_asset,
                    ),
                    reference_text=payload.get("reference_text") or "",
                    reference_text_fingerprint=fingerprint_text(payload.get("reference_text") or ""),
                    reference_language=payload.get("reference_language") or "",
                )
        except Exception:
            if active_override is None:
                return None
            payload = self._build_effective_override_payload(
                active_override=active_override,
                session_reference_asset=session_reference_asset,
            )
            return ResolvedReferenceSelection(
                binding_key=binding_key,
                source="custom",
                reference_scope="session_override",
                reference_identity=self._build_session_reference_identity(
                    binding_key=binding_key,
                    session_reference_asset=session_reference_asset,
                ),
                reference_audio_path=payload.get("reference_audio_path") or "",
                reference_audio_fingerprint=self._resolve_reference_audio_fingerprint(
                    payload.get("reference_audio_path") or "",
                    session_reference_asset=session_reference_asset,
                ),
                reference_text=payload.get("reference_text") or "",
                reference_text_fingerprint=fingerprint_text(payload.get("reference_text") or ""),
                reference_language=payload.get("reference_language") or "",
            )
        merged_reference = merge_reference_override(
            preset_voice=preset_voice,
            override=self._build_effective_override_payload(
                active_override=active_override,
                session_reference_asset=session_reference_asset,
            )
            if active_override is not None
            else None,
        )
        reference_scope = "session_override" if active_override is not None else "voice_preset"
        reference_identity = (
            self._build_session_reference_identity(
                binding_key=binding_key,
                session_reference_asset=session_reference_asset,
            )
            if active_override is not None
            else f"{voice_binding.voice_id}:preset"
        )
        return ResolvedReferenceSelection(
            binding_key=binding_key,
            source="custom" if active_override is not None else "preset",
            reference_scope=reference_scope,
            reference_identity=reference_identity,
            reference_audio_path=merged_reference["reference_audio_path"],
            reference_audio_fingerprint=self._safe_fingerprint_file(merged_reference["reference_audio_path"]),
            reference_text=merged_reference["reference_text"],
            reference_text_fingerprint=fingerprint_text(merged_reference["reference_text"]),
            reference_language=merged_reference["reference_language"],
        )

    def _resolve_session_reference_asset(
        self,
        override: ReferenceBindingOverride | None,
    ) -> SessionReferenceAsset | None:
        if (
            override is None
            or not override.session_reference_asset_id
            or self._voice_service is None
            or not hasattr(self._voice_service, "get_session_reference_asset")
        ):
            return None
        return self._voice_service.get_session_reference_asset(override.session_reference_asset_id)

    @staticmethod
    def _build_effective_override_payload(
        *,
        active_override: ReferenceBindingOverride,
        session_reference_asset: SessionReferenceAsset | None,
    ) -> dict[str, str | None]:
        payload = active_override.model_dump(mode="json")
        if session_reference_asset is None:
            return payload
        payload["reference_audio_path"] = session_reference_asset.audio_path
        if not RenderConfigResolver._has_value(payload.get("reference_text")) and session_reference_asset.reference_text:
            payload["reference_text"] = session_reference_asset.reference_text
        if (
            not RenderConfigResolver._has_value(payload.get("reference_language"))
            and session_reference_asset.reference_language
        ):
            payload["reference_language"] = session_reference_asset.reference_language
        return payload

    @staticmethod
    def _build_session_reference_identity(
        *,
        binding_key: str,
        session_reference_asset: SessionReferenceAsset | None,
    ) -> str:
        if session_reference_asset is None:
            return binding_key
        return f"{session_reference_asset.session_id}:{session_reference_asset.reference_asset_id}"

    @staticmethod
    def _resolve_reference_audio_fingerprint(
        raw_path: str,
        *,
        session_reference_asset: SessionReferenceAsset | None,
    ) -> str:
        if session_reference_asset is not None:
            return session_reference_asset.audio_fingerprint
        return RenderConfigResolver._safe_fingerprint_file(raw_path)

    @staticmethod
    def _has_value(value: object) -> bool:
        return isinstance(value, str) and bool(value.strip())

    @staticmethod
    def _apply_effective_reference(
        *,
        render_profile: RenderProfile,
        resolved_reference: ResolvedReferenceSelection | None,
    ) -> RenderProfile:
        if resolved_reference is None:
            return render_profile
        return render_profile.model_copy(
            update={
                "reference_audio_path": resolved_reference.reference_audio_path,
                "reference_text": resolved_reference.reference_text,
                "reference_language": resolved_reference.reference_language,
            }
        )

    @staticmethod
    def _build_legacy_reference_override(render_profile: RenderProfile) -> ReferenceBindingOverride | None:
        if (
            render_profile.reference_audio_path is None
            and render_profile.reference_text is None
            and render_profile.reference_language is None
        ):
            return None
        return ReferenceBindingOverride(
            reference_audio_path=render_profile.reference_audio_path,
            reference_text=render_profile.reference_text,
            reference_language=render_profile.reference_language,
        )

    @staticmethod
    def _resolve_legacy_binding_fallback(render_profile: RenderProfile) -> ReferenceBindingOverride | None:
        if not render_profile.extra_overrides.get("legacy_reference_binding_fallback"):
            return None
        if len(render_profile.reference_overrides_by_binding) != 1:
            return None
        return next(iter(render_profile.reference_overrides_by_binding.values()))

    @staticmethod
    def _safe_fingerprint_file(raw_path: str) -> str:
        if not raw_path:
            return ""
        try:
            return fingerprint_file(raw_path)
        except FileNotFoundError:
            return ""

    def _resolve_model_binding(
        self,
        *,
        voice_binding: VoiceBinding,
        render_profile: RenderProfile,
        resolved_reference: ResolvedReferenceSelection | None,
    ) -> ResolvedModelBinding | None:
        if (
            self._model_registry is None
            and self._adapter_registry is None
            and self._secret_store is None
        ):
            return None

        if self._model_registry is None:
            return None

        seed = self._resolve_model_binding_seed(voice_binding)
        if seed is None:
            raise AdapterRegistry.build_model_required_error()

        model_instance = self._model_registry.get_model(seed["model_instance_id"])
        if model_instance is None:
            raise AdapterRegistry.build_model_required_error()

        preset = next((item for item in model_instance.presets if item.preset_id == seed["preset_id"]), None)
        if preset is None:
            raise AdapterRegistry.build_model_required_error(adapter_id=model_instance.adapter_id)

        if self._adapter_registry is not None:
            self._adapter_registry.require(model_instance.adapter_id)

        resolved_reference_payload = self._build_resolved_reference_payload(
            resolved_reference=resolved_reference,
            preset=preset,
            voice_binding=voice_binding,
        )
        resolved_parameters = {
            "speed": render_profile.speed,
            "top_k": render_profile.top_k,
            "top_p": render_profile.top_p,
            "temperature": render_profile.temperature,
            "noise_scale": render_profile.noise_scale,
        }
        resolved_assets = dict(model_instance.instance_assets)
        resolved_assets.update(preset.preset_assets)
        secret_handles = self._resolve_secret_handles(model_instance)
        binding_fingerprint = fingerprint_inference_config(
            {
                "adapter_id": model_instance.adapter_id,
                "model_instance_id": model_instance.model_instance_id,
                "preset_id": preset.preset_id,
                "resolved_assets": resolved_assets,
                "resolved_reference": resolved_reference_payload,
                "resolved_parameters": resolved_parameters,
                "secret_handles": secret_handles,
            }
        )
        return ResolvedModelBinding(
            adapter_id=model_instance.adapter_id,
            model_instance_id=model_instance.model_instance_id,
            preset_id=preset.preset_id,
            resolved_assets=resolved_assets,
            resolved_reference=resolved_reference_payload,
            resolved_parameters=resolved_parameters,
            secret_handles=secret_handles,
            binding_fingerprint=binding_fingerprint,
        )

    def _resolve_model_binding_seed(self, voice_binding: VoiceBinding) -> dict[str, str] | None:
        if voice_binding.model_instance_id and voice_binding.preset_id:
            return {
                "model_instance_id": voice_binding.model_instance_id,
                "preset_id": voice_binding.preset_id,
            }

        projected_profile = self._resolve_projected_voice_profile(voice_binding.voice_id)
        if (
            projected_profile is None
            or not getattr(projected_profile, "model_instance_id", None)
            or not getattr(projected_profile, "preset_id", None)
        ):
            return None
        return {
            "model_instance_id": str(projected_profile.model_instance_id),
            "preset_id": str(projected_profile.preset_id),
        }

    def _resolve_projected_voice_profile(self, voice_id: str):
        if self._voice_service is None:
            return None
        try:
            if hasattr(self._voice_service, "get_voice_profile"):
                return self._voice_service.get_voice_profile(voice_id)
            if hasattr(self._voice_service, "get_voice"):
                return self._voice_service.get_voice(voice_id)
        except Exception:
            return None
        return None

    @staticmethod
    def _build_resolved_reference_payload(
        *,
        resolved_reference: ResolvedReferenceSelection | None,
        preset: ModelPreset,
        voice_binding: VoiceBinding,
    ) -> dict[str, str]:
        if resolved_reference is None:
            return {
                "reference_id": f"{voice_binding.voice_id}:preset",
                "audio_uri": str(
                    preset.preset_assets.get("reference_audio", {}).get("path")
                    or preset.preset_assets.get("reference_audio", {}).get("source_path")
                    or preset.preset_assets.get("reference_audio", {}).get("relative_path")
                    or ""
                ),
                "text": str(preset.defaults.get("reference_text") or ""),
                "language": str(preset.defaults.get("reference_language") or ""),
                "source": "preset",
                "fingerprint": str(
                    preset.preset_assets.get("reference_audio", {}).get("fingerprint")
                    or ""
                ),
            }
        return {
            "reference_id": resolved_reference.reference_identity,
            "audio_uri": resolved_reference.reference_audio_path,
            "text": resolved_reference.reference_text,
            "language": resolved_reference.reference_language,
            "source": resolved_reference.source,
            "fingerprint": resolved_reference.reference_audio_fingerprint,
        }

    def _resolve_secret_handles(self, model_instance: ModelInstance) -> dict[str, str]:
        account_binding = model_instance.account_binding
        if not isinstance(account_binding, dict):
            return {}
        required_secrets = account_binding.get("required_secrets")
        if (
            self._secret_store is not None
            and isinstance(required_secrets, list)
            and self._secret_store.has_all_secrets(
                model_instance.model_instance_id,
                [str(secret_name) for secret_name in required_secrets],
            )
        ):
            return {
                str(secret_name): self._secret_store.build_handle(
                    model_instance.model_instance_id,
                    str(secret_name),
                )
                for secret_name in required_secrets
            }
        secret_handles = account_binding.get("secret_handles")
        if not isinstance(secret_handles, dict):
            return {}
        return {str(key): str(value) for key, value in secret_handles.items()}
