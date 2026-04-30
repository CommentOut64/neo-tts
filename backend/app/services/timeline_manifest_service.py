from __future__ import annotations

from uuid import uuid4

from backend.app.inference.editable_types import BlockCompositionAssetPayload
from backend.app.schemas.edit_session import (
    DocumentSnapshot,
    PlaybackMapEntry,
    PlaybackMapResponse,
    TimelineBlockEntry,
    TimelineEdgeEntry,
    TimelineManifest,
    TimelineMarkerEntry,
    TimelineSegmentEntry,
)


class TimelineManifestService:
    def build(
        self,
        *,
        snapshot: DocumentSnapshot,
        blocks: list[BlockCompositionAssetPayload],
        sample_rate: int,
    ) -> tuple[TimelineManifest, PlaybackMapResponse]:
        segment_by_id = {segment.segment_id: segment for segment in snapshot.segments}
        edge_by_id = {edge.edge_id: edge for edge in snapshot.edges}
        block_entries: list[TimelineBlockEntry] = []
        segment_entries: list[TimelineSegmentEntry] = []
        edge_entries: list[TimelineEdgeEntry] = []
        markers: list[TimelineMarkerEntry] = []
        playback_entries: list[PlaybackMapEntry] = []
        cursor = 0

        for block in blocks:
            block_start = cursor
            block_end = block_start + block.audio_sample_count
            block_entries.append(
                TimelineBlockEntry(
                    block_asset_id=block.block_asset_id,
                    segment_ids=list(block.segment_ids),
                    start_sample=block_start,
                    end_sample=block_end,
                    audio_sample_count=block.audio_sample_count,
                    audio_url=f"/v1/edit-session/assets/blocks/{block.block_asset_id}/audio",
                    segment_alignment_mode=block.segment_alignment_mode,
                    join_report_summary=block.join_report_summary,
                )
            )
            for entry in block.segment_entries:
                segment = segment_by_id.get(entry.segment_id)
                absolute_start = block_start + entry.audio_sample_span[0]
                absolute_end = block_start + entry.audio_sample_span[1]
                segment_entries.append(
                    TimelineSegmentEntry(
                        segment_id=entry.segment_id,
                        order_key=entry.order_key if entry.order_key else (segment.order_key if segment is not None else 0),
                        start_sample=absolute_start,
                        end_sample=absolute_end,
                        render_status=segment.render_status if segment is not None else "ready",
                        group_id=segment.group_id if segment is not None else None,
                        render_profile_id=segment.render_profile_id if segment is not None else None,
                        voice_binding_id=segment.voice_binding_id if segment is not None else None,
                        alignment_precision=entry.precision,
                        source=entry.source,
                    )
                )
                playback_entries.append(
                    PlaybackMapEntry(
                        segment_id=entry.segment_id,
                        order_key=entry.order_key if entry.order_key else (segment.order_key if segment is not None else 0),
                        audio_sample_span=(absolute_start, absolute_end),
                    )
                )
            for entry in block.edge_entries:
                edge = edge_by_id.get(entry.edge_id)
                edge_entries.append(
                    TimelineEdgeEntry(
                        edge_id=entry.edge_id,
                        left_segment_id=entry.left_segment_id,
                        right_segment_id=entry.right_segment_id,
                        pause_duration_seconds=entry.pause_duration_seconds,
                        boundary_strategy=edge.boundary_strategy if edge is not None else entry.boundary_strategy,
                        effective_boundary_strategy=entry.effective_boundary_strategy,
                        boundary_start_sample=block_start + entry.boundary_sample_span[0],
                        boundary_end_sample=block_start + entry.boundary_sample_span[1],
                        pause_start_sample=block_start + entry.pause_sample_span[0],
                        pause_end_sample=block_start + entry.pause_sample_span[1],
                    )
                )
            for index, marker in enumerate(block.marker_entries, start=1):
                markers.append(
                    TimelineMarkerEntry(
                        marker_id=f"{block.block_asset_id}:{marker.marker_type}:{index}",
                        marker_type=marker.marker_type,
                        sample=block_start + marker.sample,
                        related_id=marker.related_id,
                    )
                )
            cursor = block_end

        segment_entries.sort(key=lambda item: (item.order_key, item.start_sample, item.segment_id))
        playback_entries.sort(key=lambda item: (item.order_key, item.audio_sample_span[0], item.segment_id))
        edge_entries.sort(key=lambda item: (item.boundary_start_sample, item.edge_id))
        markers.sort(key=lambda item: (item.sample, item.marker_type, item.related_id))

        timeline = TimelineManifest(
            timeline_manifest_id=f"timeline-{uuid4().hex}",
            document_id=snapshot.document_id,
            document_version=snapshot.document_version,
            timeline_version=snapshot.document_version,
            sample_rate=sample_rate,
            playable_sample_span=(0, cursor),
            block_entries=block_entries,
            segment_entries=segment_entries,
            edge_entries=edge_entries,
            markers=markers,
        )
        playback_map = PlaybackMapResponse(
            document_id=snapshot.document_id,
            document_version=snapshot.document_version,
            composition_manifest_id=snapshot.composition_manifest_id,
            playable_sample_span=timeline.playable_sample_span,
            entries=playback_entries,
        )
        return timeline, playback_map
