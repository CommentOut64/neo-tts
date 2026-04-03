from __future__ import annotations

from uuid import uuid4

import numpy as np

from backend.app.inference.editable_types import (
    BlockCompositionAssetPayload,
    BoundaryAssetPayload,
    DocumentCompositionManifestPayload,
    PreviewPayload,
    SegmentCompositionEntry,
    SegmentRenderAssetPayload,
)
from backend.app.schemas.edit_session import EditableEdge


class CompositionBuilder:
    def __init__(self, *, sample_rate: int = 32000) -> None:
        self._sample_rate = sample_rate

    def compose_block(
        self,
        segments: list[SegmentRenderAssetPayload],
        boundaries: list[BoundaryAssetPayload],
        edges: list[EditableEdge],
        *,
        block_id: str | None = None,
    ) -> BlockCompositionAssetPayload:
        if not segments:
            raise ValueError("compose_block requires at least one segment asset.")

        if len(segments) == 1:
            only_segment = segments[0]
            audio = self._full_segment_audio(only_segment)
            return BlockCompositionAssetPayload(
                block_id=block_id or f"block-{uuid4().hex}",
                segment_ids=[only_segment.segment_id],
                sample_rate=self._sample_rate,
                audio=audio,
                audio_sample_count=int(audio.size),
                segment_entries=[
                    SegmentCompositionEntry(
                        segment_id=only_segment.segment_id,
                        audio_sample_span=(0, int(audio.size)),
                    )
                ],
            )

        boundary_map = {
            (boundary.left_segment_id, boundary.right_segment_id): boundary for boundary in boundaries
        }
        audio_parts: list[np.ndarray] = []
        segment_entries: list[SegmentCompositionEntry] = []
        cursor = 0

        first = segments[0]
        first_owned_audio = np.concatenate([first.left_margin_audio, first.core_audio]).astype(np.float32, copy=False)
        audio_parts.append(first_owned_audio)
        cursor = int(first_owned_audio.size)
        segment_entries.append(
            SegmentCompositionEntry(
                segment_id=first.segment_id,
                audio_sample_span=(0, cursor),
            )
        )

        for index, edge in enumerate(edges):
            right_segment = segments[index + 1]
            boundary = boundary_map.get((edge.left_segment_id, edge.right_segment_id))
            boundary_audio = boundary.boundary_audio if boundary is not None else None
            pause_audio = self._pause_audio(edge.pause_duration_seconds)
            owned_audio = right_segment.core_audio
            if index == len(edges) - 1:
                owned_audio = np.concatenate([owned_audio, right_segment.right_margin_audio]).astype(
                    np.float32,
                    copy=False,
                )

            start = cursor + (0 if boundary_audio is None else int(boundary_audio.size)) + int(pause_audio.size)
            end = start + int(owned_audio.size)

            if boundary_audio is not None and boundary_audio.size > 0:
                audio_parts.append(boundary_audio.astype(np.float32, copy=False))
                cursor += int(boundary_audio.size)
            if pause_audio.size > 0:
                audio_parts.append(pause_audio)
                cursor += int(pause_audio.size)

            audio_parts.append(owned_audio.astype(np.float32, copy=False))
            cursor += int(owned_audio.size)
            segment_entries.append(
                SegmentCompositionEntry(
                    segment_id=right_segment.segment_id,
                    audio_sample_span=(start, end),
                )
            )

        audio = np.concatenate(audio_parts) if audio_parts else np.zeros(0, dtype=np.float32)
        return BlockCompositionAssetPayload(
            block_id=block_id or f"block-{uuid4().hex}",
            segment_ids=[segment.segment_id for segment in segments],
            sample_rate=self._sample_rate,
            audio=audio.astype(np.float32, copy=False),
            audio_sample_count=int(audio.size),
            segment_entries=segment_entries,
        )

    def compose_document(
        self,
        *,
        document_id: str,
        document_version: int,
        blocks: list[BlockCompositionAssetPayload],
    ) -> DocumentCompositionManifestPayload:
        block_spans: dict[str, tuple[int, int]] = {}
        segment_entries: list[SegmentCompositionEntry] = []
        audio_parts: list[np.ndarray] = []
        cursor = 0

        for block in blocks:
            block_start = cursor
            if block.audio.size > 0:
                audio_parts.append(block.audio.astype(np.float32, copy=False))
                cursor += int(block.audio.size)
            block_spans[block.block_id] = (block_start, cursor)
            for entry in block.segment_entries:
                segment_entries.append(
                    SegmentCompositionEntry(
                        segment_id=entry.segment_id,
                        order_key=entry.order_key,
                        audio_sample_span=(
                            block_start + entry.audio_sample_span[0],
                            block_start + entry.audio_sample_span[1],
                        ),
                    )
                )

        audio = np.concatenate(audio_parts) if audio_parts else np.zeros(0, dtype=np.float32)
        return DocumentCompositionManifestPayload(
            composition_manifest_id=f"composition-{uuid4().hex}",
            document_id=document_id,
            document_version=document_version,
            sample_rate=self._sample_rate,
            audio_sample_count=int(audio.size),
            playable_sample_span=(0, int(audio.size)),
            block_ids=[block.block_id for block in blocks],
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
                sample_rate=self._sample_rate,
                audio=self._full_segment_audio(segment_asset),
            )
        if boundary_asset is not None:
            return PreviewPayload(
                preview_asset_id=f"preview-edge-{boundary_asset.boundary_asset_id}",
                preview_kind="edge",
                sample_rate=self._sample_rate,
                audio=boundary_asset.boundary_audio.astype(np.float32, copy=False),
            )
        assert block_asset is not None
        return PreviewPayload(
            preview_asset_id=f"preview-block-{block_asset.block_id}",
            preview_kind="block",
            sample_rate=self._sample_rate,
            audio=block_asset.audio.astype(np.float32, copy=False),
        )

    def _full_segment_audio(self, segment: SegmentRenderAssetPayload) -> np.ndarray:
        return np.concatenate(
            [segment.left_margin_audio, segment.core_audio, segment.right_margin_audio]
        ).astype(np.float32, copy=False)

    def _pause_audio(self, pause_duration_seconds: float) -> np.ndarray:
        if pause_duration_seconds <= 0:
            return np.zeros(0, dtype=np.float32)
        return np.zeros(int(self._sample_rate * pause_duration_seconds), dtype=np.float32)
