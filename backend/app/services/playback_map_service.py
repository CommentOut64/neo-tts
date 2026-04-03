from __future__ import annotations

from backend.app.inference.editable_types import DocumentCompositionManifestPayload
from backend.app.schemas.edit_session import EditableSegment, PlaybackMapEntry, PlaybackMapResponse


class PlaybackMapService:
    def rebuild(
        self,
        *,
        manifest: DocumentCompositionManifestPayload,
        segments: list[EditableSegment],
    ) -> PlaybackMapResponse:
        span_by_segment_id = {
            entry.segment_id: entry.audio_sample_span for entry in manifest.segment_entries
        }
        ordered_segments = sorted(segments, key=lambda item: item.order_key)
        entries: list[PlaybackMapEntry] = []
        for segment in ordered_segments:
            span = span_by_segment_id.get(segment.segment_id)
            if span is None:
                continue
            entries.append(
                PlaybackMapEntry(
                    segment_id=segment.segment_id,
                    order_key=segment.order_key,
                    audio_sample_span=span,
                )
            )

        return PlaybackMapResponse(
            document_id=manifest.document_id,
            document_version=manifest.document_version,
            composition_manifest_id=manifest.composition_manifest_id,
            playable_sample_span=manifest.playable_sample_span,
            entries=entries,
        )
