from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
import json
import sqlite3
import threading

from backend.app.inference.editable_types import build_boundary_asset_id
from backend.app.services.reference_binding import build_binding_key, migrate_legacy_render_profile_payload
from backend.app.schemas.edit_session import (
    ActiveDocumentState,
    CheckpointState,
    DocumentSnapshot,
    EditableEdge,
    EditableSegment,
    ExportJobRecord,
    RenderJobRecord,
)


TERMINAL_JOB_STATUSES = {"paused", "cancelled_partial", "completed", "failed"}
TERMINAL_EXPORT_JOB_STATUSES = {"completed", "failed"}


@dataclass(frozen=True)
class PersistedRecoverableState:
    active_session: ActiveDocumentState
    head_snapshot: DocumentSnapshot
    baseline_snapshot: DocumentSnapshot | None = None


@dataclass(frozen=True)
class ReferencedAssetGraph:
    segment_asset_ids: set[str] = field(default_factory=set)
    boundary_asset_ids: set[str] = field(default_factory=set)
    block_ids: set[str] = field(default_factory=set)
    composition_manifest_ids: set[str] = field(default_factory=set)
    timeline_manifest_ids: set[str] = field(default_factory=set)
    preview_asset_ids: set[str] = field(default_factory=set)

    def as_relative_asset_paths(self) -> set[str]:
        return {
            *{f"segments/{asset_id}" for asset_id in self.segment_asset_ids},
            *{f"boundaries/{asset_id}" for asset_id in self.boundary_asset_ids},
            *{f"blocks/{asset_id}" for asset_id in self.block_ids},
            *{f"compositions/{asset_id}" for asset_id in self.composition_manifest_ids},
            *{f"timelines/{asset_id}" for asset_id in self.timeline_manifest_ids},
            *{f"previews/{asset_id}" for asset_id in self.preview_asset_ids},
        }


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
                    snapshot_id TEXT NOT NULL,
                    segment_id TEXT NOT NULL,
                    document_id TEXT NOT NULL,
                    order_key INTEGER NOT NULL,
                    payload TEXT NOT NULL,
                    PRIMARY KEY (snapshot_id, segment_id)
                );

                CREATE INDEX IF NOT EXISTS idx_segments_document_order
                ON segments (document_id, snapshot_id, order_key);

                CREATE TABLE IF NOT EXISTS edges (
                    snapshot_id TEXT NOT NULL,
                    edge_id TEXT NOT NULL,
                    document_id TEXT NOT NULL,
                    left_segment_id TEXT NOT NULL,
                    right_segment_id TEXT NOT NULL,
                    edge_order_key INTEGER NOT NULL,
                    payload TEXT NOT NULL,
                    PRIMARY KEY (snapshot_id, edge_id)
                );

                CREATE INDEX IF NOT EXISTS idx_edges_document_order
                ON edges (document_id, snapshot_id, edge_order_key);

                CREATE TABLE IF NOT EXISTS render_jobs (
                    job_id TEXT PRIMARY KEY,
                    document_id TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    payload TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS checkpoints (
                    checkpoint_id TEXT PRIMARY KEY,
                    document_id TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    payload TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_checkpoints_document_updated
                ON checkpoints (document_id, updated_at DESC, checkpoint_id DESC);

                CREATE TABLE IF NOT EXISTS export_jobs (
                    export_job_id TEXT PRIMARY KEY,
                    document_id TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    payload TEXT NOT NULL
                );
                """
            )
            self._migrate_legacy_snapshot_tables(connection)

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
            connection.execute("DELETE FROM segments WHERE snapshot_id = ?", (snapshot.snapshot_id,))
            for segment in snapshot.segments:
                connection.execute(
                    """
                    INSERT INTO segments(snapshot_id, segment_id, document_id, order_key, payload)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        snapshot.snapshot_id,
                        segment.segment_id,
                        segment.document_id,
                        segment.order_key,
                        self._dump_model(segment),
                    ),
                )

            segment_order_map = {segment.segment_id: segment.order_key for segment in snapshot.segments}
            connection.execute("DELETE FROM edges WHERE snapshot_id = ?", (snapshot.snapshot_id,))
            for edge in snapshot.edges:
                connection.execute(
                    """
                    INSERT INTO edges(snapshot_id, edge_id, document_id, left_segment_id, right_segment_id, edge_order_key, payload)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        snapshot.snapshot_id,
                        edge.edge_id,
                        edge.document_id,
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
        return self._load_snapshot_from_payload(row["payload"])

    def get_snapshot_by_document_version(self, document_id: str, document_version: int) -> DocumentSnapshot | None:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                """
                SELECT payload
                FROM snapshots
                WHERE document_id = ? AND document_version = ?
                ORDER BY created_at DESC, snapshot_id DESC
                """,
                (document_id, document_version),
            ).fetchall()
        if not rows:
            return None
        snapshots = [self._load_snapshot_from_payload(row["payload"]) for row in rows]
        preferred = next((snapshot for snapshot in snapshots if snapshot.snapshot_kind == "head"), None)
        return preferred or snapshots[0]

    def list_segments(
        self,
        document_id: str,
        *,
        limit: int,
        cursor: int | None,
        snapshot_id: str | None = None,
    ) -> list[EditableSegment]:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                """
                SELECT payload
                FROM segments
                WHERE document_id = ?
                  AND snapshot_id = COALESCE(
                    ?,
                    (
                        SELECT snapshot_id
                        FROM snapshots
                        WHERE document_id = ?
                        ORDER BY document_version DESC, created_at DESC
                        LIMIT 1
                    )
                  )
                  AND (? IS NULL OR order_key > ?)
                ORDER BY order_key ASC
                LIMIT ?
                """,
                (document_id, snapshot_id, document_id, cursor, cursor, limit),
            ).fetchall()
        return [EditableSegment.model_validate_json(row["payload"]) for row in rows]

    def list_edges(
        self,
        document_id: str,
        *,
        limit: int,
        cursor: int | None,
        snapshot_id: str | None = None,
    ) -> list[EditableEdge]:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                """
                SELECT payload
                FROM edges
                WHERE document_id = ?
                  AND snapshot_id = COALESCE(
                    ?,
                    (
                        SELECT snapshot_id
                        FROM snapshots
                        WHERE document_id = ?
                        ORDER BY document_version DESC, created_at DESC
                        LIMIT 1
                    )
                  )
                  AND (? IS NULL OR edge_order_key > ?)
                ORDER BY edge_order_key ASC, edge_id ASC
                LIMIT ?
                """,
                (document_id, snapshot_id, document_id, cursor, cursor, limit),
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

    def save_checkpoint(self, checkpoint: CheckpointState) -> None:
        payload = self._dump_model(checkpoint)
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO checkpoints(checkpoint_id, document_id, updated_at, payload)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(checkpoint_id) DO UPDATE SET
                    document_id = excluded.document_id,
                    updated_at = excluded.updated_at,
                    payload = excluded.payload
                """,
                (
                    checkpoint.checkpoint_id,
                    checkpoint.document_id,
                    checkpoint.updated_at.isoformat(),
                    payload,
                ),
            )

    def get_checkpoint(self, checkpoint_id: str) -> CheckpointState | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT payload FROM checkpoints WHERE checkpoint_id = ?",
                (checkpoint_id,),
            ).fetchone()
        if row is None:
            return None
        return CheckpointState.model_validate_json(row["payload"])

    def save_export_job(self, job: ExportJobRecord) -> None:
        payload = self._dump_model(job)
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO export_jobs(export_job_id, document_id, updated_at, payload)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(export_job_id) DO UPDATE SET
                    document_id = excluded.document_id,
                    updated_at = excluded.updated_at,
                    payload = excluded.payload
                """,
                (
                    job.export_job_id,
                    job.document_id,
                    job.updated_at.isoformat(),
                    payload,
                ),
            )

    def get_export_job(self, export_job_id: str) -> ExportJobRecord | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT payload FROM export_jobs WHERE export_job_id = ?",
                (export_job_id,),
            ).fetchone()
        if row is None:
            return None
        return ExportJobRecord.model_validate_json(row["payload"])

    def list_non_terminal_export_jobs(self) -> list[ExportJobRecord]:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                """
                SELECT payload
                FROM export_jobs
                ORDER BY updated_at ASC, export_job_id ASC
                """
            ).fetchall()
        jobs = [ExportJobRecord.model_validate_json(row["payload"]) for row in rows]
        return [job for job in jobs if job.status not in TERMINAL_EXPORT_JOB_STATUSES]

    def get_latest_completed_export_job(
        self,
        *,
        document_id: str,
        document_version: int,
        export_kind: str,
    ) -> ExportJobRecord | None:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                """
                SELECT payload
                FROM export_jobs
                WHERE document_id = ?
                ORDER BY updated_at DESC, export_job_id DESC
                """,
                (document_id,),
            ).fetchall()
        for row in rows:
            job = ExportJobRecord.model_validate_json(row["payload"])
            if job.status != "completed":
                continue
            if job.document_version != document_version or job.export_kind != export_kind:
                continue
            return job
        return None

    def mark_export_job_terminal(self, export_job_id: str, *, status: str, message: str) -> None:
        job = self.get_export_job(export_job_id)
        if job is None:
            raise LookupError(f"Export job '{export_job_id}' not found.")
        updated_job = job.model_copy(
            update={
                "status": status,
                "message": message,
                "progress": 1.0 if status == "completed" else 0.0,
                "updated_at": datetime.now(timezone.utc),
            }
        )
        self.save_export_job(updated_job)

    def get_latest_checkpoint(self, document_id: str) -> CheckpointState | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                """
                SELECT payload
                FROM checkpoints
                WHERE document_id = ?
                ORDER BY updated_at DESC, checkpoint_id DESC
                LIMIT 1
                """,
                (document_id,),
            ).fetchone()
        if row is None:
            return None
        return CheckpointState.model_validate_json(row["payload"])

    def get_checkpoint_by_resume_token(self, resume_token: str) -> CheckpointState | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                """
                SELECT payload
                FROM checkpoints
                WHERE json_extract(payload, '$.resume_token') = ?
                ORDER BY updated_at DESC, checkpoint_id DESC
                LIMIT 1
                """,
                (resume_token,),
            ).fetchone()
        if row is None:
            return None
        return CheckpointState.model_validate_json(row["payload"])

    def delete_checkpoints_for_document(self, document_id: str) -> None:
        with self._lock, self._connect() as connection:
            connection.execute("DELETE FROM checkpoints WHERE document_id = ?", (document_id,))

    def load_recoverable_state(self) -> PersistedRecoverableState | None:
        active_session = self.get_active_session()
        if active_session is None or active_session.head_snapshot_id is None:
            return None
        head_snapshot = self.get_snapshot(active_session.head_snapshot_id)
        if head_snapshot is None:
            return None
        baseline_snapshot = (
            self.get_snapshot(active_session.baseline_snapshot_id)
            if active_session.baseline_snapshot_id is not None
            else None
        )
        return PersistedRecoverableState(
            active_session=active_session,
            head_snapshot=head_snapshot,
            baseline_snapshot=baseline_snapshot,
        )

    def list_non_terminal_jobs(self) -> list[RenderJobRecord]:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                """
                SELECT payload
                FROM render_jobs
                ORDER BY updated_at ASC, job_id ASC
                """
            ).fetchall()
        jobs = [RenderJobRecord.model_validate_json(row["payload"]) for row in rows]
        return [job for job in jobs if job.status not in TERMINAL_JOB_STATUSES]

    def mark_job_terminal(self, job_id: str, *, status: str, message: str) -> None:
        job = self.get_render_job(job_id)
        if job is None:
            raise LookupError(f"Render job '{job_id}' not found.")
        progress = 1.0 if status == "completed" else 0.0
        updated_job = job.model_copy(
            update={
                "status": status,
                "message": message,
                "progress": progress,
                "updated_at": datetime.now(timezone.utc),
            }
        )
        self.save_render_job(updated_job)

    def collect_referenced_asset_ids(self) -> ReferencedAssetGraph:
        recoverable = self.load_recoverable_state()
        snapshots: list[DocumentSnapshot] = []
        if recoverable is not None:
            snapshots.append(recoverable.head_snapshot)
            if recoverable.baseline_snapshot is not None:
                snapshots.append(recoverable.baseline_snapshot)

        active_session = self.get_active_session()
        if active_session is not None:
            checkpoint = self.get_latest_checkpoint(active_session.document_id)
            if checkpoint is not None:
                head_snapshot = self.get_snapshot(checkpoint.head_snapshot_id)
                working_snapshot = self.get_snapshot(checkpoint.working_snapshot_id)
                if head_snapshot is not None:
                    snapshots.append(head_snapshot)
                if working_snapshot is not None:
                    snapshots.append(working_snapshot)

        if not snapshots:
            return ReferencedAssetGraph()

        graph = ReferencedAssetGraph()
        for snapshot in snapshots:
            graph.block_ids.update(snapshot.block_ids)
            if snapshot.composition_manifest_id is not None:
                graph.composition_manifest_ids.add(snapshot.composition_manifest_id)
            if snapshot.timeline_manifest_id is not None:
                graph.timeline_manifest_ids.add(snapshot.timeline_manifest_id)

            segments_by_id = {segment.segment_id: segment for segment in snapshot.segments}
            for segment in snapshot.segments:
                if segment.render_asset_id is not None:
                    graph.segment_asset_ids.add(segment.render_asset_id)

            for edge in snapshot.edges:
                left_segment = segments_by_id.get(edge.left_segment_id)
                right_segment = segments_by_id.get(edge.right_segment_id)
                if left_segment is None or right_segment is None:
                    continue
                if left_segment.render_asset_id is None or right_segment.render_asset_id is None:
                    continue
                graph.boundary_asset_ids.add(
                    build_boundary_asset_id(
                        left_segment_id=edge.left_segment_id,
                        left_render_version=left_segment.render_version,
                        right_segment_id=edge.right_segment_id,
                        right_render_version=right_segment.render_version,
                        edge_version=edge.edge_version,
                        boundary_strategy=edge.boundary_strategy,
                    )
                )
        return graph

    def clear(self) -> None:
        with self._lock, self._connect() as connection:
            connection.execute("DELETE FROM active_session")
            connection.execute("DELETE FROM snapshots")
            connection.execute("DELETE FROM segments")
            connection.execute("DELETE FROM edges")
            connection.execute("DELETE FROM render_jobs")
            connection.execute("DELETE FROM checkpoints")
            connection.execute("DELETE FROM export_jobs")

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._db_file)
        connection.row_factory = sqlite3.Row
        return connection

    def _migrate_legacy_snapshot_tables(self, connection: sqlite3.Connection) -> None:
        self._migrate_legacy_snapshot_table(
            connection,
            table_name="segments",
            legacy_primary_key_columns=("segment_id",),
            create_table_sql="""
                CREATE TABLE segments (
                    snapshot_id TEXT NOT NULL,
                    segment_id TEXT NOT NULL,
                    document_id TEXT NOT NULL,
                    order_key INTEGER NOT NULL,
                    payload TEXT NOT NULL,
                    PRIMARY KEY (snapshot_id, segment_id)
                )
            """,
            create_index_sql="""
                CREATE INDEX idx_segments_document_order
                ON segments (document_id, snapshot_id, order_key)
            """,
            copy_sql="""
                INSERT INTO segments(snapshot_id, segment_id, document_id, order_key, payload)
                SELECT snapshot_id, segment_id, document_id, order_key, payload
                FROM segments_legacy
            """,
            drop_index_name="idx_segments_document_order",
        )
        self._migrate_legacy_snapshot_table(
            connection,
            table_name="edges",
            legacy_primary_key_columns=("edge_id",),
            create_table_sql="""
                CREATE TABLE edges (
                    snapshot_id TEXT NOT NULL,
                    edge_id TEXT NOT NULL,
                    document_id TEXT NOT NULL,
                    left_segment_id TEXT NOT NULL,
                    right_segment_id TEXT NOT NULL,
                    edge_order_key INTEGER NOT NULL,
                    payload TEXT NOT NULL,
                    PRIMARY KEY (snapshot_id, edge_id)
                )
            """,
            create_index_sql="""
                CREATE INDEX idx_edges_document_order
                ON edges (document_id, snapshot_id, edge_order_key)
            """,
            copy_sql="""
                INSERT INTO edges(snapshot_id, edge_id, document_id, left_segment_id, right_segment_id, edge_order_key, payload)
                SELECT snapshot_id, edge_id, document_id, left_segment_id, right_segment_id, edge_order_key, payload
                FROM edges_legacy
            """,
            drop_index_name="idx_edges_document_order",
        )

    def _migrate_legacy_snapshot_table(
        self,
        connection: sqlite3.Connection,
        *,
        table_name: str,
        legacy_primary_key_columns: tuple[str, ...],
        create_table_sql: str,
        create_index_sql: str,
        copy_sql: str,
        drop_index_name: str,
    ) -> None:
        primary_key_columns = self._get_primary_key_columns(connection, table_name)
        if primary_key_columns != legacy_primary_key_columns:
            return

        legacy_table_name = f"{table_name}_legacy"
        connection.execute(f"DROP INDEX IF EXISTS {drop_index_name}")
        connection.execute(f"ALTER TABLE {table_name} RENAME TO {legacy_table_name}")
        connection.execute(create_table_sql)
        connection.execute(create_index_sql)
        connection.execute(copy_sql)
        connection.execute(f"DROP TABLE {legacy_table_name}")

    @staticmethod
    def _get_primary_key_columns(connection: sqlite3.Connection, table_name: str) -> tuple[str, ...]:
        rows = connection.execute(f"PRAGMA table_info({table_name})").fetchall()
        primary_key_rows = sorted((row for row in rows if row["pk"] > 0), key=lambda row: row["pk"])
        return tuple(row["name"] for row in primary_key_rows)

    def _resolve_path(self, value: Path) -> Path:
        if value.is_absolute():
            return value
        return (self._project_root / value).resolve()

    def _load_snapshot_from_payload(self, payload: str) -> DocumentSnapshot:
        raw_payload = json.loads(payload)
        upgraded_payload = self._upgrade_snapshot_payload(raw_payload)
        return DocumentSnapshot.model_validate(upgraded_payload)

    def _upgrade_snapshot_payload(self, payload: object) -> object:
        if not isinstance(payload, dict):
            return payload

        upgraded = dict(payload)
        upgraded.pop("raw_text", None)
        upgraded.pop("normalized_text", None)
        render_profiles = upgraded.get("render_profiles")
        if not isinstance(render_profiles, list):
            return upgraded

        binding_by_id = self._build_binding_payload_map(upgraded.get("voice_bindings"))
        group_by_id = self._build_group_payload_map(upgraded.get("groups"))
        segments = upgraded.get("segments") if isinstance(upgraded.get("segments"), list) else []
        default_binding_id = upgraded.get("default_voice_binding_id")

        upgraded["render_profiles"] = [
            self._upgrade_render_profile_payload(
                profile,
                binding_by_id=binding_by_id,
                group_by_id=group_by_id,
                segments=segments,
                default_binding_id=default_binding_id,
            )
            for profile in render_profiles
        ]
        return upgraded

    def _upgrade_render_profile_payload(
        self,
        profile: object,
        *,
        binding_by_id: dict[str, dict[str, object]],
        group_by_id: dict[str, dict[str, object]],
        segments: list[object],
        default_binding_id: object,
    ) -> object:
        if not isinstance(profile, dict):
            return profile

        binding_id = None
        scope = profile.get("scope")
        profile_id = profile.get("render_profile_id")

        if scope == "session":
            binding_id = default_binding_id
        elif scope == "group":
            group = next(
                (
                    item
                    for item in group_by_id.values()
                    if item.get("render_profile_id") == profile_id
                ),
                None,
            )
            if group is not None:
                binding_id = group.get("voice_binding_id") or default_binding_id
        elif scope == "segment":
            segment = next(
                (
                    item
                    for item in segments
                    if isinstance(item, dict) and item.get("render_profile_id") == profile_id
                ),
                None,
            )
            if isinstance(segment, dict):
                group = group_by_id.get(str(segment.get("group_id"))) if segment.get("group_id") is not None else None
                binding_id = segment.get("voice_binding_id") or (
                    group.get("voice_binding_id") if group is not None else None
                ) or default_binding_id

        binding = binding_by_id.get(str(binding_id)) if binding_id is not None else None
        if binding is None:
            return profile

        return migrate_legacy_render_profile_payload(
            profile,
            binding_key=build_binding_key(
                voice_id=str(binding.get("voice_id", "")),
                model_key=str(binding.get("model_key", "")),
            ),
        )

    @staticmethod
    def _build_binding_payload_map(payload: object) -> dict[str, dict[str, object]]:
        if not isinstance(payload, list):
            return {}
        return {
            str(item.get("voice_binding_id")): item
            for item in payload
            if isinstance(item, dict) and item.get("voice_binding_id") is not None
        }

    @staticmethod
    def _build_group_payload_map(payload: object) -> dict[str, dict[str, object]]:
        if not isinstance(payload, list):
            return {}
        return {
            str(item.get("group_id")): item
            for item in payload
            if isinstance(item, dict) and item.get("group_id") is not None
        }

    @staticmethod
    def _dump_model(
        model: (
            ActiveDocumentState
            | DocumentSnapshot
            | EditableSegment
            | EditableEdge
            | RenderJobRecord
            | CheckpointState
            | ExportJobRecord
        ),
    ) -> str:
        return json.dumps(model.model_dump(mode="json"), ensure_ascii=False)
