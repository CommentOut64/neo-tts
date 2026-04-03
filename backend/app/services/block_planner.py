from __future__ import annotations

import hashlib

from backend.app.inference.editable_types import RenderBlock
from backend.app.schemas.edit_session import EditableSegment


class BlockPlanner:
    def __init__(
        self,
        *,
        sample_rate: int = 32000,
        min_block_seconds: int = 20,
        max_block_seconds: int = 40,
        max_segment_count: int = 50,
    ) -> None:
        self._min_block_samples = sample_rate * min_block_seconds
        self._max_block_samples = sample_rate * max_block_seconds
        self._max_segment_count = max_segment_count

    def build_blocks(self, segments: list[EditableSegment]) -> list[RenderBlock]:
        if not segments:
            return []

        ordered_segments = sorted(segments, key=lambda item: item.order_key)
        blocks: list[RenderBlock] = []
        current_segments: list[EditableSegment] = []
        current_sample_count = 0

        for segment in ordered_segments:
            segment_sample_count = self._segment_sample_count(segment)
            should_split = bool(
                current_segments
                and (
                    len(current_segments) >= self._max_segment_count
                    or current_sample_count + segment_sample_count > self._max_block_samples
                    or current_sample_count >= self._min_block_samples
                )
            )
            if should_split:
                blocks.append(self._build_block(current_segments, current_sample_count))
                current_segments = []
                current_sample_count = 0

            current_segments.append(segment)
            current_sample_count += segment_sample_count

        if current_segments:
            blocks.append(self._build_block(current_segments, current_sample_count))
        return blocks

    def affected_blocks(self, *, changed_segment_ids: set[str], all_blocks: list[RenderBlock]) -> set[str]:
        if not changed_segment_ids:
            return set()
        affected: set[str] = set()
        for block in all_blocks:
            if changed_segment_ids.intersection(block.segment_ids):
                affected.add(block.block_id)
        return affected

    @staticmethod
    def _segment_sample_count(segment: EditableSegment) -> int:
        if segment.assembled_audio_span is None:
            return 0
        return max(0, segment.assembled_audio_span[1] - segment.assembled_audio_span[0])

    @staticmethod
    def _build_block(
        segments: list[EditableSegment],
        sample_count: int,
    ) -> RenderBlock:
        first = segments[0]
        last = segments[-1]
        segment_ids = [segment.segment_id for segment in segments]
        block_digest = hashlib.sha1(",".join(segment_ids).encode("utf-8")).hexdigest()[:12]
        return RenderBlock(
            block_id=f"block-{block_digest}",
            segment_ids=segment_ids,
            start_order_key=first.order_key,
            end_order_key=last.order_key,
            estimated_sample_count=sample_count,
        )
