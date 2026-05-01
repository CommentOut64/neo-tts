from __future__ import annotations

from typing import Callable

from backend.app.inference.editable_types import (
    BlockCompositionAssetPayload,
    BoundaryAssetPayload,
    RenderBlock,
    SegmentRenderAssetPayload,
)
from backend.app.schemas.edit_session import DocumentSnapshot, EditableEdge, EditableSegment, TimelineManifest
from backend.app.services.composition_builder import CompositionBuilder


class FormalBlockAssembler:
    def __init__(
        self,
        *,
        composition_builder: CompositionBuilder,
        render_config_resolver,
        resolve_boundary_strategy_for_assets: Callable[..., str],
        load_previous_block_asset_for_recompose: Callable[..., BlockCompositionAssetPayload | None],
        build_boundary_asset_from_previous_block_asset: Callable[..., BoundaryAssetPayload | None],
        load_or_rebuild_boundary_asset: Callable[..., tuple[BoundaryAssetPayload, str]],
        write_block_asset: Callable[[str, BlockCompositionAssetPayload], None],
    ) -> None:
        self._composition_builder = composition_builder
        self._render_config_resolver = render_config_resolver
        self._resolve_boundary_strategy_for_assets = resolve_boundary_strategy_for_assets
        self._load_previous_block_asset_for_recompose = load_previous_block_asset_for_recompose
        self._build_boundary_asset_from_previous_block_asset = build_boundary_asset_from_previous_block_asset
        self._load_or_rebuild_boundary_asset = load_or_rebuild_boundary_asset
        self._write_block_asset = write_block_asset

    def assemble(
        self,
        *,
        job_id: str,
        segments: list[EditableSegment],
        edges: list[EditableEdge],
        segment_assets: dict[str, SegmentRenderAssetPayload],
        boundary_assets: dict[str, BoundaryAssetPayload],
        block: RenderBlock,
        snapshot: DocumentSnapshot,
        previous_timeline: TimelineManifest | None,
    ) -> BlockCompositionAssetPayload:
        block_segments = [segment_assets[segment_id] for segment_id in block.segment_ids]
        segment_by_id = {segment.segment_id: segment for segment in segments}
        block_edges = [
            edge
            for edge in edges
            if edge.left_segment_id in block.segment_ids and edge.right_segment_id in block.segment_ids
        ]
        block_boundaries: list[BoundaryAssetPayload] = []
        previous_block_asset = self._load_previous_block_asset_for_recompose(
            previous_timeline=previous_timeline,
            block=block,
        )
        for edge in block_edges:
            resolved_edge = self._render_config_resolver.resolve_edge(snapshot=snapshot, edge_id=edge.edge_id)
            left_asset = segment_assets[edge.left_segment_id]
            right_asset = segment_assets[edge.right_segment_id]
            effective_boundary_strategy = self._resolve_boundary_strategy_for_assets(
                edge=edge,
                left_asset=left_asset,
                right_asset=right_asset,
                effective_boundary_strategy=resolved_edge.effective_boundary_strategy,
            )
            boundary_asset = self._build_boundary_asset_from_previous_block_asset(
                previous_block_asset=previous_block_asset,
                edge=edge,
                left_asset=left_asset,
                right_asset=right_asset,
                effective_boundary_strategy=effective_boundary_strategy,
            )
            if boundary_asset is None:
                boundary_asset, effective_boundary_strategy = self._load_or_rebuild_boundary_asset(
                    snapshot=snapshot,
                    edge=edge,
                    left_asset=left_asset,
                    right_asset=right_asset,
                    effective_boundary_strategy=effective_boundary_strategy,
                )
            boundary_assets[edge.edge_id] = boundary_asset
            edge.effective_boundary_strategy = effective_boundary_strategy
            edge.boundary_sample_count = boundary_asset.boundary_sample_count
            edge.pause_sample_count = int(self._composition_builder._sample_rate * edge.pause_duration_seconds)
            block_boundaries.append(boundary_asset)
        block_asset = self._composition_builder.compose_block(
            segments=block_segments,
            boundaries=block_boundaries,
            edges=block_edges,
            block_id=block.block_id,
            segment_alignment_mode=previous_block_asset.segment_alignment_mode if previous_block_asset is not None else None,
            join_report_summary=previous_block_asset.join_report_summary if previous_block_asset is not None else None,
            segment_entry_asset_ids={
                segment_id: segment_by_id.get(segment_id).render_asset_id if segment_by_id.get(segment_id) is not None else None
                for segment_id in block.segment_ids
            },
            segment_entry_base_asset_ids={
                segment_id: (
                    segment_by_id.get(segment_id).base_render_asset_id
                    if segment_by_id.get(segment_id) is not None
                    else None
                )
                for segment_id in block.segment_ids
            },
        )
        self._write_block_asset(job_id, block_asset)
        return block_asset
