"""Portable ``.neo`` v1 SQLite project container.

The store deliberately deals in plain dictionaries so it can be used by the
existing pydantic session services without introducing a second domain model.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Any, Iterator


APPLICATION_ID = 0x4E454F31
SCHEMA_VERSION = 1


class NeoError(RuntimeError):
    code = "NEO_ERROR"


class NeoUnsupportedVersionError(NeoError):
    code = "NEO_UNSUPPORTED_VERSION"


class NeoCorruptError(NeoError):
    code = "NEO_CORRUPT"


class NeoSchemaError(NeoError):
    code = "NEO_SCHEMA_INVALID"


class NeoClosureError(NeoError):
    code = "NEO_CLOSURE_BROKEN"


class NeoHashMismatchError(NeoError):
    code = "NEO_HASH_MISMATCH"


class NeoWriteBusyError(NeoError):
    code = "NEO_WRITE_BUSY"


class NeoTargetBusyError(NeoError):
    code = "NEO_TARGET_BUSY"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def canonical_json(value: Any) -> str:
    """Serialize JSON deterministically and reject non-finite numbers."""
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _validate_identifier(value: Any, label: str) -> str:
    normalized = str(value).strip()
    if not normalized or normalized in {".", ".."} or any(separator in normalized for separator in ("/", "\\")):
        raise NeoSchemaError(f"invalid {label}")
    return normalized


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS project (
 project_id TEXT PRIMARY KEY, format TEXT NOT NULL CHECK(format='neo'), schema_version INTEGER NOT NULL CHECK(schema_version=1),
 save_revision INTEGER NOT NULL CHECK(save_revision>=0), created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
 head_snapshot_id TEXT, baseline_snapshot_id TEXT, timeline_manifest_id TEXT, checkpoint_partial_id TEXT,
 checkpoint_working_id TEXT, draft_revision INTEGER NOT NULL CHECK(draft_revision>=0), draft_payload TEXT NOT NULL,
 model_identity_json TEXT NOT NULL, model_resolution_status TEXT NOT NULL,
 workspace_id TEXT, diagnostics_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS snapshots (
 snapshot_id TEXT PRIMARY KEY, kind TEXT NOT NULL CHECK(kind IN ('head','baseline','working','initial')), revision INTEGER NOT NULL CHECK(revision>=0),
 created_at TEXT NOT NULL, config_json TEXT NOT NULL, source_snapshot_id TEXT
);
CREATE TABLE IF NOT EXISTS segments (
 segment_id TEXT NOT NULL, snapshot_id TEXT NOT NULL REFERENCES snapshots(snapshot_id) ON DELETE CASCADE, position INTEGER NOT NULL CHECK(position>=0),
 group_id TEXT, text_json TEXT NOT NULL, binding_json TEXT NOT NULL, parameter_json TEXT NOT NULL, status_json TEXT NOT NULL,
 formal_asset_id TEXT, edit_context_asset_id TEXT, PRIMARY KEY(snapshot_id,segment_id)
);
CREATE TABLE IF NOT EXISTS edges (
 edge_id TEXT NOT NULL, snapshot_id TEXT NOT NULL REFERENCES snapshots(snapshot_id) ON DELETE CASCADE, from_segment_id TEXT NOT NULL,
 to_segment_id TEXT NOT NULL, position INTEGER NOT NULL CHECK(position>=0), policy_json TEXT NOT NULL, asset_id TEXT,
 status_json TEXT NOT NULL, PRIMARY KEY(snapshot_id,edge_id), CHECK(from_segment_id<>to_segment_id)
);
CREATE TABLE IF NOT EXISTS groups (
 group_id TEXT NOT NULL, snapshot_id TEXT NOT NULL REFERENCES snapshots(snapshot_id) ON DELETE CASCADE, position INTEGER NOT NULL CHECK(position>=0),
 binding_json TEXT NOT NULL, parameter_json TEXT NOT NULL, PRIMARY KEY(snapshot_id,group_id)
);
CREATE TABLE IF NOT EXISTS assets (
 asset_id TEXT PRIMARY KEY, kind TEXT NOT NULL, role TEXT, blob_sha256 TEXT, media_type TEXT NOT NULL, codec TEXT NOT NULL,
 byte_count INTEGER NOT NULL CHECK(byte_count>=0), duration_ms INTEGER, sample_rate INTEGER, channels INTEGER, ready INTEGER NOT NULL CHECK(ready IN (0,1)),
 source_revision INTEGER, metadata_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS reference_entries (
 reference_id TEXT PRIMARY KEY, role TEXT NOT NULL CHECK(role IN ('speaker','style')), audio_asset_id TEXT NOT NULL REFERENCES assets(asset_id),
 text_hash TEXT, language TEXT NOT NULL, source TEXT NOT NULL, revision INTEGER NOT NULL CHECK(revision>=0),
 status TEXT NOT NULL CHECK(status IN ('present','missing','invalid')), metadata_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS blobs (
 sha256 TEXT PRIMARY KEY, byte_count INTEGER NOT NULL CHECK(byte_count>=0), data BLOB NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS asset_refs (
 owner_type TEXT NOT NULL, owner_id TEXT NOT NULL, asset_id TEXT NOT NULL REFERENCES assets(asset_id), purpose TEXT NOT NULL,
 PRIMARY KEY(owner_type,owner_id,asset_id,purpose)
);
CREATE INDEX IF NOT EXISTS idx_segments_snapshot_position ON segments(snapshot_id,position);
CREATE INDEX IF NOT EXISTS idx_edges_snapshot_position ON edges(snapshot_id,position);
CREATE INDEX IF NOT EXISTS idx_assets_blob ON assets(blob_sha256);
CREATE INDEX IF NOT EXISTS idx_asset_refs_asset ON asset_refs(asset_id);
CREATE INDEX IF NOT EXISTS idx_references_role_status ON reference_entries(role,status);
"""


class ProjectStore:
    def __init__(self, path: str | Path, *, busy_timeout_ms: int = 250) -> None:
        self.path = Path(path)
        self.busy_timeout_ms = busy_timeout_ms
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists():
            self.validate_header()

    @contextmanager
    def connect(self, *, readonly: bool = False) -> Iterator[sqlite3.Connection]:
        uri = f"file:{self.path.as_posix()}?mode=ro" if readonly else str(self.path)
        conn = sqlite3.connect(uri, uri=readonly, timeout=self.busy_timeout_ms / 1000)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute(f"PRAGMA busy_timeout={int(self.busy_timeout_ms)}")
        try:
            yield conn
        finally:
            conn.close()

    def initialize(
        self,
        *,
        project_id: str,
        workspace_id: str | None = None,
        model_identity: dict[str, Any] | None = None,
        save_revision: int = 0,
        initial_snapshot_id: str | None = None,
    ) -> None:
        with self.connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute(f"PRAGMA application_id={APPLICATION_ID}")
            conn.execute("PRAGMA user_version=1")
            conn.executescript(SCHEMA_SQL)
            now = utc_now()
            conn.execute(
                "INSERT OR IGNORE INTO project VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    project_id,
                    "neo",
                    1,
                    save_revision,
                    now,
                    now,
                    None,
                    None,
                    None,
                    None,
                    None,
                    0,
                    canonical_json({}),
                    canonical_json(model_identity or {}),
                    "exact",
                    workspace_id,
                    canonical_json({}),
                ),
            )
            if initial_snapshot_id:
                conn.execute(
                    "INSERT OR IGNORE INTO snapshots VALUES(?,?,?,?,?,?)",
                    (initial_snapshot_id, "initial", 0, now, canonical_json({}), None),
                )
            conn.commit()

    def restore(self, payload: dict[str, Any]) -> int:
        """Install an existing capture without consuming a new save revision."""
        target_revision = int(payload.get("project", {}).get("save_revision", 0))
        self.save(payload, base_save_revision=max(target_revision - 1, 0))
        with self.connect() as conn:
            conn.execute("UPDATE project SET save_revision=?", (target_revision,))
            conn.commit()
        return target_revision

    def validate_header(self) -> None:
        try:
            with self.connect(readonly=True) as conn:
                app_id = conn.execute("PRAGMA application_id").fetchone()[0]
                version = conn.execute("PRAGMA user_version").fetchone()[0]
                if app_id != APPLICATION_ID or version > SCHEMA_VERSION:
                    raise NeoUnsupportedVersionError(
                        f"application_id={app_id}, user_version={version}"
                    )
                result = conn.execute("PRAGMA integrity_check").fetchone()[0]
                if result != "ok":
                    raise NeoCorruptError(result)
                required = {
                    "project",
                    "snapshots",
                    "segments",
                    "edges",
                    "groups",
                    "assets",
                    "reference_entries",
                    "blobs",
                    "asset_refs",
                }
                present = {
                    row[0]
                    for row in conn.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    )
                }
                if not required <= present:
                    raise NeoSchemaError("required table missing")
                required_columns = {
                    "project": {
                        "project_id", "format", "schema_version", "save_revision", "created_at", "updated_at",
                        "head_snapshot_id", "baseline_snapshot_id", "timeline_manifest_id",
                        "checkpoint_partial_id", "checkpoint_working_id", "draft_revision", "draft_payload",
                        "model_identity_json", "model_resolution_status", "workspace_id", "diagnostics_json",
                    },
                    "snapshots": {"snapshot_id", "kind", "revision", "created_at", "config_json", "source_snapshot_id"},
                    "segments": {"segment_id", "snapshot_id", "position", "group_id", "text_json", "binding_json", "parameter_json", "status_json", "formal_asset_id", "edit_context_asset_id"},
                    "edges": {"edge_id", "snapshot_id", "from_segment_id", "to_segment_id", "position", "policy_json", "asset_id", "status_json"},
                    "groups": {"group_id", "snapshot_id", "position", "binding_json", "parameter_json"},
                    "assets": {"asset_id", "kind", "role", "blob_sha256", "media_type", "codec", "byte_count", "duration_ms", "sample_rate", "channels", "ready", "source_revision", "metadata_json"},
                    "reference_entries": {"reference_id", "role", "audio_asset_id", "text_hash", "language", "source", "revision", "status", "metadata_json"},
                    "blobs": {"sha256", "byte_count", "data", "created_at"},
                    "asset_refs": {"owner_type", "owner_id", "asset_id", "purpose"},
                }
                for table, columns in required_columns.items():
                    actual = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
                    if not columns <= actual:
                        raise NeoUnsupportedVersionError(f"required columns missing from {table}")
        except NeoError:
            raise
        except sqlite3.DatabaseError as exc:
            raise NeoCorruptError(str(exc)) from exc
        except Exception as exc:
            raise NeoCorruptError(str(exc)) from exc

    def put_blob(self, data: bytes) -> str:
        digest = sha256_bytes(data)
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                "INSERT OR IGNORE INTO blobs(sha256,byte_count,data,created_at) VALUES(?,?,?,?)",
                (digest, len(data), data, utc_now()),
            )
            conn.commit()
        return digest

    def get_blob(self, digest: str) -> bytes:
        with self.connect(readonly=True) as conn:
            row = conn.execute(
                "SELECT byte_count,data FROM blobs WHERE sha256=?", (digest,)
            ).fetchone()
        if row is None:
            raise NeoClosureError(f"blob {digest} missing")
        data = bytes(row[1])
        if len(data) != row[0] or sha256_bytes(data) != digest:
            raise NeoHashMismatchError(digest)
        return data

    def save(
        self,
        payload: dict[str, Any],
        *,
        expected_save_revision: int | None = None,
        base_save_revision: int | None = None,
    ) -> int:
        """Persist a complete capture payload in one transaction.

        Payload keys mirror the v1 tables; unknown keys are retained in metadata.
        """
        if not self.path.exists() or self.path.stat().st_size == 0:
            self.initialize(
                project_id=str(payload["project"]["project_id"]),
                workspace_id=payload["project"].get("workspace_id"),
                save_revision=base_save_revision or 0,
            )
        try:
            with self.connect() as conn:
                conn.execute("BEGIN IMMEDIATE")
                project = payload["project"]
                _validate_identifier(project.get("project_id", ""), "project id")
                for item in payload.get("snapshots", []):
                    _validate_identifier(item.get("snapshot_id", ""), "snapshot id")
                for item in payload.get("assets", []):
                    _validate_identifier(item.get("asset_id", ""), "asset id")
                for snapshot in payload.get("snapshots", []):
                    for item in snapshot.get("segments", []):
                        _validate_identifier(item.get("segment_id", ""), "segment id")
                    for item in snapshot.get("edges", []):
                        _validate_identifier(item.get("edge_id", ""), "edge id")
                    for item in snapshot.get("groups", []):
                        _validate_identifier(item.get("group_id", ""), "group id")
                for item in payload.get("blobs", []):
                    digest = str(item.get("sha256", ""))
                    if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest.lower()):
                        raise NeoSchemaError("invalid blob sha256")
                row = conn.execute("SELECT save_revision FROM project").fetchone()
                current = int(row[0]) if row else 0
                if (
                    expected_save_revision is not None
                    and current != expected_save_revision
                ):
                    raise NeoWriteBusyError(
                        f"expected revision {expected_save_revision}, got {current}"
                    )
                next_revision = current + 1
                incoming_snapshots = {str(item["snapshot_id"]) for item in payload.get("snapshots", [])}
                incoming_assets = {str(item["asset_id"]) for item in payload.get("assets", [])}
                incoming_blobs = {str(item.get("sha256")) for item in payload.get("blobs", [])}
                referenced_blob_hashes = {
                    str(item.get("blob_sha256"))
                    for item in payload.get("assets", [])
                    if item.get("blob_sha256")
                }
                # Incremental entity maintenance: remove only rows no longer in
                # the captured closure; unchanged BLOB rows remain untouched.
                conn.execute("DELETE FROM asset_refs")
                conn.execute("DELETE FROM reference_entries")
                if incoming_snapshots:
                    placeholders = ",".join("?" for _ in incoming_snapshots)
                    conn.execute(f"DELETE FROM segments WHERE snapshot_id NOT IN ({placeholders})", tuple(incoming_snapshots))
                    conn.execute(f"DELETE FROM edges WHERE snapshot_id NOT IN ({placeholders})", tuple(incoming_snapshots))
                    conn.execute(f"DELETE FROM groups WHERE snapshot_id NOT IN ({placeholders})", tuple(incoming_snapshots))
                    conn.execute(f"DELETE FROM snapshots WHERE kind <> 'initial' AND snapshot_id NOT IN ({placeholders})", tuple(incoming_snapshots))
                    for snapshot_id in incoming_snapshots:
                        conn.execute("DELETE FROM segments WHERE snapshot_id=?", (snapshot_id,))
                        conn.execute("DELETE FROM edges WHERE snapshot_id=?", (snapshot_id,))
                        conn.execute("DELETE FROM groups WHERE snapshot_id=?", (snapshot_id,))
                else:
                    conn.execute("DELETE FROM segments WHERE snapshot_id IN (SELECT snapshot_id FROM snapshots WHERE kind <> 'initial')")
                    conn.execute("DELETE FROM edges WHERE snapshot_id IN (SELECT snapshot_id FROM snapshots WHERE kind <> 'initial')")
                    conn.execute("DELETE FROM groups WHERE snapshot_id IN (SELECT snapshot_id FROM snapshots WHERE kind <> 'initial')")
                    conn.execute("DELETE FROM snapshots WHERE kind <> 'initial'")
                if incoming_assets:
                    placeholders = ",".join("?" for _ in incoming_assets)
                    conn.execute(f"DELETE FROM assets WHERE asset_id NOT IN ({placeholders})", tuple(incoming_assets))
                else:
                    conn.execute("DELETE FROM assets")
                retained_blobs = incoming_blobs | referenced_blob_hashes
                if retained_blobs:
                    placeholders = ",".join("?" for _ in retained_blobs)
                    conn.execute(f"DELETE FROM blobs WHERE sha256 NOT IN ({placeholders})", tuple(retained_blobs))
                else:
                    conn.execute("DELETE FROM blobs")
                for blob in payload.get("blobs", []):
                    data = blob.get("data", b"")
                    if isinstance(data, str):
                        data = data.encode()
                    digest = sha256_bytes(data)
                    if blob.get("sha256", digest) != digest:
                        raise NeoHashMismatchError(digest)
                    conn.execute(
                        "INSERT OR REPLACE INTO blobs VALUES(?,?,?,?)",
                        (digest, len(data), data, blob.get("created_at", utc_now())),
                    )
                for asset in payload.get("assets", []):
                    conn.execute(
                        "INSERT OR REPLACE INTO assets VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (
                            asset["asset_id"],
                            asset["kind"],
                            asset.get("role"),
                            asset.get("blob_sha256"),
                            asset.get("media_type", "application/octet-stream"),
                            asset.get("codec", "raw"),
                            asset.get("byte_count", 0),
                            asset.get("duration_ms"),
                            asset.get("sample_rate"),
                            asset.get("channels"),
                            int(asset.get("ready", 1)),
                            asset.get("source_revision"),
                            canonical_json(
                                asset.get("metadata_json", asset.get("metadata", {}))
                            ),
                        ),
                    )
                for snap in payload.get("snapshots", []):
                    conn.execute(
                        "INSERT OR REPLACE INTO snapshots VALUES(?,?,?,?,?,?)",
                        (
                            snap["snapshot_id"],
                            snap.get("kind", snap.get("snapshot_kind", "head")),
                            snap.get("revision", snap.get("document_version", 0)),
                            snap.get("created_at", utc_now()),
                            canonical_json(
                                snap.get("config_json", snap.get("config", {}))
                            ),
                            snap.get("source_snapshot_id"),
                        ),
                    )
                    sid = snap["snapshot_id"]
                    for pos, seg in enumerate(snap.get("segments", [])):
                        binding = dict(seg.get("binding_json", seg.get("binding", {})) or {})
                        # Legacy callers may not have a resolver binding yet;
                        # retain the row with explicit NULL identity fields so
                        # the v1 shape remains deterministic and inspectable.
                        for key in ("model_id", "model_revision", "preset_id", "preset_revision"):
                            binding.setdefault(key, None)
                        conn.execute(
                            "INSERT INTO segments VALUES(?,?,?,?,?,?,?,?,?,?)",
                            (
                                seg["segment_id"],
                                sid,
                                seg.get("position", pos),
                                seg.get("group_id"),
                                canonical_json(
                                    seg.get("text_json", seg.get("text", seg))
                                ),
                                canonical_json(
                                    binding
                                ),
                                canonical_json(
                                    seg.get("parameter_json", seg.get("parameters", {}))
                                ),
                                canonical_json(
                                    seg.get("status_json", seg.get("status", {}))
                                ),
                                seg.get("formal_asset_id", seg.get("render_asset_id")),
                                seg.get("edit_context_asset_id"),
                            ),
                        )
                    for pos, edge in enumerate(snap.get("edges", [])):
                        conn.execute(
                            "INSERT INTO edges VALUES(?,?,?,?,?,?,?,?)",
                            (
                                edge["edge_id"],
                                sid,
                                edge.get(
                                    "from_segment_id", edge.get("left_segment_id")
                                ),
                                edge.get("to_segment_id", edge.get("right_segment_id")),
                                edge.get("position", pos),
                                canonical_json(
                                    edge.get("policy_json", edge.get("policy", edge))
                                ),
                                edge.get("asset_id"),
                                canonical_json(
                                    edge.get("status_json", edge.get("status", {}))
                                ),
                            ),
                        )
                    for pos, group in enumerate(snap.get("groups", [])):
                        binding = dict(group.get("binding_json", group.get("binding", {})) or {})
                        for key in ("model_id", "model_revision", "preset_id", "preset_revision"):
                            binding.setdefault(key, None)
                        conn.execute(
                            "INSERT INTO groups VALUES(?,?,?,?,?)",
                            (
                                group["group_id"],
                                sid,
                                group.get("position", pos),
                                canonical_json(binding),
                                canonical_json(
                                    group.get(
                                        "parameter_json", group.get("parameters", {})
                                    )
                                ),
                            ),
                        )
                for ref in payload.get(
                    "references", payload.get("reference_entries", [])
                ):
                    conn.execute(
                        "INSERT INTO reference_entries VALUES(?,?,?,?,?,?,?,?,?)",
                        (
                            ref["reference_id"],
                            ref["role"],
                            ref["audio_asset_id"],
                            ref.get("text_hash"),
                            ref.get("language", ""),
                            ref.get("source", "project"),
                            ref.get("revision", 0),
                            ref.get("status", "present"),
                            canonical_json(
                                ref.get("metadata_json", ref.get("metadata", {}))
                            ),
                        ),
                    )
                for ref in payload.get("asset_refs", []):
                    conn.execute(
                        "INSERT INTO asset_refs VALUES(?,?,?,?)",
                        (
                            ref["owner_type"],
                            ref["owner_id"],
                            ref["asset_id"],
                            ref["purpose"],
                        ),
                    )
                conn.execute(
                    "UPDATE project SET save_revision=?,updated_at=?,head_snapshot_id=?,baseline_snapshot_id=?,timeline_manifest_id=?,checkpoint_partial_id=?,checkpoint_working_id=?,draft_revision=?,draft_payload=?,model_identity_json=?,model_resolution_status=?,workspace_id=?,diagnostics_json=?",
                    (
                        next_revision,
                        utc_now(),
                        project.get("head_snapshot_id"),
                        project.get("baseline_snapshot_id"),
                        project.get("timeline_manifest_id"),
                        project.get("checkpoint_partial_id"),
                        project.get("checkpoint_working_id"),
                        project.get("draft_revision", 0),
                        canonical_json(project.get("draft_payload", {})),
                        canonical_json(
                            project.get(
                                "model_identity_json", project.get("model_identity", {})
                            )
                        ),
                        project.get("model_resolution_status", "exact"),
                        project.get("workspace_id"),
                        canonical_json(
                            project.get(
                                "diagnostics_json", project.get("diagnostics", {})
                            )
                        ),
                    ),
                )
                foreign_key_errors = conn.execute("PRAGMA foreign_key_check").fetchall()
                if foreign_key_errors:
                    raise NeoClosureError("foreign key closure is incomplete")
                self._validate_closure(conn)
                conn.commit()
                return next_revision
        except sqlite3.IntegrityError as exc:
            raise NeoClosureError(str(exc)) from exc
        except sqlite3.OperationalError as exc:
            if "locked" in str(exc).lower() or "busy" in str(exc).lower():
                raise NeoWriteBusyError(str(exc)) from exc
            raise

    def _validate_closure(self, conn: sqlite3.Connection) -> None:
        project = conn.execute("SELECT * FROM project").fetchone()
        if project is None:
            raise NeoSchemaError("project row missing")
        if project["format"] != "neo" or int(project["schema_version"]) != SCHEMA_VERSION:
            raise NeoUnsupportedVersionError("project format/schema version mismatch")
        if project["model_resolution_status"] not in {
            "exact", "read_only_degraded", "replacement_checking", "replacement_compatible", "incompatible",
        }:
            raise NeoSchemaError("invalid model resolution status")
        for column in ("head_snapshot_id", "baseline_snapshot_id", "checkpoint_partial_id", "checkpoint_working_id"):
            value = project[column]
            if value is not None and conn.execute(
                "SELECT 1 FROM snapshots WHERE snapshot_id=?", (value,)
            ).fetchone() is None:
                raise NeoClosureError(f"project.{column} references missing snapshot")
        timeline_id = project["timeline_manifest_id"]
        if timeline_id is not None and conn.execute(
            "SELECT 1 FROM assets WHERE asset_id=?", (timeline_id,)
        ).fetchone() is None:
            raise NeoClosureError("project.timeline_manifest_id references missing asset")
        valid_kinds = {"head", "baseline", "working", "initial"}
        for row in conn.execute("SELECT snapshot_id,kind,revision,source_snapshot_id FROM snapshots"):
            if row[1] not in valid_kinds or int(row[2]) < 0:
                raise NeoSchemaError(f"invalid snapshot {row[0]}")
            if row[3] is not None and conn.execute(
                "SELECT 1 FROM snapshots WHERE snapshot_id=?", (row[3],)
            ).fetchone() is None:
                raise NeoClosureError(f"snapshot {row[0]} source snapshot is missing")
            segment_ids = {
                r[0] for r in conn.execute(
                    "SELECT segment_id FROM segments WHERE snapshot_id=?", (row[0],)
                )
            }
            for edge in conn.execute(
                "SELECT edge_id,from_segment_id,to_segment_id FROM edges WHERE snapshot_id=?",
                (row[0],),
            ):
                if edge[1] not in segment_ids or edge[2] not in segment_ids:
                    raise NeoClosureError(f"edge {edge[0]} references missing segment")
            for row2 in conn.execute(
                "SELECT segment_id,group_id,formal_asset_id,edit_context_asset_id FROM segments WHERE snapshot_id=?",
                (row[0],),
            ):
                if row2[1] is not None and conn.execute(
                    "SELECT 1 FROM groups WHERE snapshot_id=? AND group_id=?", (row[0], row2[1])
                ).fetchone() is None:
                    raise NeoClosureError(f"segment {row2[0]} references missing group")
                for asset_id in (row2[2], row2[3]):
                    if asset_id is not None and conn.execute(
                        "SELECT 1 FROM assets WHERE asset_id=?", (asset_id,)
                    ).fetchone() is None:
                        raise NeoClosureError(f"segment {row2[0]} references missing asset")
            for row2 in conn.execute(
                "SELECT segment_id,binding_json FROM segments WHERE snapshot_id=?",
                (row[0],),
            ):
                try:
                    binding = json.loads(row2[1])
                except (TypeError, json.JSONDecodeError) as exc:
                    raise NeoSchemaError(f"segment {row2[0]} binding is not valid JSON") from exc
                if not isinstance(binding, dict):
                    raise NeoSchemaError(f"segment {row2[0]} binding must be an object")
                missing = {"model_id", "model_revision", "preset_id", "preset_revision"} - set(binding)
                if missing:
                    raise NeoSchemaError(f"segment {row2[0]} binding missing {sorted(missing)}")
            for row2 in conn.execute(
                "SELECT edge_id,asset_id FROM edges WHERE snapshot_id=?", (row[0],)
            ):
                if row2[1] is not None and conn.execute(
                    "SELECT 1 FROM assets WHERE asset_id=?", (row2[1],)
                ).fetchone() is None:
                    raise NeoClosureError(f"edge {row2[0]} references missing asset")
            for row2 in conn.execute(
                "SELECT group_id,binding_json FROM groups WHERE snapshot_id=?",
                (row[0],),
            ):
                try:
                    binding = json.loads(row2[1])
                except (TypeError, json.JSONDecodeError) as exc:
                    raise NeoSchemaError(f"group {row2[0]} binding is not valid JSON") from exc
                if not isinstance(binding, dict):
                    raise NeoSchemaError(f"group {row2[0]} binding must be an object")
                missing = {"model_id", "model_revision", "preset_id", "preset_revision"} - set(binding)
                if missing:
                    raise NeoSchemaError(f"group {row2[0]} binding missing {sorted(missing)}")
        valid_asset_kinds = {"formal", "boundary", "timeline", "latent", "trace", "reference_audio", "reference_text", "checkpoint", "preview", "export"}
        for asset in conn.execute("SELECT asset_id,kind,blob_sha256,byte_count,ready FROM assets"):
            if asset[1] not in valid_asset_kinds or int(asset[3]) < 0 or int(asset[4]) not in (0, 1):
                raise NeoSchemaError(f"invalid asset {asset[0]}")
            if int(asset[4]) and not asset[2]:
                raise NeoClosureError(f"ready asset {asset[0]} has no blob")
        bad = conn.execute("""
            SELECT 1 FROM assets a
            LEFT JOIN blobs b ON b.sha256=a.blob_sha256
            WHERE a.blob_sha256 IS NOT NULL AND (b.sha256 IS NULL OR b.byte_count<>a.byte_count OR length(b.data)<>b.byte_count)
        """).fetchone()
        if bad:
            raise NeoClosureError("asset blob missing")
        for row in conn.execute("SELECT sha256,byte_count,data FROM blobs"):
            data = bytes(row[2])
            if len(data) != row[1] or sha256_bytes(data) != row[0]:
                raise NeoHashMismatchError(row[0])
        for ref in conn.execute("SELECT reference_id,role,audio_asset_id,status FROM reference_entries"):
            if ref[1] not in {"speaker", "style"} or ref[3] not in {"present", "missing", "invalid"}:
                raise NeoSchemaError(f"invalid reference {ref[0]}")
            audio = conn.execute("SELECT kind FROM assets WHERE asset_id=?", (ref[2],)).fetchone()
            if audio is None or audio[0] != "reference_audio":
                raise NeoClosureError(f"reference {ref[0]} audio asset is invalid")
            if ref[1] == "speaker" and ref[3] == "present":
                reference = conn.execute(
                    "SELECT text_hash,language FROM reference_entries WHERE reference_id=?", (ref[0],)
                ).fetchone()
                if reference[0] is None or not str(reference[1]).strip():
                    raise NeoSchemaError(f"speaker reference {ref[0]} must freeze text hash and language")

        valid_owner_types = {"project", "snapshot", "segment", "edge", "reference"}
        for ref in conn.execute("SELECT owner_type,owner_id,asset_id,purpose FROM asset_refs"):
            if ref[0] not in valid_owner_types:
                raise NeoSchemaError(f"invalid asset ref owner type {ref[0]}")
            owner_exists = {
                "project": "SELECT 1 FROM project WHERE project_id=?",
                "snapshot": "SELECT 1 FROM snapshots WHERE snapshot_id=?",
                "segment": "SELECT 1 FROM segments WHERE segment_id=?",
                "edge": "SELECT 1 FROM edges WHERE edge_id=?",
                "reference": "SELECT 1 FROM reference_entries WHERE reference_id=?",
            }[ref[0]]
            if conn.execute(owner_exists, (ref[1],)).fetchone() is None:
                raise NeoClosureError(f"asset ref owner {ref[0]}:{ref[1]} is missing")

    def load(self) -> dict[str, Any]:
        self.validate_header()
        with self.connect(readonly=True) as conn:
            self._validate_closure(conn)
            project = dict(conn.execute("SELECT * FROM project").fetchone())
            for key in ("draft_payload", "model_identity_json", "diagnostics_json"):
                project[key] = json.loads(project[key])
            snapshots = []
            for row in conn.execute(
                "SELECT * FROM snapshots ORDER BY revision,snapshot_id"
            ):
                snap = dict(row)
                snap["config_json"] = json.loads(snap["config_json"])
                sid = snap["snapshot_id"]
                snap["segments"] = [
                    self._decode_entity_json(dict(r), ("text_json", "binding_json", "parameter_json", "status_json"))
                    for r in conn.execute(
                        "SELECT * FROM segments WHERE snapshot_id=? ORDER BY position",
                        (sid,),
                    )
                ]
                snap["edges"] = [
                    self._decode_entity_json(dict(r), ("policy_json", "status_json"))
                    for r in conn.execute(
                        "SELECT * FROM edges WHERE snapshot_id=? ORDER BY position",
                        (sid,),
                    )
                ]
                snap["groups"] = [
                    self._decode_entity_json(dict(r), ("binding_json", "parameter_json"))
                    for r in conn.execute(
                        "SELECT * FROM groups WHERE snapshot_id=? ORDER BY position",
                        (sid,),
                    )
                ]
                snapshots.append(snap)
            assets = [
                self._decode_entity_json(dict(r), ("metadata_json",))
                for r in conn.execute("SELECT * FROM assets")
            ]
            refs = [
                self._decode_entity_json(dict(r), ("metadata_json",))
                for r in conn.execute("SELECT * FROM reference_entries")
            ]
            return {
                "project": project,
                "snapshots": snapshots,
                "assets": assets,
                "references": refs,
                "asset_refs": [
                    dict(r) for r in conn.execute("SELECT * FROM asset_refs")
                ],
                "blobs": [
                    {"sha256": r[0], "byte_count": r[1], "data": bytes(r[2])}
                    for r in conn.execute("SELECT sha256,byte_count,data FROM blobs")
                ],
            }

    @staticmethod
    def _decode_entity_json(row: dict[str, Any], columns: tuple[str, ...]) -> dict[str, Any]:
        for column in columns:
            if column not in row:
                continue
            try:
                row[column] = json.loads(row[column])
            except (TypeError, json.JSONDecodeError) as exc:
                raise NeoCorruptError(f"invalid JSON in {column}") from exc
        return row
