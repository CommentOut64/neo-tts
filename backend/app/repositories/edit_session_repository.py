from __future__ import annotations

from pathlib import Path
import json
import sqlite3
import threading

from backend.app.schemas.edit_session import ActiveDocumentState, DocumentSnapshot, EditableEdge, EditableSegment, RenderJobRecord


class EditSessionRepository:
    def __init__(self, *, db_file: Path, project_root: Path | None = None) -> None:
        self._project_root = project_root or Path.cwd()
        self._db_file = self._resolve_path(db_file)
        self._lock = threading.Lock()

    def initialize_schema(self) -> None:
        self._db_file.parent.mkdir(parents=True, exist_ok=True)
        with self._lock, self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS active_session (
                    singleton_key TEXT PRIMARY KEY CHECK (singleton_key = 'active'),
                    payload TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS snapshots (
                    snapshot_id TEXT PRIMARY KEY,
                    document_id TEXT NOT NULL,
                    document_version INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    payload TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS segments (
                    segment_id TEXT PRIMARY KEY,
                    document_id TEXT NOT NULL,
                    snapshot_id TEXT NOT NULL,
                    order_key INTEGER NOT NULL,
                    payload TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_segments_document_order
                ON segments (document_id, order_key);

                CREATE TABLE IF NOT EXISTS edges (
                    edge_id TEXT PRIMARY KEY,
                    document_id TEXT NOT NULL,
                    snapshot_id TEXT NOT NULL,
                    left_segment_id TEXT NOT NULL,
                    right_segment_id TEXT NOT NULL,
                    edge_order_key INTEGER NOT NULL,
                    payload TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_edges_document_order
                ON edges (document_id, edge_order_key);

                CREATE TABLE IF NOT EXISTS render_jobs (
                    job_id TEXT PRIMARY KEY,
                    document_id TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    payload TEXT NOT NULL
                );
                """
            )

    def upsert_active_session(self, session: ActiveDocumentState) -> None:
        payload = self._dump_model(session)
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO active_session(singleton_key, payload)
                VALUES ('active', ?)
                ON CONFLICT(singleton_key) DO UPDATE SET payload = excluded.payload
                """,
                (payload,),
            )

    def get_active_session(self) -> ActiveDocumentState | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT payload FROM active_session WHERE singleton_key = 'active'"
            ).fetchone()
        if row is None:
            return None
        return ActiveDocumentState.model_validate_json(row["payload"])

    def save_snapshot(self, snapshot: DocumentSnapshot) -> None:
        payload = self._dump_model(snapshot)
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO snapshots(snapshot_id, document_id, document_version, created_at, payload)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(snapshot_id) DO UPDATE SET
                    document_id = excluded.document_id,
                    document_version = excluded.document_version,
                    created_at = excluded.created_at,
                    payload = excluded.payload
                """,
                (
                    snapshot.snapshot_id,
                    snapshot.document_id,
                    snapshot.document_version,
                    snapshot.created_at.isoformat(),
                    payload,
                ),
            )
            connection.execute("DELETE FROM segments WHERE document_id = ?", (snapshot.document_id,))
            for segment in snapshot.segments:
                connection.execute(
                    """
                    INSERT INTO segments(segment_id, document_id, snapshot_id, order_key, payload)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        segment.segment_id,
                        segment.document_id,
                        snapshot.snapshot_id,
                        segment.order_key,
                        self._dump_model(segment),
                    ),
                )

            segment_order_map = {segment.segment_id: segment.order_key for segment in snapshot.segments}
            connection.execute("DELETE FROM edges WHERE document_id = ?", (snapshot.document_id,))
            for edge in snapshot.edges:
                connection.execute(
                    """
                    INSERT INTO edges(edge_id, document_id, snapshot_id, left_segment_id, right_segment_id, edge_order_key, payload)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        edge.edge_id,
                        edge.document_id,
                        snapshot.snapshot_id,
                        edge.left_segment_id,
                        edge.right_segment_id,
                        segment_order_map.get(edge.left_segment_id, 0),
                        self._dump_model(edge),
                    ),
                )

    def get_snapshot(self, snapshot_id: str) -> DocumentSnapshot | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT payload FROM snapshots WHERE snapshot_id = ?",
                (snapshot_id,),
            ).fetchone()
        if row is None:
            return None
        return DocumentSnapshot.model_validate_json(row["payload"])

    def list_segments(self, document_id: str, *, limit: int, cursor: int | None) -> list[EditableSegment]:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                """
                SELECT payload
                FROM segments
                WHERE document_id = ?
                  AND (? IS NULL OR order_key > ?)
                ORDER BY order_key ASC
                LIMIT ?
                """,
                (document_id, cursor, cursor, limit),
            ).fetchall()
        return [EditableSegment.model_validate_json(row["payload"]) for row in rows]

    def list_edges(self, document_id: str, *, limit: int, cursor: int | None) -> list[EditableEdge]:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                """
                SELECT payload
                FROM edges
                WHERE document_id = ?
                  AND (? IS NULL OR edge_order_key > ?)
                ORDER BY edge_order_key ASC, edge_id ASC
                LIMIT ?
                """,
                (document_id, cursor, cursor, limit),
            ).fetchall()
        return [EditableEdge.model_validate_json(row["payload"]) for row in rows]

    def save_render_job(self, job: RenderJobRecord) -> None:
        payload = self._dump_model(job)
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO render_jobs(job_id, document_id, updated_at, payload)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(job_id) DO UPDATE SET
                    document_id = excluded.document_id,
                    updated_at = excluded.updated_at,
                    payload = excluded.payload
                """,
                (
                    job.job_id,
                    job.document_id,
                    job.updated_at.isoformat(),
                    payload,
                ),
            )

    def get_render_job(self, job_id: str) -> RenderJobRecord | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT payload FROM render_jobs WHERE job_id = ?",
                (job_id,),
            ).fetchone()
        if row is None:
            return None
        return RenderJobRecord.model_validate_json(row["payload"])

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._db_file)
        connection.row_factory = sqlite3.Row
        return connection

    def _resolve_path(self, value: Path) -> Path:
        if value.is_absolute():
            return value
        return (self._project_root / value).resolve()

    @staticmethod
    def _dump_model(model: ActiveDocumentState | DocumentSnapshot | EditableSegment | EditableEdge | RenderJobRecord) -> str:
        return json.dumps(model.model_dump(mode="json"), ensure_ascii=False)
