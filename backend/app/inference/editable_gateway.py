from __future__ import annotations

from dataclasses import replace
import threading
from typing import TYPE_CHECKING, Callable, Protocol

from backend.app.inference.editable_types import (
    BoundaryAssetPayload,
    ReferenceContext,
    ResolvedRenderContext,
    SegmentRenderAssetPayload,
)
from backend.app.schemas.edit_session import EditableEdge, EditableSegment

if TYPE_CHECKING:
    from backend.app.inference.model_cache import PyTorchModelCache


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


class CacheBackedEditableInferenceBackend:
    def __init__(
        self,
        *,
        model_cache: "PyTorchModelCache",
        gpt_path: str,
        sovits_path: str,
    ) -> None:
        self._model_cache = model_cache
        self._gpt_path = gpt_path
        self._sovits_path = sovits_path

    def build_reference_context(self, resolved_context: ResolvedRenderContext) -> ReferenceContext:
        handle = self._model_cache.acquire_model_handle(gpt_path=self._gpt_path, sovits_path=self._sovits_path)
        try:
            return handle.engine.build_reference_context(resolved_context)
        finally:
            self._model_cache.release_model_handle(handle.cache_key)

    def render_segment_base(
        self,
        segment: EditableSegment,
        context: ReferenceContext,
        *,
        progress_callback: Callable[[dict], None] | None = None,
    ) -> SegmentRenderAssetPayload:
        handle = self._model_cache.acquire_model_handle(gpt_path=self._gpt_path, sovits_path=self._sovits_path)
        try:
            return handle.engine.render_segment_base(segment, context, progress_callback=progress_callback)
        finally:
            self._model_cache.release_model_handle(handle.cache_key)

    def render_boundary_asset(
        self,
        left_asset: SegmentRenderAssetPayload,
        right_asset: SegmentRenderAssetPayload,
        edge: EditableEdge,
        context: ReferenceContext,
    ) -> BoundaryAssetPayload:
        handle = self._model_cache.acquire_model_handle(gpt_path=self._gpt_path, sovits_path=self._sovits_path)
        try:
            return handle.engine.render_boundary_asset(left_asset, right_asset, edge, context)
        finally:
            self._model_cache.release_model_handle(handle.cache_key)


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


class RoutingEditableInferenceGateway:
    def __init__(
        self,
        *,
        default_gateway: EditableInferenceGateway | LazyEditableInferenceGateway,
        gateway_cache: dict[tuple[str, str], EditableInferenceGateway | LazyEditableInferenceGateway],
        gateway_factory: Callable[[str, str], EditableInferenceGateway | LazyEditableInferenceGateway],
    ) -> None:
        self._default_gateway = default_gateway
        self._gateway_cache = gateway_cache
        self._gateway_factory = gateway_factory
        self._gateway_lock = threading.Lock()

    @staticmethod
    def _resolve_cache_key(resolved_context: ResolvedRenderContext) -> tuple[str, str] | None:
        binding = resolved_context.resolved_voice_binding
        if binding is None:
            return None
        if not binding.gpt_path or not binding.sovits_path:
            return None
        return (binding.gpt_path, binding.sovits_path)

    def _get_gateway(
        self,
        cache_key: tuple[str, str] | None,
    ) -> EditableInferenceGateway | LazyEditableInferenceGateway:
        if cache_key is None:
            return self._default_gateway

        gateway = self._gateway_cache.get(cache_key)
        if gateway is not None:
            return gateway

        with self._gateway_lock:
            cached = self._gateway_cache.get(cache_key)
            if cached is not None:
                return cached
            created = self._gateway_factory(*cache_key)
            self._gateway_cache[cache_key] = created
            return created

    def build_reference_context(self, resolved_context: ResolvedRenderContext) -> ReferenceContext:
        cache_key = self._resolve_cache_key(resolved_context)
        context = self._get_gateway(cache_key).build_reference_context(resolved_context)
        if cache_key is None:
            return context
        return replace(context, backend_cache_key=cache_key)

    def render_segment_base(
        self,
        segment: EditableSegment,
        context: ReferenceContext,
        *,
        progress_callback: Callable[[dict], None] | None = None,
    ) -> SegmentRenderAssetPayload:
        return self._get_gateway(context.backend_cache_key).render_segment_base(
            segment,
            context,
            progress_callback=progress_callback,
        )

    def render_boundary_asset(
        self,
        left_asset: SegmentRenderAssetPayload,
        right_asset: SegmentRenderAssetPayload,
        edge: EditableEdge,
        context: ReferenceContext,
    ) -> BoundaryAssetPayload:
        return self._get_gateway(context.backend_cache_key).render_boundary_asset(
            left_asset,
            right_asset,
            edge,
            context,
        )

    def clear_backend(self) -> None:
        seen: set[int] = set()
        for gateway in [self._default_gateway, *self._gateway_cache.values()]:
            identity = id(gateway)
            if identity in seen:
                continue
            seen.add(identity)
            clear_backend = getattr(gateway, "clear_backend", None)
            if callable(clear_backend):
                clear_backend()
