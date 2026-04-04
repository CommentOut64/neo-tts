from __future__ import annotations

from typing import Protocol

from backend.app.inference.editable_types import (
    BoundaryAssetPayload,
    ReferenceContext,
    ResolvedRenderContext,
    SegmentRenderAssetPayload,
)
from backend.app.schemas.edit_session import EditableEdge, EditableSegment


class EditableInferenceBackend(Protocol):
    def build_reference_context(self, resolved_context: ResolvedRenderContext) -> ReferenceContext: ...

    def render_segment_base(
        self,
        segment: EditableSegment,
        context: ReferenceContext,
    ) -> SegmentRenderAssetPayload: ...

    def render_boundary_asset(
        self,
        left_asset: SegmentRenderAssetPayload,
        right_asset: SegmentRenderAssetPayload,
        edge: EditableEdge,
        context: ReferenceContext,
    ) -> BoundaryAssetPayload: ...


class EditableInferenceGateway:
    def __init__(self, backend: EditableInferenceBackend) -> None:
        self._backend = backend

    def build_reference_context(self, resolved_context: ResolvedRenderContext) -> ReferenceContext:
        return self._backend.build_reference_context(resolved_context)

    def render_segment_base(
        self,
        segment: EditableSegment,
        context: ReferenceContext,
    ) -> SegmentRenderAssetPayload:
        return self._backend.render_segment_base(segment, context)

    def render_boundary_asset(
        self,
        left_asset: SegmentRenderAssetPayload,
        right_asset: SegmentRenderAssetPayload,
        edge: EditableEdge,
        context: ReferenceContext,
    ) -> BoundaryAssetPayload:
        return self._backend.render_boundary_asset(left_asset, right_asset, edge, context)
