from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable
from uuid import uuid4

import numpy as np

from backend.app.inference.audio_processing import build_wav_bytes, float_audio_chunk_to_pcm16_bytes
from backend.app.inference.editable_gateway import EditableInferenceGateway
from backend.app.inference.editable_types import BoundaryAssetPayload, ReferenceContext, SegmentRenderAssetPayload
from backend.app.repositories.edit_session_repository import EditSessionRepository
from backend.app.schemas.edit_session import (
    ActiveDocumentState,
    CheckpointState,
    DocumentSnapshot,
    EditableEdge,
    EditableSegment,
    RenderProfile,
    SegmentGroup,
    VoiceBinding,
)
from backend.app.services.block_planner import BlockPlanner
from backend.app.services.composition_builder import CompositionBuilder
from backend.app.services.edit_asset_store import EditAssetStore
from backend.app.services.render_config_resolver import RenderConfigResolver
from backend.app.services.timeline_manifest_service import TimelineManifestService
from backend.app.inference.block_adapter_registry import AdapterRegistry
from backend.app.tts_registry.model_registry import ModelRegistry
from backend.app.tts_registry.secret_store import SecretStore


class CheckpointService:
    def __init__(
        self,
        *,
        repository: EditSessionRepository,
        asset_store: EditAssetStore,
        gateway: EditableInferenceGateway,
        block_planner: BlockPlanner | None = None,
        composition_builder: CompositionBuilder | None = None,
        timeline_manifest_service: TimelineManifestService | None = None,
        model_registry: ModelRegistry | None = None,
        adapter_registry: AdapterRegistry | None = None,
        secret_store: SecretStore | None = None,
    ) -> None:
        self._repository = repository
        self._asset_store = asset_store
        self._gateway = gateway
        self._block_planner = block_planner or BlockPlanner()
        self._composition_builder = composition_builder or CompositionBuilder()
        self._timeline_manifest_service = timeline_manifest_service or TimelineManifestService()
        self._render_config_resolver = RenderConfigResolver(
            model_registry=model_registry,
            adapter_registry=adapter_registry,
            secret_store=secret_store,
        )

    def get_current_checkpoint(self, document_id: str) -> CheckpointState | None:
        return self._repository.get_latest_checkpoint(document_id)

    def clear_document_checkpoint(self, document_id: str) -> None:
        self._repository.delete_checkpoints_for_document(document_id)

    def save_partial_head(
        self,
        *,
        document_id: str,
        job_id: str,
        active_session: ActiveDocumentState,
        full_snapshot: DocumentSnapshot,
        resolve_boundary_context: Callable[[EditableEdge], ReferenceContext],
        segment_assets: dict[str, SegmentRenderAssetPayload],
        boundary_assets: dict[str, BoundaryAssetPayload],
        status: str,
    ) -> tuple[CheckpointState, DocumentSnapshot]:
        completed_segments = self._collect_completed_prefix(full_snapshot.segments)
        completed_segment_ids = [segment.segment_id for segment in completed_segments]
        remaining_segment_ids = [
            segment.segment_id for segment in sorted(full_snapshot.segments, key=lambda item: item.order_key)
            if segment.segment_id not in set(completed_segment_ids)
        ]
        partial_edges = [
            edge.model_copy(deep=True)
            for edge in full_snapshot.edges
            if edge.left_segment_id in set(completed_segment_ids) and edge.right_segment_id in set(completed_segment_ids)
        ]

        partial_boundaries = self._ensure_partial_boundaries(
            full_snapshot=full_snapshot,
            edges=partial_edges,
            resolve_boundary_context=resolve_boundary_context,
            segment_assets=segment_assets,
            boundary_assets=boundary_assets,
        )
        blocks = self._block_planner.build_blocks(completed_segments)
        block_assets = []
        for block in blocks:
            block_segments = [segment_assets[segment_id] for segment_id in block.segment_ids]
            block_edges = [
                edge
                for edge in partial_edges
                if edge.left_segment_id in block.segment_ids and edge.right_segment_id in block.segment_ids
            ]
            block_boundaries = [
                partial_boundaries[edge.edge_id]
                for edge in block_edges
                if edge.edge_id in partial_boundaries
            ]
            block_asset = self._composition_builder.compose_block(
                segments=block_segments,
                boundaries=block_boundaries,
                edges=block_edges,
                block_id=block.block_id,
            )
            self._write_block_asset(block_asset)
            block_assets.append(block_asset)

        next_document_version = self._resolve_next_document_version(
            active_session=active_session,
            snapshot=full_snapshot,
        )
        partial_snapshot = self._build_partial_snapshot(
            document_id=document_id,
            document_version=next_document_version,
            segments=completed_segments,
            edges=partial_edges,
            groups=full_snapshot.groups,
            render_profiles=full_snapshot.render_profiles,
            voice_bindings=full_snapshot.voice_bindings,
            default_render_profile_id=full_snapshot.default_render_profile_id,
            default_voice_binding_id=full_snapshot.default_voice_binding_id,
        )
        timeline_manifest, _ = self._timeline_manifest_service.build(
            snapshot=partial_snapshot,
            blocks=block_assets,
            sample_rate=self._composition_builder._sample_rate,  # noqa: SLF001
        )
        self._asset_store.write_formal_json_atomic(
            f"timelines/{timeline_manifest.timeline_manifest_id}/manifest.json",
            timeline_manifest.model_dump(mode="json"),
        )
        partial_snapshot = partial_snapshot.model_copy(
            deep=True,
            update={
                "block_ids": [entry.block_asset_id for entry in timeline_manifest.block_entries],
                "timeline_manifest_id": timeline_manifest.timeline_manifest_id,
            },
        )

        working_snapshot = full_snapshot.model_copy(
            deep=True,
            update={
                "snapshot_id": f"checkpoint-working-{uuid4().hex}",
                "snapshot_kind": "staging",
                "document_version": next_document_version,
            },
        )
        self._repository.save_snapshot(partial_snapshot)
        self._repository.save_snapshot(working_snapshot)

        checkpoint = CheckpointState(
            checkpoint_id=f"checkpoint-{uuid4().hex}",
            document_id=document_id,
            job_id=job_id,
            document_version=partial_snapshot.document_version,
            head_snapshot_id=partial_snapshot.snapshot_id,
            timeline_manifest_id=timeline_manifest.timeline_manifest_id,
            working_snapshot_id=working_snapshot.snapshot_id,
            next_segment_cursor=len(completed_segment_ids),
            completed_segment_ids=completed_segment_ids,
            remaining_segment_ids=remaining_segment_ids,
            status=status,
            resume_token=(f"resume-{uuid4().hex}" if status == "paused" else None),
            updated_at=datetime.now(timezone.utc),
        )
        self._repository.save_checkpoint(checkpoint)
        return checkpoint, partial_snapshot

    @staticmethod
    def _collect_completed_prefix(segments: list[EditableSegment]) -> list[EditableSegment]:
        prefix: list[EditableSegment] = []
        for segment in sorted(segments, key=lambda item: item.order_key):
            if segment.render_asset_id is None or segment.render_status != "ready":
                break
            prefix.append(segment.model_copy(deep=True))
        return prefix

    def _ensure_partial_boundaries(
        self,
        *,
        full_snapshot: DocumentSnapshot,
        edges: list[EditableEdge],
        resolve_boundary_context: Callable[[EditableEdge], ReferenceContext],
        segment_assets: dict[str, SegmentRenderAssetPayload],
        boundary_assets: dict[str, BoundaryAssetPayload],
    ) -> dict[str, BoundaryAssetPayload]:
        snapshot = full_snapshot.model_copy(deep=True)
        ensured: dict[str, BoundaryAssetPayload] = {}
        for edge in edges:
            existing = boundary_assets.get(edge.edge_id)
            if existing is not None:
                ensured[edge.edge_id] = existing
                continue
            resolved_edge = self._render_config_resolver.resolve_edge(snapshot=snapshot, edge_id=edge.edge_id)
            boundary_asset = self._gateway.render_boundary_asset(
                segment_assets[edge.left_segment_id],
                segment_assets[edge.right_segment_id],
                edge.model_copy(update={"boundary_strategy": resolved_edge.effective_boundary_strategy}),
                resolve_boundary_context(edge),
            )
            updated_edge = edge.model_copy(
                update={
                    "effective_boundary_strategy": resolved_edge.effective_boundary_strategy,
                    "boundary_sample_count": boundary_asset.boundary_sample_count,
                    "pause_sample_count": int(self._composition_builder._sample_rate * edge.pause_duration_seconds),  # noqa: SLF001
                },
            )
            edge.effective_boundary_strategy = updated_edge.effective_boundary_strategy
            edge.boundary_sample_count = updated_edge.boundary_sample_count
            edge.pause_sample_count = updated_edge.pause_sample_count
            ensured[edge.edge_id] = boundary_asset
            self._write_boundary_asset(boundary_asset)
        return ensured

    @staticmethod
    def _resolve_next_document_version(*, active_session: ActiveDocumentState, snapshot: DocumentSnapshot) -> int:
        current_version = 0
        if active_session.head_snapshot_id is not None:
            current_version = snapshot.document_version - 1
        return max(snapshot.document_version, current_version + 1)

    def _build_partial_snapshot(
        self,
        *,
        document_id: str,
        document_version: int,
        segments: list[EditableSegment],
        edges: list[EditableEdge],
        groups: list[SegmentGroup],
        render_profiles: list[RenderProfile],
        voice_bindings: list[VoiceBinding],
        default_render_profile_id: str | None,
        default_voice_binding_id: str | None,
    ) -> DocumentSnapshot:
        return DocumentSnapshot(
            snapshot_id=f"head-{uuid4().hex}",
            document_id=document_id,
            snapshot_kind="head",
            document_version=document_version,
            segment_ids=[segment.segment_id for segment in segments],
            edge_ids=[edge.edge_id for edge in edges],
            block_ids=[],
            groups=[group.model_copy(deep=True) for group in groups],
            render_profiles=[profile.model_copy(deep=True) for profile in render_profiles],
            voice_bindings=[binding.model_copy(deep=True) for binding in voice_bindings],
            default_render_profile_id=default_render_profile_id,
            default_voice_binding_id=default_voice_binding_id,
            timeline_manifest_id=None,
            segments=[segment.model_copy(deep=True) for segment in segments],
            edges=[edge.model_copy(deep=True) for edge in edges],
        )

    def _write_boundary_asset(self, asset: BoundaryAssetPayload) -> None:
        wav_bytes = build_wav_bytes(
            self._composition_builder._sample_rate,  # noqa: SLF001
            float_audio_chunk_to_pcm16_bytes(asset.boundary_audio.astype(np.float32, copy=False)),
        )
        self._asset_store.write_formal_bytes_atomic(f"boundaries/{asset.boundary_asset_id}/audio.wav", wav_bytes)
        self._asset_store.write_formal_json_atomic(
            f"boundaries/{asset.boundary_asset_id}/metadata.json",
            {
                "boundary_asset_id": asset.boundary_asset_id,
                "left_segment_id": asset.left_segment_id,
                "left_render_version": asset.left_render_version,
                "right_segment_id": asset.right_segment_id,
                "right_render_version": asset.right_render_version,
                "edge_version": asset.edge_version,
                "boundary_strategy": asset.boundary_strategy,
                "boundary_sample_count": asset.boundary_sample_count,
                "trace": asset.trace,
            },
        )

    def _write_block_asset(self, asset) -> None:
        wav_bytes = build_wav_bytes(
            asset.sample_rate,
            float_audio_chunk_to_pcm16_bytes(asset.audio.astype(np.float32, copy=False)),
        )
        self._asset_store.write_formal_bytes_atomic(f"blocks/{asset.block_asset_id}/audio.wav", wav_bytes)
        self._asset_store.write_formal_json_atomic(
            f"blocks/{asset.block_asset_id}/metadata.json",
            {
                "block_id": asset.block_id,
                "block_asset_id": asset.block_asset_id,
                "segment_ids": asset.segment_ids,
                "audio_sample_count": asset.audio_sample_count,
                "segment_entries": [
                    {
                        "segment_id": entry.segment_id,
                        "audio_sample_span": list(entry.audio_sample_span),
                        "order_key": entry.order_key,
                        "render_asset_id": entry.render_asset_id,
                    }
                    for entry in asset.segment_entries
                ],
                "edge_entries": [
                    {
                        "edge_id": entry.edge_id,
                        "left_segment_id": entry.left_segment_id,
                        "right_segment_id": entry.right_segment_id,
                        "boundary_strategy": entry.boundary_strategy,
                        "effective_boundary_strategy": entry.effective_boundary_strategy,
                        "pause_duration_seconds": entry.pause_duration_seconds,
                        "boundary_sample_span": list(entry.boundary_sample_span),
                        "pause_sample_span": list(entry.pause_sample_span),
                    }
                    for entry in asset.edge_entries
                ],
                "marker_entries": [
                    {
                        "marker_type": entry.marker_type,
                        "sample": entry.sample,
                        "related_id": entry.related_id,
                    }
                    for entry in asset.marker_entries
                ],
            },
        )
