import pytest

from backend.app.repositories.edit_session_repository import EditSessionRepository
from backend.app.schemas.edit_session import DocumentSnapshot, EditableSegment, UpdateSegmentRequest
from backend.app.services.edge_service import EdgeService
from backend.app.services.segment_service import SegmentService


def _build_service(tmp_path) -> SegmentService:
    repository = EditSessionRepository(project_root=tmp_path, db_file=tmp_path / "edit_session.db")
    repository.initialize_schema()
    return SegmentService(
        repository=repository,
        edge_service=EdgeService(repository=repository),
    )


def _snapshot(*segments: EditableSegment) -> DocumentSnapshot:
    return DocumentSnapshot(
        snapshot_id="head-1",
        document_id="doc-1",
        snapshot_kind="head",
        document_version=1,
        raw_text="".join(segment.raw_text for segment in segments),
        normalized_text="".join(segment.normalized_text for segment in segments),
        segments=list(segments),
        edges=[],
    )


def _segment(segment_id: str, order_key: int, raw_text: str) -> EditableSegment:
    return EditableSegment(
        segment_id=segment_id,
        document_id="doc-1",
        order_key=order_key,
        previous_segment_id=None if order_key == 1 else f"seg-{order_key - 1}",
        next_segment_id=None,
        raw_text=raw_text,
        normalized_text=raw_text,
        text_language="zh",
    )


def test_insert_segment_requires_strong_boundary_punctuation(tmp_path):
    service = _build_service(tmp_path)
    snapshot = _snapshot(_segment("seg-1", 1, "原句。"))

    with pytest.raises(ValueError, match="强标点"):
        service.insert_segment(
            after_segment_id="seg-1",
            raw_text="没有句末标点",
            text_language="zh",
            inference_override={},
            snapshot=snapshot,
        )


def test_insert_segment_marks_short_segment_risk(tmp_path):
    service = _build_service(tmp_path)
    snapshot = _snapshot(_segment("seg-1", 1, "这是一个较长的参考句子。"))

    mutation = service.insert_segment(
        after_segment_id="seg-1",
        raw_text="你好。",
        text_language="zh",
        inference_override={},
        snapshot=snapshot,
    )

    assert mutation.segment is not None
    assert "short_naturalness_risk" in mutation.segment.risk_flags


def test_update_segment_marks_long_segment_risk(tmp_path):
    service = _build_service(tmp_path)
    snapshot = _snapshot(_segment("seg-1", 1, "原句。"))
    long_text = ("这是一个用于验证长段风险提示的测试句子" * 20) + "。"

    mutation = service.update_segment(
        "seg-1",
        UpdateSegmentRequest(raw_text=long_text),
        snapshot=snapshot,
    )

    assert mutation.segment is not None
    assert "long_edit_cost_risk" in mutation.segment.risk_flags


def test_reorder_segments_reorders_snapshot_and_rebuilds_neighbors(tmp_path):
    service = _build_service(tmp_path)
    first = _segment("seg-1", 1, "第一句。")
    second = _segment("seg-2", 2, "第二句。")
    third = _segment("seg-3", 3, "第三句。")
    snapshot = _snapshot(first, second, third)

    mutation = service.reorder_segments(
        ["seg-3", "seg-1", "seg-2"],
        snapshot=snapshot,
    )

    assert mutation.segment is None
    assert [segment.segment_id for segment in mutation.snapshot.segments] == ["seg-3", "seg-1", "seg-2"]
    assert [segment.order_key for segment in mutation.snapshot.segments] == [1, 2, 3]
    assert mutation.snapshot.segments[0].previous_segment_id is None
    assert mutation.snapshot.segments[0].next_segment_id == "seg-1"
    assert mutation.snapshot.segments[1].previous_segment_id == "seg-3"
    assert mutation.snapshot.segments[1].next_segment_id == "seg-2"
    assert mutation.snapshot.segments[2].previous_segment_id == "seg-1"
    assert mutation.snapshot.segments[2].next_segment_id is None
    assert mutation.snapshot.raw_text == "第三句。第一句。第二句。"
    assert [(edge.left_segment_id, edge.right_segment_id) for edge in mutation.snapshot.edges] == [
        ("seg-3", "seg-1"),
        ("seg-1", "seg-2"),
    ]


def test_reorder_segments_requires_complete_unique_segment_ids(tmp_path):
    service = _build_service(tmp_path)
    snapshot = _snapshot(
        _segment("seg-1", 1, "第一句。"),
        _segment("seg-2", 2, "第二句。"),
        _segment("seg-3", 3, "第三句。"),
    )

    with pytest.raises(ValueError, match="must match current snapshot exactly"):
        service.reorder_segments(["seg-1", "seg-2"], snapshot=snapshot)

    with pytest.raises(ValueError, match="must be unique"):
        service.reorder_segments(["seg-1", "seg-2", "seg-2"], snapshot=snapshot)


def test_swap_segments_reorders_snapshot_and_rebuilds_neighbors(tmp_path):
    service = _build_service(tmp_path)
    first = _segment("seg-1", 1, "第一句。")
    second = _segment("seg-2", 2, "第二句。")
    third = _segment("seg-3", 3, "第三句。")
    snapshot = _snapshot(first, second, third)

    mutation = service.swap_segments("seg-2", "seg-3", snapshot=snapshot)

    assert mutation.segment is None
    assert [segment.segment_id for segment in mutation.snapshot.segments] == ["seg-1", "seg-3", "seg-2"]
    assert [segment.order_key for segment in mutation.snapshot.segments] == [1, 2, 3]
    assert mutation.snapshot.segments[1].previous_segment_id == "seg-1"
    assert mutation.snapshot.segments[1].next_segment_id == "seg-2"
    assert mutation.snapshot.segments[2].previous_segment_id == "seg-3"
    assert mutation.snapshot.segments[2].next_segment_id is None
    assert mutation.snapshot.raw_text == "第一句。第三句。第二句。"
    assert [(edge.left_segment_id, edge.right_segment_id) for edge in mutation.snapshot.edges] == [
        ("seg-1", "seg-3"),
        ("seg-3", "seg-2"),
    ]
