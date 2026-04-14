from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from backend.app.core.exceptions import EditSessionNotFoundError
from backend.app.schemas.edit_session import (
    DocumentSnapshot,
    ReferenceBindingOverride,
    RenderProfile,
    RenderProfilePatchRequest,
    SegmentGroup,
    VoiceBinding,
    VoiceBindingPatchRequest,
)


@dataclass(frozen=True)
class GroupMutationResult:
    snapshot: DocumentSnapshot
    group: SegmentGroup


class SegmentGroupService:
    def ensure_group(
        self,
        *,
        snapshot: DocumentSnapshot,
        target_group_id: str | None,
        created_by: str,
        name: str | None = None,
    ) -> GroupMutationResult:
        groups = [group.model_copy(deep=True) for group in snapshot.groups]
        if target_group_id is not None:
            group = next((item for item in groups if item.group_id == target_group_id), None)
            if group is None:
                raise EditSessionNotFoundError(f"Segment group '{target_group_id}' not found.")
            return GroupMutationResult(snapshot=snapshot.model_copy(deep=True), group=group)

        group = SegmentGroup(
            group_id=f"group-{uuid4().hex}",
            name=name or "append-group",
            created_by=created_by,  # type: ignore[arg-type]
        )
        groups.append(group)
        return GroupMutationResult(
            snapshot=snapshot.model_copy(deep=True, update={"groups": groups}),
            group=group,
        )

    def attach_segments(
        self,
        *,
        snapshot: DocumentSnapshot,
        group_id: str,
        segment_ids: list[str],
    ) -> GroupMutationResult:
        groups = [group.model_copy(deep=True) for group in snapshot.groups]
        group_index = next((index for index, group in enumerate(groups) if group.group_id == group_id), None)
        if group_index is None:
            raise EditSessionNotFoundError(f"Segment group '{group_id}' not found.")
        group = groups[group_index].model_copy(
            update={
                "segment_ids": [*groups[group_index].segment_ids, *segment_ids],
            }
        )
        groups[group_index] = group
        return GroupMutationResult(
            snapshot=snapshot.model_copy(deep=True, update={"groups": groups}),
            group=group,
        )

    def update_group_render_profile(
        self,
        group_id: str,
        patch: RenderProfilePatchRequest,
        *,
        snapshot: DocumentSnapshot,
    ) -> GroupMutationResult:
        groups = [group.model_copy(deep=True) for group in snapshot.groups]
        group_index = next((index for index, group in enumerate(groups) if group.group_id == group_id), None)
        if group_index is None:
            raise EditSessionNotFoundError(f"Segment group '{group_id}' not found.")
        next_snapshot, profile = self.create_render_profile(
            snapshot=snapshot,
            scope="group",
            patch=patch,
            base_profile_id=groups[group_index].render_profile_id or snapshot.default_render_profile_id,
        )
        groups = [group.model_copy(deep=True) for group in next_snapshot.groups]
        group = groups[group_index].model_copy(update={"render_profile_id": profile.render_profile_id})
        groups[group_index] = group
        return GroupMutationResult(
            snapshot=next_snapshot.model_copy(deep=True, update={"groups": groups}),
            group=group,
        )

    def update_group_voice_binding(
        self,
        group_id: str,
        patch: VoiceBindingPatchRequest,
        *,
        snapshot: DocumentSnapshot,
    ) -> GroupMutationResult:
        groups = [group.model_copy(deep=True) for group in snapshot.groups]
        group_index = next((index for index, group in enumerate(groups) if group.group_id == group_id), None)
        if group_index is None:
            raise EditSessionNotFoundError(f"Segment group '{group_id}' not found.")
        next_snapshot, binding = self.create_voice_binding(
            snapshot=snapshot,
            scope="group",
            patch=patch,
            base_binding_id=groups[group_index].voice_binding_id or snapshot.default_voice_binding_id,
        )
        groups = [group.model_copy(deep=True) for group in next_snapshot.groups]
        group = groups[group_index].model_copy(update={"voice_binding_id": binding.voice_binding_id})
        groups[group_index] = group
        return GroupMutationResult(
            snapshot=next_snapshot.model_copy(deep=True, update={"groups": groups}),
            group=group,
        )

    def update_session_render_profile(
        self,
        patch: RenderProfilePatchRequest,
        *,
        snapshot: DocumentSnapshot,
    ) -> DocumentSnapshot:
        next_snapshot, profile = self.create_render_profile(
            snapshot=snapshot,
            scope="session",
            patch=patch,
            base_profile_id=snapshot.default_render_profile_id,
        )
        return next_snapshot.model_copy(deep=True, update={"default_render_profile_id": profile.render_profile_id})

    def update_session_voice_binding(
        self,
        patch: VoiceBindingPatchRequest,
        *,
        snapshot: DocumentSnapshot,
    ) -> DocumentSnapshot:
        next_snapshot, binding = self.create_voice_binding(
            snapshot=snapshot,
            scope="session",
            patch=patch,
            base_binding_id=snapshot.default_voice_binding_id,
        )
        return next_snapshot.model_copy(deep=True, update={"default_voice_binding_id": binding.voice_binding_id})

    @staticmethod
    def create_render_profile(
        *,
        snapshot: DocumentSnapshot,
        scope: str,
        patch: RenderProfilePatchRequest,
        base_profile_id: str | None,
    ) -> tuple[DocumentSnapshot, RenderProfile]:
        base = SegmentGroupService._get_render_profile(snapshot=snapshot, render_profile_id=base_profile_id)
        next_profile = base.model_copy(
            update={
                "render_profile_id": f"profile-{scope}-{uuid4().hex}",
                "scope": scope,
                "name": patch.name if patch.name is not None else base.name,
                "speed": patch.speed if patch.speed is not None else base.speed,
                "top_k": patch.top_k if patch.top_k is not None else base.top_k,
                "top_p": patch.top_p if patch.top_p is not None else base.top_p,
                "temperature": patch.temperature if patch.temperature is not None else base.temperature,
                "noise_scale": patch.noise_scale if patch.noise_scale is not None else base.noise_scale,
                "reference_overrides_by_binding": SegmentGroupService._apply_reference_override_patch(
                    base=base,
                    patch=patch,
                ),
                "reference_audio_path": (
                    None
                    if patch.reference_override is not None
                    else (patch.reference_audio_path if patch.reference_audio_path is not None else base.reference_audio_path)
                ),
                "reference_text": (
                    None
                    if patch.reference_override is not None
                    else (patch.reference_text if patch.reference_text is not None else base.reference_text)
                ),
                "reference_language": (
                    None
                    if patch.reference_override is not None
                    else (patch.reference_language if patch.reference_language is not None else base.reference_language)
                ),
                "extra_overrides": SegmentGroupService._build_extra_overrides(
                    base=base,
                    patch=patch,
                ),
            }
        )
        return (
            snapshot.model_copy(deep=True, update={"render_profiles": [*snapshot.render_profiles, next_profile]}),
            next_profile,
        )

    @staticmethod
    def create_voice_binding(
        *,
        snapshot: DocumentSnapshot,
        scope: str,
        patch: VoiceBindingPatchRequest,
        base_binding_id: str | None,
    ) -> tuple[DocumentSnapshot, VoiceBinding]:
        base = SegmentGroupService._get_voice_binding(snapshot=snapshot, voice_binding_id=base_binding_id)
        next_binding = base.model_copy(
            update={
                "voice_binding_id": f"binding-{scope}-{uuid4().hex}",
                "scope": scope,
                "voice_id": patch.voice_id if patch.voice_id is not None else base.voice_id,
                "model_key": patch.model_key if patch.model_key is not None else base.model_key,
                "sovits_path": patch.sovits_path if patch.sovits_path is not None else base.sovits_path,
                "gpt_path": patch.gpt_path if patch.gpt_path is not None else base.gpt_path,
                "speaker_meta": patch.speaker_meta if patch.speaker_meta is not None else dict(base.speaker_meta),
            }
        )
        return (
            snapshot.model_copy(deep=True, update={"voice_bindings": [*snapshot.voice_bindings, next_binding]}),
            next_binding,
        )

    @staticmethod
    def _get_render_profile(*, snapshot: DocumentSnapshot, render_profile_id: str | None) -> RenderProfile:
        if render_profile_id is None:
            return RenderProfile(render_profile_id=f"profile-session-{uuid4().hex}", scope="session")
        profile = next((item for item in snapshot.render_profiles if item.render_profile_id == render_profile_id), None)
        if profile is None:
            raise EditSessionNotFoundError(f"Render profile '{render_profile_id}' not found.")
        return profile

    @staticmethod
    def _get_voice_binding(*, snapshot: DocumentSnapshot, voice_binding_id: str | None) -> VoiceBinding:
        if voice_binding_id is None:
            raise EditSessionNotFoundError("Default voice binding not found.")
        binding = next((item for item in snapshot.voice_bindings if item.voice_binding_id == voice_binding_id), None)
        if binding is None:
            raise EditSessionNotFoundError(f"Voice binding '{voice_binding_id}' not found.")
        return binding

    @staticmethod
    def _apply_reference_override_patch(
        *,
        base: RenderProfile,
        patch: RenderProfilePatchRequest,
    ) -> dict[str, ReferenceBindingOverride]:
        overrides_by_binding = {
            binding_key: override.model_copy(deep=True)
            for binding_key, override in base.reference_overrides_by_binding.items()
        }
        if patch.reference_override is None:
            return overrides_by_binding
        if patch.reference_override.operation == "clear":
            overrides_by_binding.pop(patch.reference_override.binding_key, None)
            return overrides_by_binding
        overrides_by_binding[patch.reference_override.binding_key] = ReferenceBindingOverride(
            reference_audio_path=patch.reference_override.reference_audio_path,
            reference_text=patch.reference_override.reference_text,
            reference_language=patch.reference_override.reference_language,
        )
        return overrides_by_binding

    @staticmethod
    def _build_extra_overrides(
        *,
        base: RenderProfile,
        patch: RenderProfilePatchRequest,
    ) -> dict[str, object]:
        if patch.extra_overrides is not None:
            next_extra_overrides = dict(patch.extra_overrides)
        else:
            next_extra_overrides = dict(base.extra_overrides)

        if patch.reference_override is not None:
            next_extra_overrides.pop("legacy_reference_binding_fallback", None)
            return next_extra_overrides

        if (
            patch.reference_audio_path is not None
            or patch.reference_text is not None
            or patch.reference_language is not None
        ):
            next_extra_overrides["legacy_reference_binding_fallback"] = True

        return next_extra_overrides
