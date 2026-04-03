from backend.app.inference.editable_types import DocumentCompositionManifestPayload, SegmentCompositionEntry
from backend.app.schemas.edit_session import EditableSegment
from backend.app.services.playback_map_service import PlaybackMapService


def test_rebuild_playback_map_uses_manifest_spans_and_segment_order():
    service = PlaybackMapService()
    manifest = DocumentCompositionManifestPayload(
        composition_manifest_id="comp-1",
        document_id="doc-1",
        document_version=2,
        sample_rate=32000,
        audio_sample_count=12,
        playable_sample_span=(0, 12),
        block_ids=["block-1"],
        block_spans={"block-1": (0, 12)},
        segment_entries=[
            SegmentCompositionEntry(segment_id="seg-2", order_key=2, audio_sample_span=(6, 12)),
            SegmentCompositionEntry(segment_id="seg-1", order_key=1, audio_sample_span=(0, 6)),
        ],
        audio=None,
    )
    segments = [
        EditableSegment(
            segment_id="seg-2",
            document_id="doc-1",
            order_key=2,
            raw_text="第二句。",
            normalized_text="第二句。",
            text_language="zh",
        ),
        EditableSegment(
            segment_id="seg-1",
            document_id="doc-1",
            order_key=1,
            raw_text="第一句。",
            normalized_text="第一句。",
            text_language="zh",
        ),
    ]

    playback_map = service.rebuild(manifest=manifest, segments=segments)

    assert playback_map.document_id == "doc-1"
    assert playback_map.document_version == 2
    assert playback_map.composition_manifest_id == "comp-1"
    assert playback_map.playable_sample_span == (0, 12)
    assert [entry.segment_id for entry in playback_map.entries] == ["seg-1", "seg-2"]
    assert playback_map.entries[0].audio_sample_span == (0, 6)
    assert playback_map.entries[1].audio_sample_span == (6, 12)
