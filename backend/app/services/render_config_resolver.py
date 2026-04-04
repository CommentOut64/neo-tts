from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json

from backend.app.core.exceptions import EditSessionNotFoundError
from backend.app.schemas.edit_session import (
    DocumentSnapshot,
    EditableEdge,
    EditableSegment,
    RenderProfile,
    VoiceBinding,
)


@dataclass(frozen=True)
class ResolvedSegmentConfig:
    segment: EditableSegment
    render_profile: RenderProfile
    voice_binding: VoiceBinding
    render_profile_fingerprint: str
    model_cache_key: str


@dataclass(frozen=True)
class ResolvedEdgeConfig:
    edge: EditableEdge
    left_binding: VoiceBinding
    right_binding: VoiceBinding
    effective_boundary_strategy: str


class RenderConfigResolver:
    def resolve_segment(self, *, snapshot: DocumentSnapshot, segment_id: str) -> ResolvedSegmentConfig:
        segment = next((item for item in snapshot.segments if item.segment_id == segment_id), None)
        if segment is None:
            raise EditSessionNotFoundError(f"Segment '{segment_id}' not found.")

        render_profile = self._resolve_render_profile(snapshot=snapshot, segment=segment)
        voice_binding = self._resolve_voice_binding(snapshot=snapshot, segment=segment)
        fingerprint_payload = json.dumps(render_profile.model_dump(mode="json"), ensure_ascii=True, sort_keys=True)
        render_profile_fingerprint = hashlib.sha1(fingerprint_payload.encode("utf-8")).hexdigest()
        return ResolvedSegmentConfig(
            segment=segment,
            render_profile=render_profile,
            voice_binding=voice_binding,
            render_profile_fingerprint=render_profile_fingerprint,
            model_cache_key=f"{voice_binding.voice_id}:{voice_binding.model_key}",
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
