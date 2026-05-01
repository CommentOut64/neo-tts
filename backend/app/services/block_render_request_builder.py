from __future__ import annotations

import hashlib
from dataclasses import dataclass

from backend.app.inference.block_adapter_errors import BlockAdapterError
from backend.app.inference.block_adapter_registry import AdapterRegistry
from backend.app.inference.block_adapter_types import (
    BoundaryContext,
    BlockPolicy,
    BlockRenderRequest,
    BlockRequestBlock,
    BlockRequestSegment,
    DirtyContext,
    EdgeControl,
    RenderScope,
    ReusableSourceAssetDescriptor,
)
from backend.app.inference.editable_types import RenderBlock
from backend.app.schemas.edit_session import DocumentSnapshot, EditableSegment, TimelineManifest
from backend.app.services.render_execution_plan import (
    ExecutionBoundaryContext,
    ExecutionPlan,
    ExecutionUnit,
    FormalBlockPlan,
    build_degradation_policy,
    build_scope_policy,
    normalize_degradation_policy,
    normalize_scope_policy,
)
from backend.app.services.render_config_resolver import ResolvedEdgeConfig, ResolvedSegmentConfig


@dataclass(frozen=True)
class _PreparedSegment:
    segment: EditableSegment
    resolved: ResolvedSegmentConfig


class BlockRenderRequestBuilder:
    def __init__(
        self,
        *,
        adapter_registry: AdapterRegistry,
        sample_rate: int = 32000,
        default_block_policy: BlockPolicy | None = None,
    ) -> None:
        self._adapter_registry = adapter_registry
        self._sample_rate = sample_rate
        self._default_block_policy = default_block_policy or BlockPolicy()

    def build_requests(
        self,
        *,
        snapshot: DocumentSnapshot,
        blocks: list[RenderBlock],
        resolved_segments: dict[str, ResolvedSegmentConfig],
        resolved_edges: dict[str, ResolvedEdgeConfig],
        target_segment_ids: set[str],
        target_edge_ids: set[str],
        previous_timeline: TimelineManifest | None,
        reuse_policy: str,
        render_scope: RenderScope = "block",
    ) -> list[BlockRenderRequest]:
        execution_plan = self.build_execution_plan(
            snapshot=snapshot,
            blocks=blocks,
            resolved_segments=resolved_segments,
            resolved_edges=resolved_edges,
            target_segment_ids=target_segment_ids,
            target_edge_ids=target_edge_ids,
            previous_timeline=previous_timeline,
            reuse_policy=reuse_policy,
            render_scope=render_scope,
        )
        requests: list[BlockRenderRequest] = []
        for formal_block_plan in execution_plan.formal_blocks:
            requests.extend(unit.request for unit in formal_block_plan.execution_units)
        return requests

    def build_execution_plan(
        self,
        *,
        snapshot: DocumentSnapshot,
        blocks: list[RenderBlock],
        resolved_segments: dict[str, ResolvedSegmentConfig],
        resolved_edges: dict[str, ResolvedEdgeConfig],
        target_segment_ids: set[str],
        target_edge_ids: set[str],
        previous_timeline: TimelineManifest | None,
        reuse_policy: str,
        render_scope: RenderScope = "block",
    ) -> ExecutionPlan:
        formal_block_plans: list[FormalBlockPlan] = []
        for block in blocks:
            prepared_segments = [
                _PreparedSegment(segment=resolved_segments[segment_id].segment, resolved=resolved_segments[segment_id])
                for segment_id in block.segment_ids
            ]
            ordered_segments = sorted(prepared_segments, key=lambda item: item.segment.order_key)
            requests = self._build_block_requests(
                snapshot=snapshot,
                block=block,
                ordered_segments=ordered_segments,
                resolved_edges=resolved_edges,
                target_segment_ids=target_segment_ids,
                target_edge_ids=target_edge_ids,
                previous_timeline=previous_timeline,
                reuse_policy=reuse_policy,
                render_scope=render_scope,
            )
            formal_block_plans.append(
                FormalBlockPlan(
                    formal_block=block,
                    execution_units=tuple(
                        self._build_execution_unit(
                            request=request,
                            formal_block=block,
                        )
                        for request in requests
                    ),
                )
            )
        return ExecutionPlan(formal_blocks=tuple(formal_block_plans))

    def _build_block_requests(
        self,
        *,
        snapshot: DocumentSnapshot,
        block: RenderBlock,
        ordered_segments: list[_PreparedSegment],
        resolved_edges: dict[str, ResolvedEdgeConfig],
        target_segment_ids: set[str],
        target_edge_ids: set[str],
        previous_timeline: TimelineManifest | None,
        reuse_policy: str,
        render_scope: RenderScope,
    ) -> list[BlockRenderRequest]:
        requests: list[BlockRenderRequest] = []
        cursor = 0
        while cursor < len(ordered_segments):
            chunk = self._collect_chunk(ordered_segments, cursor)
            cursor += len(chunk)
            scoped_windows = self._split_chunk_by_scope(
                chunk=chunk,
                snapshot=snapshot,
                target_segment_ids=target_segment_ids,
                target_edge_ids=target_edge_ids,
                render_scope=render_scope,
            )
            for scoped_chunk in scoped_windows:
                first_binding = scoped_chunk[0].resolved.resolved_model_binding
                if first_binding is None:
                    raise AdapterRegistry.build_model_required_error()
                adapter_definition = self._adapter_registry.require(first_binding.adapter_id)
                chunk_segment_ids = [item.segment.segment_id for item in scoped_chunk]
                request_block = self._build_request_block(scoped_chunk, block)
                edge_controls = self._build_edge_controls(
                    chunk=scoped_chunk,
                    snapshot=snapshot,
                    resolved_edges=resolved_edges,
                )
                join_policy = self._resolve_join_policy(edge_controls)
                dirty_context = self._build_dirty_context(
                    chunk_segment_ids=chunk_segment_ids,
                    edge_controls=edge_controls,
                    target_segment_ids=target_segment_ids,
                    target_edge_ids=target_edge_ids,
                    previous_timeline=previous_timeline,
                    reuse_policy=reuse_policy,
                    adapter_definition=adapter_definition,
                )
                top_level_reference = first_binding.resolved_reference or {}
                boundary_contexts = self._build_boundary_contexts(
                    edge_controls=edge_controls,
                    snapshot=snapshot,
                )
                reusable_source_assets = self._build_reusable_source_assets(
                    chunk=scoped_chunk,
                    target_segment_ids=target_segment_ids,
                )
                requests.append(
                    BlockRenderRequest(
                        request_id=self._build_request_id(
                            document_id=snapshot.document_id,
                            block_id=request_block.block_id,
                            binding_fingerprint=first_binding.binding_fingerprint,
                        ),
                        document_id=snapshot.document_id,
                        execution_unit_id=self._build_execution_unit_id(
                            document_id=snapshot.document_id,
                            formal_block_id=block.block_id,
                            execution_segment_ids=chunk_segment_ids,
                            render_scope=render_scope,
                        ),
                        formal_block_id=block.block_id,
                        render_scope=render_scope,
                        escalated_from_scope=None,
                        block=request_block,
                        model_binding=first_binding,
                        voice={
                            "voice_id": scoped_chunk[0].resolved.voice_binding.voice_id,
                            "voice_binding_id": scoped_chunk[0].resolved.voice_binding.voice_binding_id,
                        },
                        model={
                            "model_key": scoped_chunk[0].resolved.voice_binding.model_key,
                            "model_instance_id": scoped_chunk[0].resolved.voice_binding.model_instance_id,
                            "preset_id": scoped_chunk[0].resolved.voice_binding.preset_id,
                        },
                        reference={
                            "reference_id": top_level_reference.get("reference_id", ""),
                        },
                        synthesis=dict(first_binding.resolved_parameters),
                        requested_alignment_mode="exact",
                        join_policy=join_policy,
                        requested_join_policy=join_policy,
                        effective_join_policy=join_policy,
                        edge_controls=edge_controls,
                        boundary_contexts=boundary_contexts,
                        reusable_source_assets=reusable_source_assets,
                        dirty_context=dirty_context,
                        resolved_reference=dict(top_level_reference),
                        resolved_parameters=dict(first_binding.resolved_parameters),
                        allowed_degradation=normalize_degradation_policy(
                            requested_mode="exact",
                            allowed_modes=["exact", "estimated", "block_only"],
                        ),
                        allowed_scope_escalation=normalize_scope_policy(
                            render_scope=render_scope,
                            allowed_scopes=["segment", "block"] if render_scope == "segment" else ["block"],
                        ),
                        block_policy=self._default_block_policy,
                    )
                )
        return requests

    @staticmethod
    def _split_chunk_by_scope(
        *,
        chunk: list[_PreparedSegment],
        snapshot: DocumentSnapshot,
        target_segment_ids: set[str],
        target_edge_ids: set[str],
        render_scope: RenderScope,
    ) -> list[list[_PreparedSegment]]:
        if render_scope != "segment" or len(chunk) <= 1:
            return [chunk]
        index_by_segment_id = {
            item.segment.segment_id: index
            for index, item in enumerate(chunk)
        }
        dirty_ranges: list[tuple[int, int]] = []
        for index, item in enumerate(chunk):
            if item.segment.segment_id not in target_segment_ids:
                continue
            dirty_ranges.append((max(0, index - 1), min(len(chunk) - 1, index + 1)))
        for edge in snapshot.edges:
            if edge.edge_id not in target_edge_ids:
                continue
            left_index = index_by_segment_id.get(edge.left_segment_id)
            right_index = index_by_segment_id.get(edge.right_segment_id)
            if left_index is None or right_index is None:
                continue
            dirty_ranges.append((min(left_index, right_index), max(left_index, right_index)))
        if not dirty_ranges:
            return [chunk]
        merged_ranges = BlockRenderRequestBuilder._merge_ranges(dirty_ranges)
        windows: list[list[_PreparedSegment]] = []
        cursor = 0
        for start_index, end_index in merged_ranges:
            if cursor < start_index:
                windows.append(chunk[cursor:start_index])
            windows.append(chunk[start_index : end_index + 1])
            cursor = end_index + 1
        if cursor < len(chunk):
            windows.append(chunk[cursor:])
        return [window for window in windows if window]

    @staticmethod
    def _merge_ranges(ranges: list[tuple[int, int]]) -> list[tuple[int, int]]:
        ordered = sorted(ranges)
        merged: list[tuple[int, int]] = []
        for start_index, end_index in ordered:
            if not merged:
                merged.append((start_index, end_index))
                continue
            previous_start, previous_end = merged[-1]
            if start_index <= previous_end + 1:
                merged[-1] = (previous_start, max(previous_end, end_index))
                continue
            merged.append((start_index, end_index))
        return merged

    def _collect_chunk(self, ordered_segments: list[_PreparedSegment], start_index: int) -> list[_PreparedSegment]:
        first = ordered_segments[start_index]
        first_binding = first.resolved.resolved_model_binding
        if first_binding is None:
            raise AdapterRegistry.build_model_required_error()
        adapter_definition = self._adapter_registry.require(first_binding.adapter_id)
        chunk: list[_PreparedSegment] = []
        for index in range(start_index, len(ordered_segments)):
            candidate = ordered_segments[index]
            candidate_binding = candidate.resolved.resolved_model_binding
            if candidate_binding is None:
                raise AdapterRegistry.build_model_required_error(adapter_id=first_binding.adapter_id)
            if candidate_binding.adapter_id != first_binding.adapter_id and chunk:
                break
            if chunk and self._segment_identity_key(candidate) != self._segment_identity_key(first):
                break
            if (
                chunk
                and not adapter_definition.capabilities.segment_level_voice_binding
                and candidate_binding.binding_fingerprint != first_binding.binding_fingerprint
            ):
                break
            tentative = [*chunk, candidate]
            if not self._fits_adapter_limits(tentative, adapter_definition):
                if not chunk:
                    self._raise_segment_limit_error(candidate.segment.segment_id, first_binding.adapter_id)
                break
            chunk = tentative
        return chunk

    def _fits_adapter_limits(self, segments: list[_PreparedSegment], adapter_definition) -> bool:
        limits = adapter_definition.block_limits
        if limits.max_segment_count is not None and len(segments) > limits.max_segment_count:
            return False
        block_text = "\n".join(item.segment.display_text for item in segments)
        if limits.max_block_chars is not None and len(block_text) > limits.max_block_chars:
            return False
        if limits.max_block_seconds is not None:
            sample_count = sum(self._segment_sample_count(item.segment) for item in segments)
            if sample_count > limits.max_block_seconds * self._sample_rate:
                return False
        return True

    def _build_request_block(self, chunk: list[_PreparedSegment], parent_block: RenderBlock) -> BlockRequestBlock:
        ordered_segments = sorted(chunk, key=lambda item: item.segment.order_key)
        segments = [
            BlockRequestSegment(
                segment_id=item.segment.segment_id,
                order_key=item.segment.order_key,
                text=item.segment.display_text,
                language=item.segment.text_language,
                terminal_punctuation=item.segment.terminal_raw,
                voice_binding_id=item.resolved.voice_binding.voice_binding_id,
                render_profile_id=item.resolved.render_profile.render_profile_id,
                render_version=item.segment.render_version,
                resolved_binding={
                    "voice_binding_id": item.resolved.voice_binding.voice_binding_id,
                    "voice_id": item.resolved.voice_binding.voice_id,
                    "model_key": item.resolved.voice_binding.model_key,
                    "model_instance_id": item.resolved.voice_binding.model_instance_id,
                    "preset_id": item.resolved.voice_binding.preset_id,
                },
                resolved_model_binding=(
                    item.resolved.resolved_model_binding.model_dump(mode="json")
                    if item.resolved.resolved_model_binding is not None
                    else None
                ),
                resolved_reference=(
                    {
                        "reference_id": item.resolved.resolved_reference.reference_identity,
                        "audio_uri": item.resolved.resolved_reference.reference_audio_path,
                        "text": item.resolved.resolved_reference.reference_text,
                        "language": item.resolved.resolved_reference.reference_language,
                        "source": item.resolved.resolved_reference.source,
                        "fingerprint": item.resolved.resolved_reference.reference_audio_fingerprint,
                    }
                    if item.resolved.resolved_reference is not None
                    else None
                ),
            )
            for item in ordered_segments
        ]
        segment_ids = [item.segment_id for item in segments]
        block_id = parent_block.block_id if segment_ids == parent_block.segment_ids else self._build_child_block_id(segment_ids)
        return BlockRequestBlock(
            block_id=block_id,
            segment_ids=segment_ids,
            start_order_key=ordered_segments[0].segment.order_key,
            end_order_key=ordered_segments[-1].segment.order_key,
            estimated_sample_count=sum(self._segment_sample_count(item.segment) for item in ordered_segments),
            segments=segments,
            block_text="\n".join(item.text for item in segments),
        )

    def _build_edge_controls(
        self,
        *,
        chunk: list[_PreparedSegment],
        snapshot: DocumentSnapshot,
        resolved_edges: dict[str, ResolvedEdgeConfig],
    ) -> list[EdgeControl]:
        segment_ids = {item.segment.segment_id for item in chunk}
        controls: list[EdgeControl] = []
        for edge in snapshot.edges:
            if edge.left_segment_id not in segment_ids or edge.right_segment_id not in segment_ids:
                continue
            resolved_edge = resolved_edges.get(edge.edge_id)
            effective_strategy = (
                resolved_edge.effective_boundary_strategy
                if resolved_edge is not None
                else edge.boundary_strategy
            )
            controls.append(
                EdgeControl(
                    edge_id=edge.edge_id,
                    left_segment_id=edge.left_segment_id,
                    right_segment_id=edge.right_segment_id,
                    pause_duration_seconds=edge.pause_duration_seconds,
                    join_policy_override=self._map_join_policy(effective_strategy),
                    locked=edge.boundary_strategy_locked,
                )
            )
        return controls

    @staticmethod
    def _build_boundary_contexts(
        *,
        edge_controls: list[EdgeControl],
        snapshot: DocumentSnapshot,
    ) -> list[BoundaryContext]:
        edges_by_id = {edge.edge_id: edge for edge in snapshot.edges}
        contexts: list[BoundaryContext] = []
        for edge_control in edge_controls:
            snapshot_edge = edges_by_id.get(edge_control.edge_id)
            requested_boundary_strategy = (
                snapshot_edge.boundary_strategy
                if snapshot_edge is not None
                else "crossfade_only"
            )
            contexts.append(
                BoundaryContext(
                    edge_id=edge_control.edge_id,
                    left_segment_id=edge_control.left_segment_id,
                    right_segment_id=edge_control.right_segment_id,
                    pause_duration_seconds=edge_control.pause_duration_seconds,
                    requested_boundary_strategy=requested_boundary_strategy,
                    join_policy=edge_control.join_policy_override or "natural",
                    locked=edge_control.locked,
                )
            )
        return contexts

    @staticmethod
    def _build_reusable_source_assets(
        *,
        chunk: list[_PreparedSegment],
        target_segment_ids: set[str],
    ) -> list[ReusableSourceAssetDescriptor]:
        descriptors: list[ReusableSourceAssetDescriptor] = []
        for item in chunk:
            segment = item.segment
            if (
                segment.segment_id in target_segment_ids
                and segment.base_render_asset_id is None
                and segment.render_asset_id is None
            ):
                continue
            descriptors.append(
                ReusableSourceAssetDescriptor(
                    segment_id=segment.segment_id,
                    render_asset_id=segment.render_asset_id,
                    base_render_asset_id=segment.base_render_asset_id,
                    render_version=segment.render_version,
                )
            )
        return descriptors

    @staticmethod
    def _build_execution_unit(
        *,
        request: BlockRenderRequest,
        formal_block: RenderBlock,
    ) -> ExecutionUnit:
        return ExecutionUnit(
            execution_unit_id=request.execution_unit_id,
            formal_block_id=formal_block.block_id,
            request=request,
            segment_ids=tuple(request.block.segment_ids),
            boundary_contexts=tuple(
                ExecutionBoundaryContext(boundary_context=context)
                for context in request.boundary_contexts
            ),
            reusable_source_assets=tuple(request.reusable_source_assets),
            scope_policy=build_scope_policy(request),
            degradation_policy=build_degradation_policy(request),
        )

    def _resolve_join_policy(self, edge_controls: list[EdgeControl]) -> str:
        for edge_control in edge_controls:
            if edge_control.join_policy_override == "prefer_enhanced":
                return "prefer_enhanced"
        for edge_control in edge_controls:
            if edge_control.join_policy_override == "preserve_pause":
                return "preserve_pause"
        return "natural"

    def _build_dirty_context(
        self,
        *,
        chunk_segment_ids: list[str],
        edge_controls: list[EdgeControl],
        target_segment_ids: set[str],
        target_edge_ids: set[str],
        previous_timeline: TimelineManifest | None,
        reuse_policy: str,
        adapter_definition,
    ) -> DirtyContext | None:
        dirty_segment_ids = [segment_id for segment_id in chunk_segment_ids if segment_id in target_segment_ids]
        dirty_edge_ids = [edge.edge_id for edge in edge_controls if edge.edge_id in target_edge_ids]
        previous_block_asset_id = self._find_previous_block_asset_id(previous_timeline, chunk_segment_ids)
        if (
            previous_timeline is not None
            and not dirty_segment_ids
            and not dirty_edge_ids
            and previous_block_asset_id is None
        ):
            return None
        effective_reuse_policy = reuse_policy
        if reuse_policy == "prefer_reuse" and not adapter_definition.capabilities.incremental_render:
            effective_reuse_policy = "adapter_default"
        return DirtyContext(
            dirty_segment_ids=dirty_segment_ids,
            dirty_edge_ids=dirty_edge_ids,
            previous_block_asset_id=previous_block_asset_id,
            reuse_policy=effective_reuse_policy,
        )

    @staticmethod
    def _find_previous_block_asset_id(
        previous_timeline: TimelineManifest | None,
        segment_ids: list[str],
    ) -> str | None:
        if previous_timeline is None:
            return None
        for block_entry in previous_timeline.block_entries:
            if block_entry.segment_ids == segment_ids:
                return block_entry.block_asset_id
        for block_entry in previous_timeline.block_entries:
            if BlockRenderRequestBuilder._is_contiguous_subsequence(segment_ids, block_entry.segment_ids):
                return block_entry.block_asset_id
        return None

    @staticmethod
    def _is_contiguous_subsequence(segment_ids: list[str], candidate_ids: list[str]) -> bool:
        if not segment_ids or len(segment_ids) > len(candidate_ids):
            return False
        window_size = len(segment_ids)
        for index in range(0, len(candidate_ids) - window_size + 1):
            if candidate_ids[index : index + window_size] == segment_ids:
                return True
        return False

    @staticmethod
    def _map_join_policy(boundary_strategy: str) -> str:
        if boundary_strategy in {"enhanced", "latent_overlap_then_equal_power_crossfade"}:
            return "prefer_enhanced"
        if boundary_strategy == "crossfade_only":
            return "preserve_pause"
        return "natural"

    @staticmethod
    def _segment_sample_count(segment: EditableSegment) -> int:
        if segment.assembled_audio_span is None:
            return 0
        return max(0, segment.assembled_audio_span[1] - segment.assembled_audio_span[0])

    @staticmethod
    def _segment_identity_key(prepared: _PreparedSegment) -> str:
        model_binding = prepared.resolved.resolved_model_binding
        if model_binding is None:
            raise AdapterRegistry.build_model_required_error()
        return model_binding.binding_fingerprint

    @staticmethod
    def _build_request_id(*, document_id: str, block_id: str, binding_fingerprint: str) -> str:
        digest = hashlib.sha1(f"{document_id}|{block_id}|{binding_fingerprint}".encode("utf-8")).hexdigest()[:12]
        return f"req-{digest}"

    @staticmethod
    def _build_execution_unit_id(
        *,
        document_id: str,
        formal_block_id: str,
        execution_segment_ids: list[str],
        render_scope: RenderScope,
    ) -> str:
        digest = hashlib.sha1(
            f"{document_id}|{formal_block_id}|{render_scope}|{','.join(execution_segment_ids)}".encode("utf-8")
        ).hexdigest()[:12]
        return f"unit-{digest}"

    @staticmethod
    def _build_child_block_id(segment_ids: list[str]) -> str:
        digest = hashlib.sha1(",".join(segment_ids).encode("utf-8")).hexdigest()[:12]
        return f"block-{digest}"

    @staticmethod
    def _raise_segment_limit_error(segment_id: str, adapter_id: str) -> None:
        raise BlockAdapterError(
            error_code="unsupported_capability",
            message=(
                f"Segment '{segment_id}' exceeds adapter '{adapter_id}' block limits and cannot be auto-split."
            ),
            details={
                "segment_id": segment_id,
                "adapter_id": adapter_id,
            },
        )
