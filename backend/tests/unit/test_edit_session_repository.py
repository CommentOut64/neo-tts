import json
import sqlite3
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
                raw_text="甲？」",
                normalized_text="甲。",
                text_language="zh",
                terminal_raw="？",
                terminal_closer_suffix="」",
                terminal_source="original",
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
    assert loaded_snapshot.segments[0].terminal_raw == "？"
    assert loaded_snapshot.segments[0].terminal_closer_suffix == "」"
    assert loaded_snapshot.segments[0].terminal_source == "original"
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


def test_repository_preserves_snapshot_specific_segment_and_edge_indexes(tmp_path: Path):
    repository = _build_repository(tmp_path / "edit_session.db")
    baseline_snapshot = DocumentSnapshot(
        snapshot_id="snap-base",
        document_id="doc-1",
        snapshot_kind="baseline",
        document_version=1,
        raw_text="甲。乙。",
        normalized_text="甲。乙。",
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
            ),
        ],
        edges=[
            EditableEdge(
                edge_id="edge-base",
                document_id="doc-1",
                left_segment_id="seg-1",
                right_segment_id="seg-2",
            )
        ],
    )
    head_snapshot = DocumentSnapshot(
        snapshot_id="snap-head",
        document_id="doc-1",
        snapshot_kind="head",
        document_version=2,
        raw_text="甲。乙。丙。",
        normalized_text="甲。乙。丙。",
        segments=[
            EditableSegment(
                segment_id="seg-1-v2",
                document_id="doc-1",
                order_key=1,
                raw_text="甲。",
                normalized_text="甲。",
                text_language="zh",
            ),
            EditableSegment(
                segment_id="seg-2-v2",
                document_id="doc-1",
                order_key=2,
                raw_text="乙。",
                normalized_text="乙。",
                text_language="zh",
                previous_segment_id="seg-1-v2",
                next_segment_id="seg-3-v2",
            ),
            EditableSegment(
                segment_id="seg-3-v2",
                document_id="doc-1",
                order_key=3,
                raw_text="丙。",
                normalized_text="丙。",
                text_language="zh",
                previous_segment_id="seg-2-v2",
            ),
        ],
        edges=[
            EditableEdge(
                edge_id="edge-head-1",
                document_id="doc-1",
                left_segment_id="seg-1-v2",
                right_segment_id="seg-2-v2",
            ),
            EditableEdge(
                edge_id="edge-head-2",
                document_id="doc-1",
                left_segment_id="seg-2-v2",
                right_segment_id="seg-3-v2",
            ),
        ],
    )

    repository.save_snapshot(baseline_snapshot)
    repository.save_snapshot(head_snapshot)

    baseline_segments = repository.list_segments("doc-1", limit=10, cursor=None, snapshot_id="snap-base")
    head_segments = repository.list_segments("doc-1", limit=10, cursor=None, snapshot_id="snap-head")
    baseline_edges = repository.list_edges("doc-1", limit=10, cursor=None, snapshot_id="snap-base")
    head_edges = repository.list_edges("doc-1", limit=10, cursor=None, snapshot_id="snap-head")

    assert [segment.segment_id for segment in baseline_segments] == ["seg-1", "seg-2"]
    assert [segment.segment_id for segment in head_segments] == ["seg-1-v2", "seg-2-v2", "seg-3-v2"]
    assert [edge.edge_id for edge in baseline_edges] == ["edge-base"]
    assert [edge.edge_id for edge in head_edges] == ["edge-head-1", "edge-head-2"]


def test_repository_loads_recoverable_state_and_collects_referenced_assets(tmp_path: Path):
    repository = _build_repository(tmp_path / "edit_session.db")
    baseline_snapshot = DocumentSnapshot(
        snapshot_id="snap-base",
        document_id="doc-1",
        snapshot_kind="baseline",
        document_version=1,
        raw_text="甲。乙。",
        normalized_text="甲。乙。",
        block_ids=["block-1"],
        composition_manifest_id="comp-1",
        segments=[
            EditableSegment(
                segment_id="seg-1",
                document_id="doc-1",
                order_key=1,
                raw_text="甲。",
                normalized_text="甲。",
                text_language="zh",
                render_asset_id="render-1",
                render_version=1,
            ),
            EditableSegment(
                segment_id="seg-2",
                document_id="doc-1",
                order_key=2,
                raw_text="乙。",
                normalized_text="乙。",
                text_language="zh",
                previous_segment_id="seg-1",
                render_asset_id="render-2",
                render_version=2,
            ),
        ],
        edges=[
            EditableEdge(
                edge_id="edge-1",
                document_id="doc-1",
                left_segment_id="seg-1",
                right_segment_id="seg-2",
                edge_version=3,
            )
        ],
    )
    head_snapshot = baseline_snapshot.model_copy(
        update={
            "snapshot_id": "snap-head",
            "snapshot_kind": "head",
            "document_version": 2,
            "composition_manifest_id": "comp-2",
            "block_ids": ["block-2"],
            "segments": [
                baseline_snapshot.segments[0].model_copy(update={"render_asset_id": "render-3", "render_version": 4}),
                baseline_snapshot.segments[1],
            ],
        },
        deep=True,
    )
    repository.save_snapshot(baseline_snapshot)
    repository.save_snapshot(head_snapshot)
    repository.upsert_active_session(
        ActiveDocumentState(
            document_id="doc-1",
            session_status="ready",
            baseline_snapshot_id="snap-base",
            head_snapshot_id="snap-head",
        )
    )

    recoverable = repository.load_recoverable_state()
    referenced = repository.collect_referenced_asset_ids()

    assert recoverable is not None
    assert recoverable.active_session.document_id == "doc-1"
    assert recoverable.baseline_snapshot.snapshot_id == "snap-base"
    assert recoverable.head_snapshot.snapshot_id == "snap-head"
    assert referenced.segment_asset_ids == {"render-1", "render-2", "render-3"}
    assert referenced.block_ids == {"block-1", "block-2"}
    assert referenced.composition_manifest_ids == {"comp-1", "comp-2"}
    assert referenced.boundary_asset_ids


def test_repository_lists_non_terminal_jobs_and_marks_terminal(tmp_path: Path):
    repository = _build_repository(tmp_path / "edit_session.db")
    preparing = RenderJobRecord(
        job_id="job-1",
        document_id="doc-1",
        job_kind="initialize",
        status="preparing",
        progress=0.1,
        message="preparing",
        cancel_requested=False,
        updated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    completed = RenderJobRecord(
        job_id="job-2",
        document_id="doc-1",
        job_kind="initialize",
        status="completed",
        progress=1.0,
        message="done",
        cancel_requested=False,
        updated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    repository.save_render_job(preparing)
    repository.save_render_job(completed)

    non_terminal = repository.list_non_terminal_jobs()

    assert [job.job_id for job in non_terminal] == ["job-1"]

    repository.mark_job_terminal("job-1", status="failed", message="recovered on startup")

    updated = repository.get_render_job("job-1")
    assert updated is not None
    assert updated.status == "failed"
    assert updated.message == "recovered on startup"


def test_repository_migrates_legacy_snapshot_tables_to_composite_primary_keys(tmp_path: Path):
    db_file = tmp_path / "edit_session.db"
    with sqlite3.connect(db_file) as connection:
        connection.executescript(
            """
            CREATE TABLE segments (
                segment_id TEXT PRIMARY KEY,
                document_id TEXT NOT NULL,
                snapshot_id TEXT NOT NULL,
                order_key INTEGER NOT NULL,
                payload TEXT NOT NULL
            );
            CREATE INDEX idx_segments_document_order
            ON segments (document_id, snapshot_id, order_key);

            CREATE TABLE edges (
                edge_id TEXT PRIMARY KEY,
                document_id TEXT NOT NULL,
                snapshot_id TEXT NOT NULL,
                left_segment_id TEXT NOT NULL,
                right_segment_id TEXT NOT NULL,
                edge_order_key INTEGER NOT NULL,
                payload TEXT NOT NULL
            );
            CREATE INDEX idx_edges_document_order
            ON edges (document_id, snapshot_id, edge_order_key);
            """
        )
        connection.execute(
            """
            INSERT INTO segments(segment_id, document_id, snapshot_id, order_key, payload)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                "seg-legacy",
                "doc-legacy",
                "snap-legacy",
                1,
                json.dumps(
                    EditableSegment(
                        segment_id="seg-legacy",
                        document_id="doc-legacy",
                        order_key=1,
                        raw_text="旧段。",
                        normalized_text="旧段。",
                        text_language="zh",
                    ).model_dump(mode="json"),
                    ensure_ascii=False,
                ),
            ),
        )
        connection.execute(
            """
            INSERT INTO edges(edge_id, document_id, snapshot_id, left_segment_id, right_segment_id, edge_order_key, payload)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "edge-legacy",
                "doc-legacy",
                "snap-legacy",
                "seg-legacy",
                "seg-legacy-2",
                1,
                json.dumps(
                    EditableEdge(
                        edge_id="edge-legacy",
                        document_id="doc-legacy",
                        left_segment_id="seg-legacy",
                        right_segment_id="seg-legacy-2",
                    ).model_dump(mode="json"),
                    ensure_ascii=False,
                ),
            ),
        )

    repository = _build_repository(db_file)

    baseline_snapshot = DocumentSnapshot(
        snapshot_id="snap-base",
        document_id="doc-1",
        snapshot_kind="baseline",
        document_version=1,
        raw_text="甲。乙。",
        normalized_text="甲。乙。",
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
            ),
        ],
        edges=[
            EditableEdge(
                edge_id="edge-1",
                document_id="doc-1",
                left_segment_id="seg-1",
                right_segment_id="seg-2",
            )
        ],
    )
    head_snapshot = baseline_snapshot.model_copy(
        update={
            "snapshot_id": "snap-head",
            "snapshot_kind": "head",
            "document_version": 2,
        },
        deep=True,
    )

    repository.save_snapshot(baseline_snapshot)
    repository.save_snapshot(head_snapshot)

    with sqlite3.connect(db_file) as connection:
        segment_pk = connection.execute("PRAGMA table_info(segments)").fetchall()
        edge_pk = connection.execute("PRAGMA table_info(edges)").fetchall()

    assert [row[1] for row in segment_pk if row[5] > 0] == ["snapshot_id", "segment_id"]
    assert [row[1] for row in edge_pk if row[5] > 0] == ["snapshot_id", "edge_id"]
    assert [segment.segment_id for segment in repository.list_segments("doc-legacy", limit=10, cursor=None, snapshot_id="snap-legacy")] == [
        "seg-legacy"
    ]
    assert [edge.edge_id for edge in repository.list_edges("doc-legacy", limit=10, cursor=None, snapshot_id="snap-legacy")] == [
        "edge-legacy"
    ]
    assert [segment.segment_id for segment in repository.list_segments("doc-1", limit=10, cursor=None, snapshot_id="snap-base")] == [
        "seg-1",
        "seg-2",
    ]
    assert [segment.segment_id for segment in repository.list_segments("doc-1", limit=10, cursor=None, snapshot_id="snap-head")] == [
        "seg-1",
        "seg-2",
    ]


def test_repository_upgrades_legacy_render_profile_reference_fields_on_read(tmp_path: Path):
    db_file = tmp_path / "edit_session.db"
    repository = _build_repository(db_file)

    legacy_snapshot = {
        "snapshot_id": "snap-legacy",
        "document_id": "doc-1",
        "snapshot_kind": "head",
        "document_version": 1,
        "raw_text": "第一句。",
        "normalized_text": "第一句。",
        "segment_ids": ["seg-1"],
        "edge_ids": [],
        "block_ids": [],
        "groups": [],
        "render_profiles": [
            {
                "render_profile_id": "profile-session",
                "scope": "session",
                "name": "session",
                "speed": 1.0,
                "top_k": 15,
                "top_p": 1.0,
                "temperature": 1.0,
                "noise_scale": 0.35,
                "reference_audio_path": "legacy.wav",
                "reference_text": "遗留参考文本",
                "reference_language": "zh",
                "extra_overrides": {},
            }
        ],
        "voice_bindings": [
            {
                "voice_binding_id": "binding-session",
                "scope": "session",
                "voice_id": "voice-a",
                "model_key": "model-a",
                "sovits_path": None,
                "gpt_path": None,
                "speaker_meta": {},
            }
        ],
        "default_render_profile_id": "profile-session",
        "default_voice_binding_id": "binding-session",
        "composition_manifest_id": None,
        "playback_map_version": None,
        "timeline_manifest_id": None,
        "segments": [
            {
                "segment_id": "seg-1",
                "document_id": "doc-1",
                "order_key": 1,
                "previous_segment_id": None,
                "next_segment_id": None,
                "segment_kind": "speech",
                "raw_text": "第一句。",
                "normalized_text": "第一句。",
                "text_language": "zh",
                "render_version": 0,
                "render_asset_id": None,
                "group_id": None,
                "render_profile_id": None,
                "voice_binding_id": None,
                "render_status": "ready",
                "segment_revision": 1,
                "effective_duration_samples": None,
                "inference_override": {},
                "risk_flags": [],
                "assembled_audio_span": None,
            }
        ],
        "edges": [],
    }

    with sqlite3.connect(db_file) as connection:
        connection.execute(
            """
            INSERT INTO snapshots(snapshot_id, document_id, document_version, created_at, payload)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                "snap-legacy",
                "doc-1",
                1,
                datetime(2026, 4, 12, tzinfo=timezone.utc).isoformat(),
                json.dumps(legacy_snapshot, ensure_ascii=False),
            ),
        )

    loaded = repository.get_snapshot("snap-legacy")

    assert loaded is not None
    assert loaded.render_profiles[0].model_dump(mode="json")["reference_overrides_by_binding"] == {
        "voice-a:model-a": {
            "reference_audio_path": "legacy.wav",
            "reference_text": "遗留参考文本",
            "reference_language": "zh",
        }
    }
