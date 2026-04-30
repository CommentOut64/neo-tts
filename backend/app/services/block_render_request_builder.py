from __future__ import annotations

import hashlib
from dataclasses import dataclass

from backend.app.inference.block_adapter_errors import BlockAdapterError
from backend.app.inference.block_adapter_registry import AdapterRegistry
from backend.app.inference.block_adapter_types import (
    BlockPolicy,
    BlockRenderRequest,
    BlockRequestBlock,
    BlockRequestSegment,
    DirtyContext,
    EdgeControl,
)
from backend.app.inference.editable_types import RenderBlock
from backend.app.schemas.edit_session import DocumentSnapshot, EditableSegment, TimelineManifest
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
    ) -> list[BlockRenderRequest]:
        requests: list[BlockRenderRequest] = []
        for block in blocks:
            prepared_segments = [
                _PreparedSegment(segment=resolved_segments[segment_id].segment, resolved=resolved_segments[segment_id])
                for segment_id in block.segment_ids
            ]
            ordered_segments = sorted(prepared_segments, key=lambda item: item.segment.order_key)
            requests.extend(
                self._build_block_requests(
                    snapshot=snapshot,
                    block=block,
                    ordered_segments=ordered_segments,
                    resolved_edges=resolved_edges,
                    target_segment_ids=target_segment_ids,
                    target_edge_ids=target_edge_ids,
                    previous_timeline=previous_timeline,
                    reuse_policy=reuse_policy,
                )
            )
        return requests

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
    ) -> list[BlockRenderRequest]:
        requests: list[BlockRenderRequest] = []
        cursor = 0
        while cursor < len(ordered_segments):
            chunk = self._collect_chunk(ordered_segments, cursor)
            cursor += len(chunk)
            first_binding = chunk[0].resolved.resolved_model_binding
            if first_binding is None:
                raise AdapterRegistry.build_model_required_error()
            adapter_definition = self._adapter_registry.require(first_binding.adapter_id)
            chunk_segment_ids = [item.segment.segment_id for item in chunk]
            request_block = self._build_request_block(chunk, block)
            edge_controls = self._build_edge_controls(
                chunk=chunk,
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
            requests.append(
                BlockRenderRequest(
                    request_id=self._build_request_id(
                        document_id=snapshot.document_id,
                        block_id=request_block.block_id,
                        binding_fingerprint=first_binding.binding_fingerprint,
                    ),
                    document_id=snapshot.document_id,
                    block=request_block,
                    model_binding=first_binding,
                    voice={
                        "voice_id": chunk[0].resolved.voice_binding.voice_id,
                        "voice_binding_id": chunk[0].resolved.voice_binding.voice_binding_id,
                    },
                    model={
                        "model_key": chunk[0].resolved.voice_binding.model_key,
                        "model_instance_id": chunk[0].resolved.voice_binding.model_instance_id,
                        "preset_id": chunk[0].resolved.voice_binding.preset_id,
                    },
                    reference={
                        "reference_id": top_level_reference.get("reference_id", ""),
                    },
                    synthesis=dict(first_binding.resolved_parameters),
                    join_policy=join_policy,
                    edge_controls=edge_controls,
                    dirty_context=dirty_context,
                    block_policy=self._default_block_policy,
                )
            )
        return requests

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
    def _build_request_id(*, document_id: str, block_id: str, binding_fingerprint: str) -> str:
        digest = hashlib.sha1(f"{document_id}|{block_id}|{binding_fingerprint}".encode("utf-8")).hexdigest()[:12]
        return f"req-{digest}"

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
