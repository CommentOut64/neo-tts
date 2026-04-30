from datetime import datetime, timezone

import numpy as np

from backend.app.inference.editable_types import (
    BlockCompositionAssetPayload,
    BlockMarkerEntry,
    EdgeCompositionEntry,
    SegmentCompositionEntry,
)
from backend.app.schemas.edit_session import (
    DocumentSnapshot,
    EditableEdge,
    EditableSegment,
)
from backend.app.services.timeline_manifest_service import TimelineManifestService


def test_build_timeline_manifest_reflows_absolute_spans_and_playback_map():
    service = TimelineManifestService()
    snapshot = DocumentSnapshot(
        snapshot_id="snap-head-1",
        document_id="doc-1",
        snapshot_kind="head",
        document_version=3,
        segments=[
            EditableSegment(
                segment_id="seg-1",
                document_id="doc-1",
                order_key=1,
                stem="甲",
                text_language="zh",
                terminal_raw="。",
                terminal_source="original",
                detected_language="zh",
                inference_exclusion_reason="none",
                render_asset_id="render-1",
            ),
            EditableSegment(
                segment_id="seg-2",
                document_id="doc-1",
                order_key=2,
                stem="乙",
                text_language="zh",
                terminal_raw="。",
                terminal_source="original",
                detected_language="zh",
                inference_exclusion_reason="none",
                render_asset_id="render-2",
            ),
            EditableSegment(
                segment_id="seg-3",
                document_id="doc-1",
                order_key=3,
                stem="丙",
                text_language="zh",
                terminal_raw="。",
                terminal_source="original",
                detected_language="zh",
                inference_exclusion_reason="none",
                render_asset_id="render-3",
            ),
        ],
        edges=[
            EditableEdge(
                edge_id="edge-1-2",
                document_id="doc-1",
                left_segment_id="seg-1",
                right_segment_id="seg-2",
                pause_duration_seconds=0.5,
            ),
            EditableEdge(
                edge_id="edge-2-3",
                document_id="doc-1",
                left_segment_id="seg-2",
                right_segment_id="seg-3",
                pause_duration_seconds=0.0,
            ),
        ],
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    blocks = [
        BlockCompositionAssetPayload(
            block_id="logical-block-1",
            block_asset_id="block-asset-1",
            segment_ids=["seg-1", "seg-2"],
            sample_rate=4,
            audio=np.asarray([0.1] * 6, dtype=np.float32),
            audio_sample_count=6,
            segment_entries=[
                SegmentCompositionEntry(
                    segment_id="seg-1",
                    audio_sample_span=(0, 2),
                    order_key=1,
                    render_asset_id="render-1",
                ),
                SegmentCompositionEntry(
                    segment_id="seg-2",
                    audio_sample_span=(4, 6),
                    order_key=2,
                    render_asset_id="render-2",
                ),
            ],
            edge_entries=[
                EdgeCompositionEntry(
                    edge_id="edge-1-2",
                    left_segment_id="seg-1",
                    right_segment_id="seg-2",
                    boundary_strategy="latent_overlap_then_equal_power_crossfade",
                    effective_boundary_strategy="latent_overlap_then_equal_power_crossfade",
                    pause_duration_seconds=0.5,
                    boundary_sample_span=(2, 3),
                    pause_sample_span=(3, 4),
                )
            ],
            marker_entries=[
                BlockMarkerEntry(marker_type="block_start", sample=0, related_id="logical-block-1"),
                BlockMarkerEntry(marker_type="segment_start", sample=0, related_id="seg-1"),
                BlockMarkerEntry(marker_type="segment_end", sample=2, related_id="seg-1"),
                BlockMarkerEntry(marker_type="edge_gap_start", sample=3, related_id="edge-1-2"),
                BlockMarkerEntry(marker_type="edge_gap_end", sample=4, related_id="edge-1-2"),
                BlockMarkerEntry(marker_type="segment_start", sample=4, related_id="seg-2"),
                BlockMarkerEntry(marker_type="segment_end", sample=6, related_id="seg-2"),
                BlockMarkerEntry(marker_type="block_end", sample=6, related_id="logical-block-1"),
            ],
        ),
        BlockCompositionAssetPayload(
            block_id="logical-block-2",
            block_asset_id="block-asset-2",
            segment_ids=["seg-3"],
            sample_rate=4,
            audio=np.asarray([0.2, 0.3], dtype=np.float32),
            audio_sample_count=2,
            segment_entries=[
                SegmentCompositionEntry(
                    segment_id="seg-3",
                    audio_sample_span=(0, 2),
                    order_key=3,
                    render_asset_id="render-3",
                )
            ],
            edge_entries=[],
            marker_entries=[
                BlockMarkerEntry(marker_type="block_start", sample=0, related_id="logical-block-2"),
                BlockMarkerEntry(marker_type="segment_start", sample=0, related_id="seg-3"),
                BlockMarkerEntry(marker_type="segment_end", sample=2, related_id="seg-3"),
                BlockMarkerEntry(marker_type="block_end", sample=2, related_id="logical-block-2"),
            ],
        ),
    ]

    timeline, playback_map = service.build(snapshot=snapshot, blocks=blocks, sample_rate=4)

    assert timeline.document_id == "doc-1"
    assert timeline.document_version == 3
    assert timeline.timeline_version == 3
    assert timeline.playable_sample_span == (0, 8)
    assert [entry.block_asset_id for entry in timeline.block_entries] == ["block-asset-1", "block-asset-2"]
    assert timeline.block_entries[0].start_sample == 0
    assert timeline.block_entries[0].end_sample == 6
    assert timeline.block_entries[1].start_sample == 6
    assert timeline.block_entries[1].end_sample == 8
    assert [entry.segment_id for entry in timeline.segment_entries] == ["seg-1", "seg-2", "seg-3"]
    assert timeline.segment_entries[0].start_sample == 0
    assert timeline.segment_entries[1].start_sample == 4
    assert timeline.segment_entries[2].start_sample == 6
    assert timeline.edge_entries[0].boundary_start_sample == 2
    assert timeline.edge_entries[0].boundary_end_sample == 3
    assert timeline.edge_entries[0].pause_start_sample == 3
    assert timeline.edge_entries[0].pause_end_sample == 4
    assert {marker.marker_type for marker in timeline.markers} >= {
        "segment_start",
        "segment_end",
        "edge_gap_start",
        "edge_gap_end",
        "block_start",
        "block_end",
    }
    assert playback_map.document_id == "doc-1"
    assert playback_map.document_version == 3
    assert [entry.segment_id for entry in playback_map.entries] == ["seg-1", "seg-2", "seg-3"]
    assert playback_map.entries[1].audio_sample_span == (4, 6)

