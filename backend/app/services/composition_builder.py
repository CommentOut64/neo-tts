from __future__ import annotations

import hashlib
import json
from uuid import uuid4

import numpy as np

from backend.app.inference.editable_types import (
    BlockCompositionAssetPayload,
    BlockMarkerEntry,
    BoundaryAssetPayload,
    DocumentCompositionManifestPayload,
    EdgeCompositionEntry,
    PreviewPayload,
    SegmentCompositionEntry,
    SegmentRenderAssetPayload,
)
from backend.app.schemas.edit_session import EditableEdge


class CompositionBuilder:
    def __init__(self, *, sample_rate: int = 32000) -> None:
        self._sample_rate = sample_rate

    @staticmethod
    def _resolve_uniform_sample_rate(
        sample_rates: list[int],
        *,
        context: str,
        fallback_sample_rate: int,
    ) -> int:
        filtered = [int(sample_rate) for sample_rate in sample_rates if int(sample_rate) > 0]
        if not filtered:
            return fallback_sample_rate
        first_sample_rate = filtered[0]
        if any(sample_rate != first_sample_rate for sample_rate in filtered[1:]):
            raise ValueError(f"{context} sample rates must match exactly.")
        return first_sample_rate

    def compose_block(
        self,
        segments: list[SegmentRenderAssetPayload],
        boundaries: list[BoundaryAssetPayload],
        edges: list[EditableEdge],
        *,
        block_id: str | None = None,
        block_asset_id: str | None = None,
        segment_alignment_mode: str | None = None,
        join_report_summary: dict | None = None,
        segment_entry_asset_ids: dict[str, str | None] | None = None,
        segment_entry_base_asset_ids: dict[str, str | None] | None = None,
    ) -> BlockCompositionAssetPayload:
        if not segments:
            raise ValueError("compose_block requires at least one segment asset.")

        block_sample_rate = self._resolve_uniform_sample_rate(
            [segment.sample_rate for segment in segments],
            context="segment asset",
            fallback_sample_rate=self._sample_rate,
        )
        if boundaries:
            self._resolve_uniform_sample_rate(
                [boundary.sample_rate for boundary in boundaries] + [block_sample_rate],
                context="block asset",
                fallback_sample_rate=block_sample_rate,
            )

        logical_block_id = block_id or f"block-{uuid4().hex}"
        effective_alignment_mode = segment_alignment_mode or "exact"
        if len(segments) == 1:
            only_segment = segments[0]
            audio = self._full_segment_audio(only_segment)
            segment_entries = [
                SegmentCompositionEntry(
                    segment_id=only_segment.segment_id,
                    audio_sample_span=(0, int(audio.size)),
                    render_asset_id=self._resolve_segment_entry_asset_id(
                        only_segment.segment_id,
                        only_segment.render_asset_id,
                        segment_entry_asset_ids,
                    ),
                    base_render_asset_id=self._resolve_segment_entry_asset_id(
                        only_segment.segment_id,
                        only_segment.render_asset_id,
                        segment_entry_base_asset_ids,
                    ),
                    precision="exact",
                    source="adapter_exact",
                )
            ]
            marker_entries = [
                BlockMarkerEntry(marker_type="block_start", sample=0, related_id=logical_block_id),
                BlockMarkerEntry(marker_type="segment_start", sample=0, related_id=only_segment.segment_id),
                BlockMarkerEntry(marker_type="segment_end", sample=int(audio.size), related_id=only_segment.segment_id),
                BlockMarkerEntry(marker_type="block_end", sample=int(audio.size), related_id=logical_block_id),
            ]
            return BlockCompositionAssetPayload(
                block_id=logical_block_id,
                block_asset_id=block_asset_id
                or self._build_block_asset_id(
                    block_id=logical_block_id,
                    segments=segment_entries,
                    edges=[],
                    sample_rate=block_sample_rate,
                ),
                segment_ids=[only_segment.segment_id],
                sample_rate=block_sample_rate,
                audio=audio,
                audio_sample_count=int(audio.size),
                segment_entries=segment_entries,
                segment_alignment_mode=effective_alignment_mode,
                join_report_summary=join_report_summary,
                edge_entries=[],
                marker_entries=marker_entries,
            )

        boundary_map = {(boundary.left_segment_id, boundary.right_segment_id): boundary for boundary in boundaries}
        audio_parts: list[np.ndarray] = []
        segment_entries: list[SegmentCompositionEntry] = []
        edge_entries: list[EdgeCompositionEntry] = []
        marker_entries: list[BlockMarkerEntry] = [
            BlockMarkerEntry(marker_type="block_start", sample=0, related_id=logical_block_id)
        ]
        cursor = 0

        first = segments[0]
        first_owned_audio = np.concatenate([first.left_margin_audio, first.core_audio]).astype(np.float32, copy=False)
        audio_parts.append(first_owned_audio)
        cursor = int(first_owned_audio.size)
        marker_entries.append(BlockMarkerEntry(marker_type="segment_start", sample=0, related_id=first.segment_id))
        segment_entries.append(
            SegmentCompositionEntry(
                segment_id=first.segment_id,
                audio_sample_span=(0, cursor),
                render_asset_id=self._resolve_segment_entry_asset_id(
                    first.segment_id,
                    first.render_asset_id,
                    segment_entry_asset_ids,
                ),
                base_render_asset_id=self._resolve_segment_entry_asset_id(
                    first.segment_id,
                    first.render_asset_id,
                    segment_entry_base_asset_ids,
                ),
                precision="exact",
                source="adapter_exact",
            )
        )
        marker_entries.append(BlockMarkerEntry(marker_type="segment_end", sample=cursor, related_id=first.segment_id))

        for index, edge in enumerate(edges):
            right_segment = segments[index + 1]
            boundary = boundary_map.get((edge.left_segment_id, edge.right_segment_id))
            boundary_audio = boundary.boundary_audio if boundary is not None else None
            pause_audio = self._pause_audio(edge.pause_duration_seconds, sample_rate=block_sample_rate)
            owned_audio = right_segment.core_audio
            if index == len(edges) - 1:
                owned_audio = np.concatenate([owned_audio, right_segment.right_margin_audio]).astype(
                    np.float32,
                    copy=False,
                )

            boundary_start = cursor
            boundary_end = boundary_start + (0 if boundary_audio is None else int(boundary_audio.size))
            pause_start = boundary_end
            pause_end = pause_start + int(pause_audio.size)
            start = pause_end
            end = start + int(owned_audio.size)

            if boundary_audio is not None and boundary_audio.size > 0:
                audio_parts.append(boundary_audio.astype(np.float32, copy=False))
                cursor += int(boundary_audio.size)
            if pause_audio.size > 0:
                audio_parts.append(pause_audio)
                cursor += int(pause_audio.size)

            audio_parts.append(owned_audio.astype(np.float32, copy=False))
            cursor += int(owned_audio.size)
            edge_entries.append(
                EdgeCompositionEntry(
                    edge_id=edge.edge_id,
                    left_segment_id=edge.left_segment_id,
                    right_segment_id=edge.right_segment_id,
                    boundary_strategy=edge.boundary_strategy,
                    effective_boundary_strategy=edge.effective_boundary_strategy or edge.boundary_strategy,
                    pause_duration_seconds=edge.pause_duration_seconds,
                    boundary_sample_span=(boundary_start, boundary_end),
                    pause_sample_span=(pause_start, pause_end),
                )
            )
            if pause_end > pause_start:
                marker_entries.append(
                    BlockMarkerEntry(marker_type="edge_gap_start", sample=pause_start, related_id=edge.edge_id)
                )
                marker_entries.append(
                    BlockMarkerEntry(marker_type="edge_gap_end", sample=pause_end, related_id=edge.edge_id)
                )
            marker_entries.append(
                BlockMarkerEntry(marker_type="segment_start", sample=start, related_id=right_segment.segment_id)
            )
            segment_entries.append(
                SegmentCompositionEntry(
                    segment_id=right_segment.segment_id,
                    audio_sample_span=(start, end),
                    render_asset_id=self._resolve_segment_entry_asset_id(
                        right_segment.segment_id,
                        right_segment.render_asset_id,
                        segment_entry_asset_ids,
                    ),
                    base_render_asset_id=self._resolve_segment_entry_asset_id(
                        right_segment.segment_id,
                        right_segment.render_asset_id,
                        segment_entry_base_asset_ids,
                    ),
                    precision="exact",
                    source="adapter_exact",
                )
            )
            marker_entries.append(
                BlockMarkerEntry(marker_type="segment_end", sample=end, related_id=right_segment.segment_id)
            )

        audio = np.concatenate(audio_parts) if audio_parts else np.zeros(0, dtype=np.float32)
        marker_entries.append(
            BlockMarkerEntry(marker_type="block_end", sample=int(audio.size), related_id=logical_block_id)
        )
        return BlockCompositionAssetPayload(
            block_id=logical_block_id,
            block_asset_id=block_asset_id
            or self._build_block_asset_id(
                block_id=logical_block_id,
                segments=segment_entries,
                edges=edge_entries,
                sample_rate=block_sample_rate,
            ),
            segment_ids=[segment.segment_id for segment in segments],
            sample_rate=block_sample_rate,
            audio=audio.astype(np.float32, copy=False),
            audio_sample_count=int(audio.size),
            segment_entries=segment_entries,
            segment_alignment_mode=effective_alignment_mode,
            join_report_summary=join_report_summary,
            edge_entries=edge_entries,
            marker_entries=marker_entries,
        )

    def compose_document(
        self,
        *,
        document_id: str,
        document_version: int,
        blocks: list[BlockCompositionAssetPayload],
    ) -> DocumentCompositionManifestPayload:
        document_sample_rate = self._resolve_uniform_sample_rate(
            [block.sample_rate for block in blocks],
            context="block composition asset",
            fallback_sample_rate=self._sample_rate,
        )
        block_spans: dict[str, tuple[int, int]] = {}
        segment_entries: list[SegmentCompositionEntry] = []
        audio_parts: list[np.ndarray] = []
        cursor = 0

        for block in blocks:
            block_start = cursor
            if block.audio.size > 0:
                audio_parts.append(block.audio.astype(np.float32, copy=False))
                cursor += int(block.audio.size)
            block_spans[block.block_asset_id] = (block_start, cursor)
            for entry in block.segment_entries:
                segment_entries.append(
                    SegmentCompositionEntry(
                        segment_id=entry.segment_id,
                        order_key=entry.order_key,
                        audio_sample_span=(
                            block_start + entry.audio_sample_span[0],
                            block_start + entry.audio_sample_span[1],
                        ),
                        render_asset_id=entry.render_asset_id,
                        base_render_asset_id=entry.base_render_asset_id,
                    )
                )

        audio = np.concatenate(audio_parts) if audio_parts else np.zeros(0, dtype=np.float32)
        return DocumentCompositionManifestPayload(
            composition_manifest_id=f"composition-{uuid4().hex}",
            document_id=document_id,
            document_version=document_version,
            sample_rate=document_sample_rate,
            audio_sample_count=int(audio.size),
            playable_sample_span=(0, int(audio.size)),
            block_ids=[block.block_asset_id for block in blocks],
            block_spans=block_spans,
            segment_entries=segment_entries,
            audio=audio.astype(np.float32, copy=False),
        )

    def build_preview(
        self,
        *,
        segment_asset: SegmentRenderAssetPayload | None = None,
        boundary_asset: BoundaryAssetPayload | None = None,
        block_asset: BlockCompositionAssetPayload | None = None,
    ) -> PreviewPayload:
        chosen = [segment_asset, boundary_asset, block_asset]
        if sum(item is not None for item in chosen) != 1:
            raise ValueError("Exactly one preview target must be provided.")

        if segment_asset is not None:
            return PreviewPayload(
                preview_asset_id=f"preview-segment-{segment_asset.render_asset_id}",
                preview_kind="segment",
                sample_rate=segment_asset.sample_rate,
                audio=self._full_segment_audio(segment_asset),
            )
        if boundary_asset is not None:
            return PreviewPayload(
                preview_asset_id=f"preview-edge-{boundary_asset.boundary_asset_id}",
                preview_kind="edge",
                sample_rate=boundary_asset.sample_rate,
                audio=boundary_asset.boundary_audio.astype(np.float32, copy=False),
            )
        assert block_asset is not None
        return PreviewPayload(
            preview_asset_id=f"preview-block-{block_asset.block_asset_id}",
            preview_kind="block",
            sample_rate=block_asset.sample_rate,
            audio=block_asset.audio.astype(np.float32, copy=False),
        )

    def _full_segment_audio(self, segment: SegmentRenderAssetPayload) -> np.ndarray:
        return np.concatenate([segment.left_margin_audio, segment.core_audio, segment.right_margin_audio]).astype(
            np.float32,
            copy=False,
        )

    def _pause_audio(self, pause_duration_seconds: float, *, sample_rate: int) -> np.ndarray:
        if pause_duration_seconds <= 0:
            return np.zeros(0, dtype=np.float32)
        return np.zeros(int(sample_rate * pause_duration_seconds), dtype=np.float32)

    @staticmethod
    def _resolve_segment_entry_asset_id(
        segment_id: str,
        fallback_asset_id: str | None,
        overrides: dict[str, str | None] | None,
    ) -> str | None:
        if overrides is None:
            return fallback_asset_id
        return overrides.get(segment_id, fallback_asset_id)

    @staticmethod
    def _build_block_asset_id(
        *,
        block_id: str,
        segments: list[SegmentCompositionEntry],
        edges: list[EdgeCompositionEntry],
        sample_rate: int,
    ) -> str:
        payload = {
            "block_id": block_id,
            "sample_rate": sample_rate,
            "segments": [
                {
                    "segment_id": entry.segment_id,
                    "audio_sample_span": list(entry.audio_sample_span),
                    "render_asset_id": entry.render_asset_id,
                    "base_render_asset_id": entry.base_render_asset_id,
                }
                for entry in segments
            ],
            "edges": [
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
                for entry in edges
            ],
        }
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        digest = hashlib.sha1(encoded.encode("utf-8")).hexdigest()[:16]
        return f"{block_id}-{digest}"
