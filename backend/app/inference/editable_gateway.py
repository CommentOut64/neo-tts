from __future__ import annotations

import threading
from typing import Callable, Protocol

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
        *,
        progress_callback: Callable[[dict], None] | None = None,
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
        *,
        progress_callback: Callable[[dict], None] | None = None,
    ) -> SegmentRenderAssetPayload:
        return self._backend.render_segment_base(segment, context, progress_callback=progress_callback)

    def render_boundary_asset(
        self,
        left_asset: SegmentRenderAssetPayload,
        right_asset: SegmentRenderAssetPayload,
        edge: EditableEdge,
        context: ReferenceContext,
    ) -> BoundaryAssetPayload:
        return self._backend.render_boundary_asset(left_asset, right_asset, edge, context)


class LazyEditableInferenceGateway:
    def __init__(self, backend_factory: Callable[[], EditableInferenceBackend]) -> None:
        self._backend_factory = backend_factory
        self._backend: EditableInferenceBackend | None = None
        self._backend_lock = threading.Lock()

    def _get_backend(self) -> EditableInferenceBackend:
        backend = self._backend
        if backend is not None:
            return backend
        with self._backend_lock:
            if self._backend is None:
                self._backend = self._backend_factory()
            return self._backend

    def build_reference_context(self, resolved_context: ResolvedRenderContext) -> ReferenceContext:
        return self._get_backend().build_reference_context(resolved_context)

    def render_segment_base(
        self,
        segment: EditableSegment,
        context: ReferenceContext,
        *,
        progress_callback: Callable[[dict], None] | None = None,
    ) -> SegmentRenderAssetPayload:
        return self._get_backend().render_segment_base(segment, context, progress_callback=progress_callback)

    def render_boundary_asset(
        self,
        left_asset: SegmentRenderAssetPayload,
        right_asset: SegmentRenderAssetPayload,
        edge: EditableEdge,
        context: ReferenceContext,
    ) -> BoundaryAssetPayload:
        return self._get_backend().render_boundary_asset(left_asset, right_asset, edge, context)

    def clear_backend(self) -> None:
        with self._backend_lock:
            self._backend = None
