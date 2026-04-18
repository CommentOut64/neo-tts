from datetime import datetime, timezone

import pytest

from backend.app.schemas.edit_session import (
    DocumentSnapshot,
    EditableSegment,
    ExportRequest,
    ExportSubtitleRequest,
    TimelineManifest,
    TimelineSegmentEntry,
)
from backend.app.services.subtitle_export_service import SubtitleExportService


def _build_subtitle_request(
    *,
    format: str = "srt",
    offset_seconds: float = 0.0,
    strip_trailing_punctuation: bool = False,
) -> ExportSubtitleRequest:
    return ExportSubtitleRequest(
        enabled=True,
        format=format,
        offset_seconds=offset_seconds,
        strip_trailing_punctuation=strip_trailing_punctuation,
    )


def _build_snapshot(*segments: tuple[str, str]) -> DocumentSnapshot:
    items = [
        EditableSegment(
            segment_id=segment_id,
            document_id="doc-1",
            order_key=index,
            raw_text=raw_text,
            text_language="zh",
            render_asset_id=f"render-{segment_id}",
        )
        for index, (segment_id, raw_text) in enumerate(segments, start=1)
    ]
    return DocumentSnapshot(
        snapshot_id="snapshot-1",
        document_id="doc-1",
        snapshot_kind="head",
        document_version=1,
        timeline_manifest_id="timeline-1",
        segments=items,
        created_at=datetime(2026, 4, 12, tzinfo=timezone.utc),
    )


def _build_timeline(*, sample_rate: int = 10, entries: list[tuple[str, int, int]]) -> TimelineManifest:
    return TimelineManifest(
        timeline_manifest_id="timeline-1",
        document_id="doc-1",
        document_version=1,
        timeline_version=1,
        sample_rate=sample_rate,
        playable_sample_span=(entries[0][1], entries[-1][2]),
        segment_entries=[
            TimelineSegmentEntry(
                segment_id=segment_id,
                order_key=index,
                start_sample=start_sample,
                end_sample=end_sample,
            )
            for index, (segment_id, start_sample, end_sample) in enumerate(entries, start=1)
        ],
        created_at=datetime(2026, 4, 12, tzinfo=timezone.utc),
    )


def test_unified_export_request_supports_audio_and_subtitle_specs():
    payload = ExportRequest(
        document_version=1,
        target_dir="F:\\exports",
        audio={"kind": "composition", "overwrite_policy": "fail"},
        subtitle={
            "enabled": True,
            "format": "srt",
            "offset_seconds": -0.3,
            "strip_trailing_punctuation": True,
        },
    )

    assert payload.audio.kind == "composition"
    assert payload.subtitle.enabled is True
    assert payload.subtitle.format == "srt"
    assert payload.subtitle.offset_seconds == -0.3
    assert payload.subtitle.strip_trailing_punctuation is True


def test_format_srt_timestamp_uses_hh_mm_ss_mmm():
    assert SubtitleExportService._format_srt_timestamp(0.0) == "00:00:00,000"
    assert SubtitleExportService._format_srt_timestamp(61.2) == "00:01:01,200"


def test_shifted_segment_keeps_duration_when_offset_is_positive():
    start, end = SubtitleExportService._shift_segment_window(1.0, 2.5, 0.4)

    assert (start, end) == (1.4, 2.9)


def test_shifted_segment_clamps_negative_start_to_zero_but_keeps_duration():
    start, end = SubtitleExportService._shift_segment_window(0.1, 0.6, -0.5)

    assert (start, end) == (0.0, 0.5)


def test_export_srt_preserves_segment_terminal_punctuation_by_default():
    timeline = _build_timeline(sample_rate=10, entries=[("seg-1", 0, 10), ("seg-2", 12, 20)])
    snapshot = _build_snapshot(("seg-1", "第一句。"), ("seg-2", "第二句。"))

    result = SubtitleExportService().export(
        request=_build_subtitle_request(
            format="srt",
            offset_seconds=0.0,
            strip_trailing_punctuation=False,
        ),
        snapshot=snapshot,
        timeline=timeline,
    )

    assert result.file_extension == ".srt"
    assert "1\n00:00:00,000 --> 00:00:01,000\n第一句。" in result.payload


def test_export_srt_can_strip_segment_terminal_punctuation():
    timeline = _build_timeline(sample_rate=10, entries=[("seg-1", 0, 10)])
    snapshot = _build_snapshot(("seg-1", "真的吗？！」"))

    result = SubtitleExportService().export(
        request=_build_subtitle_request(
            format="srt",
            offset_seconds=0.0,
            strip_trailing_punctuation=True,
        ),
        snapshot=snapshot,
        timeline=timeline,
    )

    assert "1\n00:00:00,000 --> 00:00:01,000\n真的吗\n" in result.payload


def test_export_srt_uses_structured_stem_and_capsule_without_legacy_raw_text_fields():
    timeline = _build_timeline(sample_rate=10, entries=[("seg-1", 0, 10)])
    snapshot = DocumentSnapshot(
        snapshot_id="snapshot-1",
        document_id="doc-1",
        snapshot_kind="head",
        document_version=1,
        timeline_manifest_id="timeline-1",
        segments=[
            EditableSegment(
                segment_id="seg-1",
                document_id="doc-1",
                order_key=1,
                stem="Hello world",
                text_language="en",
                terminal_raw="",
                terminal_closer_suffix="",
                terminal_source="synthetic",
                render_asset_id="render-seg-1",
            )
        ],
        created_at=datetime(2026, 4, 12, tzinfo=timezone.utc),
    )

    result = SubtitleExportService().export(
        request=_build_subtitle_request(
            format="srt",
            offset_seconds=0.0,
            strip_trailing_punctuation=False,
        ),
        snapshot=snapshot,
        timeline=timeline,
    )

    assert "1\n00:00:00,000 --> 00:00:01,000\nHello world.\n" in result.payload


def test_export_raises_for_unsupported_format():
    with pytest.raises(ValueError):
        SubtitleExportService().export(
            request=ExportSubtitleRequest.model_construct(
                enabled=True,
                format="vtt",
                offset_seconds=0.0,
                strip_trailing_punctuation=False,
            ),
            snapshot=_build_snapshot(("seg-1", "第一句。")),
            timeline=_build_timeline(sample_rate=10, entries=[("seg-1", 0, 10)]),
        )
