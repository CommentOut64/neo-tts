from datetime import datetime, timezone
from pathlib import Path

from backend.app.repositories.edit_session_repository import EditSessionRepository
from backend.app.schemas.edit_session import ActiveDocumentState, DocumentSnapshot, EditableEdge, EditableSegment, RenderJobRecord


def _build_repository(db_file: Path) -> EditSessionRepository:
    repository = EditSessionRepository(db_file=db_file)
    repository.initialize_schema()
    return repository


def test_repository_initializes_schema_and_round_trips_active_session(tmp_path: Path):
    repository = _build_repository(tmp_path / "edit_session.db")
    session = ActiveDocumentState(
        document_id="doc-1",
        session_status="ready",
        baseline_snapshot_id="snap-base",
        head_snapshot_id="snap-head",
        active_job_id=None,
        editable_mode="segment",
    )

    repository.upsert_active_session(session)

    loaded = repository.get_active_session()

    assert loaded == session


def test_repository_saves_snapshot_and_lists_segments_and_edges_with_cursor(tmp_path: Path):
    repository = _build_repository(tmp_path / "edit_session.db")
    snapshot = DocumentSnapshot(
        snapshot_id="snap-1",
        document_id="doc-1",
        snapshot_kind="head",
        document_version=3,
        raw_text="甲。乙。丙。",
        normalized_text="甲。乙。丙。",
        segment_ids=["seg-1", "seg-2", "seg-3"],
        edge_ids=["edge-1", "edge-2"],
        block_ids=[],
        composition_manifest_id="comp-1",
        playback_map_version=3,
        segments=[
            EditableSegment(
                segment_id="seg-1",
                document_id="doc-1",
                order_key=1,
                raw_text="甲。",
                normalized_text="甲。",
                text_language="zh",
            ),
            EditableSegment(
                segment_id="seg-2",
                document_id="doc-1",
                order_key=2,
                raw_text="乙。",
                normalized_text="乙。",
                text_language="zh",
                previous_segment_id="seg-1",
                next_segment_id="seg-3",
            ),
            EditableSegment(
                segment_id="seg-3",
                document_id="doc-1",
                order_key=3,
                raw_text="丙。",
                normalized_text="丙。",
                text_language="zh",
                previous_segment_id="seg-2",
            ),
        ],
        edges=[
            EditableEdge(
                edge_id="edge-1",
                document_id="doc-1",
                left_segment_id="seg-1",
                right_segment_id="seg-2",
            ),
            EditableEdge(
                edge_id="edge-2",
                document_id="doc-1",
                left_segment_id="seg-2",
                right_segment_id="seg-3",
            ),
        ],
    )

    repository.save_snapshot(snapshot)

    loaded_snapshot = repository.get_snapshot("snap-1")
    first_page_segments = repository.list_segments("doc-1", limit=2, cursor=None)
    second_page_segments = repository.list_segments("doc-1", limit=2, cursor=2)
    first_page_edges = repository.list_edges("doc-1", limit=1, cursor=None)
    second_page_edges = repository.list_edges("doc-1", limit=5, cursor=1)

    assert loaded_snapshot is not None
    assert loaded_snapshot.snapshot_id == "snap-1"
    assert [segment.segment_id for segment in first_page_segments] == ["seg-1", "seg-2"]
    assert [segment.segment_id for segment in second_page_segments] == ["seg-3"]
    assert [edge.edge_id for edge in first_page_edges] == ["edge-1"]
    assert [edge.edge_id for edge in second_page_edges] == ["edge-2"]


def test_repository_saves_and_loads_render_job(tmp_path: Path):
    repository = _build_repository(tmp_path / "edit_session.db")
    job = RenderJobRecord(
        job_id="job-1",
        document_id="doc-1",
        job_kind="initialize",
        status="queued",
        snapshot_id="snap-1",
        target_segment_ids=["seg-1"],
        target_edge_ids=["edge-1"],
        target_block_ids=["block-1"],
        progress=0.1,
        message="queued",
        cancel_requested=False,
        current_segment_index=0,
        total_segment_count=1,
        current_block_index=0,
        total_block_count=1,
        result_document_version=None,
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        updated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )

    repository.save_render_job(job)

    loaded = repository.get_render_job("job-1")

    assert loaded == job
