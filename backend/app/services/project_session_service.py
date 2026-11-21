"""Workspace lifecycle and capture coordination for S3 project files."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import hashlib
import os
from pathlib import Path
import sqlite3
import threading
from typing import Any, Iterator
from uuid import uuid4

from backend.app.services.project_store import (
    NeoClosureError,
    NeoHashMismatchError,
    NeoTargetBusyError,
    NeoWriteBusyError,
    ProjectStore,
    sha256_bytes,
)
from backend.app.core.exceptions import AssetNotFoundError
from backend.app.services.session_reference_asset_service import (
    SessionReferenceAsset,
    SessionReferenceAssetService,
)
from backend.app.inference.asset_fingerprint import fingerprint_text
from backend.app.inference.editable_types import build_boundary_asset_id
from backend.app.schemas.edit_session import (
    ActiveDocumentState,
    DocumentSnapshot,
    EditableEdge,
    EditableSegment,
    InitializeEditSessionRequest,
    SegmentGroup,
    RenderProfile,
    VoiceBinding,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class CaptureToken:
    workspace_id: str
    project_id: str
    head_revision: int = 0
    baseline_revision: int = 0
    timeline_revision: int = 0
    checkpoint_partial_revision: int = 0
    checkpoint_working_revision: int = 0
    draft_revision: int = 0
    input_revision: int = 0
    reference_hashes: dict[str, str] | None = None
    root_asset_ids: tuple[str, ...] = ()
    expected_save_revision: int = 0
    created_at: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "workspace_id": self.workspace_id,
            "project_id": self.project_id,
            "head_revision": self.head_revision,
            "baseline_revision": self.baseline_revision,
            "timeline_revision": self.timeline_revision,
            "checkpoint_partial_revision": self.checkpoint_partial_revision,
            "checkpoint_working_revision": self.checkpoint_working_revision,
            "draft_revision": self.draft_revision,
            "input_revision": self.input_revision,
            "reference_hashes": self.reference_hashes or {},
            "root_asset_ids": list(self.root_asset_ids),
            "expected_save_revision": self.expected_save_revision,
            "created_at": self.created_at,
        }


class ProjectSessionService:
    def __init__(
        self,
        *,
        user_data_root: str | Path,
        workspace_id: str | None = None,
        asset_store: object | None = None,
        model_catalog: object | None = None,
        edit_session_repository: object | None = None,
        session_reference_asset_service: SessionReferenceAssetService | None = None,
    ) -> None:
        self.user_data_root = Path(user_data_root).resolve()
        self.workspaces_root = self.user_data_root / "workspaces"
        self.workspaces_root.mkdir(parents=True, exist_ok=True)
        self.workspace_id = workspace_id
        self._lock = threading.RLock()
        self._gc_lock = threading.RLock()
        self._pins: dict[str, int] = {}
        self._asset_store = asset_store
        self._model_catalog = model_catalog
        self._edit_session_repository = edit_session_repository
        if session_reference_asset_service is not None:
            self._session_reference_asset_service = session_reference_asset_service
        elif asset_store is not None and hasattr(asset_store, "assets_root"):
            self._session_reference_asset_service = SessionReferenceAssetService(
                assets_root=Path(asset_store.assets_root)
            )
        else:
            self._session_reference_asset_service = None
        self.current_capability = self.capability_for_status("exact")
        self.last_model_diagnostics: dict[str, Any] = {}

    @staticmethod
    def capability_for_status(status: str) -> dict[str, bool]:
        if status == "exact":
            return {"play": True, "export": True, "edit": True, "render": True, "boundary": True}
        # ``replacement_checking`` and ``replacement_compatible`` are only
        # forward-compatible values reserved for a later S2/S7 replacement
        # workflow.  S3 never produces or validates either state, so opening
        # such a file must remain degraded rather than unlocking edits based
        # on an unverified candidate model.
        return {"play": True, "export": True, "edit": False, "render": False, "boundary": False}

    @staticmethod
    def _validate_logical_id(value: str, label: str) -> str:
        normalized = str(value).strip()
        if not normalized or normalized in {".", ".."} or any(separator in normalized for separator in ("/", "\\")):
            raise ValueError(f"invalid {label}")
        return normalized

    def set_model_catalog(self, catalog: object | None) -> None:
        """Install the S2 resolver without copying or owning its catalog."""
        self._model_catalog = catalog

    def set_edit_session_repository(self, repository: object | None) -> None:
        self._edit_session_repository = repository

    def _workspace_path(self, workspace_id: str) -> Path:
        if (
            not workspace_id
            or Path(workspace_id).name != workspace_id
            or any(c in workspace_id for c in "/\\")
        ):
            raise ValueError("invalid workspace id")
        path = (self.workspaces_root / workspace_id).resolve()
        if self.workspaces_root not in path.parents:
            raise ValueError("workspace escapes root")
        return path

    @property
    def workspace_path(self) -> Path:
        if self.workspace_id is None:
            raise RuntimeError("workspace not initialized")
        return self._workspace_path(self.workspace_id)

    @property
    def session_db(self) -> Path:
        return self.workspace_path / "session.db"

    def _prepare_save_workspace(
        self,
        payload: dict[str, Any],
        token: CaptureToken | None,
    ) -> str:
        """Validate the capture and lazily create its first workspace.

        The application service is constructed before a project is selected,
        so ``workspace_id`` is intentionally unset during startup.  A first
        save is still a valid way to materialize a project, but only when the
        request contains a usable project identity.  A non-zero capture
        revision is evidence that the caller expected an existing target; do
        not create a new empty workspace and turn that stale/invalid request
        into an apparently valid save.
        """
        if not isinstance(payload, dict):
            raise ValueError("project payload is required")
        project = payload.get("project")
        if not isinstance(project, dict):
            raise ValueError("project payload is required")
        raw_project_id = project.get("project_id")
        if raw_project_id is None:
            raise ValueError("project id is required")
        project_id = self._validate_logical_id(str(raw_project_id), "project id")

        if self.workspace_id is None:
            if token is not None and token.expected_save_revision != 0:
                # Preserve the pre-existing initialization failure for a
                # token that refers to a prior save.  Creating a blank
                # workspace here would bypass the expected-revision check.
                # Surface it as the same stable conflict used for an
                # existing target whose revision no longer matches.  The
                # router previously treated the RuntimeError as a generic
                # NEO_STORAGE_ERROR, which made a stale first-save request
                # look like an infrastructure failure to the client.
                raise NeoWriteBusyError("workspace not initialized")
            with self._lock:
                if self.workspace_id is None:
                    self.create_workspace(project_id=project_id)
        return project_id

    def create_workspace(
        self, *, project_id: str | None = None, workspace_id: str | None = None
    ) -> Path:
        with self._lock:
            wid = workspace_id or uuid4().hex
            root = self._workspace_path(wid)
            root.mkdir(parents=True, exist_ok=False)
            for child in (
                "assets/formal",
                "assets/references",
                "assets/staging",
                "preview",
                "exports",
            ):
                (root / child).mkdir(parents=True, exist_ok=True)
            pid = self._validate_logical_id(project_id or uuid4().hex, "project id")
            ProjectStore(root / "session.db").initialize(
                project_id=pid, workspace_id=wid, initial_snapshot_id=f"initial-{pid}"
            )
            (root / "workspace.json").write_text(
                json.dumps(
                    {
                        "workspace_id": wid,
                        "project_id": pid,
                        "created_at": _now(),
                        "last_opened_at": _now(),
                        "last_save_revision": 0,
                        "dirty": False,
                        "schema_version": 1,
                    },
                    sort_keys=True,
                ),
                encoding="utf-8",
            )
            self.workspace_id = wid
            self.current_capability = self.capability_for_status("exact")
            self.last_model_diagnostics = {}
            return root

    def mark_dirty(self, dirty: bool = True) -> None:
        path = self.workspace_path / "workspace.json"
        data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        data["dirty"] = dirty
        data["last_opened_at"] = _now()
        path.write_text(json.dumps(data, sort_keys=True), encoding="utf-8")

    @contextmanager
    def pin_assets(self, asset_ids: Iterator[str] | list[str] | set[str]) -> Iterator[None]:
        """Pin a captured asset closure across save/play/export/GC operations."""
        ids = [str(asset_id) for asset_id in asset_ids]
        with self._gc_lock:
            for asset_id in ids:
                self._pins[asset_id] = self._pins.get(asset_id, 0) + 1
        try:
            yield
        finally:
            with self._gc_lock:
                for asset_id in ids:
                    count = self._pins.get(asset_id, 0) - 1
                    if count > 0:
                        self._pins[asset_id] = count
                    else:
                        self._pins.pop(asset_id, None)

    def pinned_asset_ids(self) -> set[str]:
        with self._gc_lock:
            return set(self._pins)

    @contextmanager
    def read_assets(self, asset_ids: Iterator[str] | list[str] | set[str]) -> Iterator[None]:
        """Pin formal assets for the lifetime of a playback/read operation."""
        with self.pin_assets(asset_ids):
            yield

    def capture_token(
        self, state: dict[str, Any], *, reference_hashes: dict[str, str] | None = None
    ) -> CaptureToken:
        project = state.get("project", state)
        return CaptureToken(
            workspace_id=self.workspace_id or str(project.get("workspace_id", "")),
            project_id=str(project.get("project_id", "")),
            head_revision=int(
                project.get("head_revision", project.get("head_document_version", 0))
            ),
            baseline_revision=int(project.get("baseline_revision", 0)),
            timeline_revision=int(project.get("timeline_revision", 0)),
            checkpoint_partial_revision=int(
                project.get("checkpoint_partial_revision", 0)
            ),
            checkpoint_working_revision=int(
                project.get("checkpoint_working_revision", 0)
            ),
            draft_revision=int(project.get("draft_revision", 0)),
            input_revision=int(project.get("input_revision", 0)),
            reference_hashes=reference_hashes or {},
            root_asset_ids=tuple(
                sorted(
                    {
                        str(item.get("asset_id")) if isinstance(item, dict) else str(item)
                        for item in state.get("assets", project.get("asset_ids", []))
                        if (isinstance(item, dict) and item.get("asset_id")) or isinstance(item, str)
                    }
                )
            ),
            expected_save_revision=int(project.get("save_revision", 0)),
            created_at=_now(),
        )

    @staticmethod
    def is_token_stale(token: CaptureToken, state: dict[str, Any]) -> bool:
        project = state.get("project", state)
        fields = (
            ("head_revision", token.head_revision),
            ("baseline_revision", token.baseline_revision),
            ("timeline_revision", token.timeline_revision),
            ("checkpoint_partial_revision", token.checkpoint_partial_revision),
            ("checkpoint_working_revision", token.checkpoint_working_revision),
            ("draft_revision", token.draft_revision),
            ("input_revision", token.input_revision),
        )
        # A caller may provide a partial capture payload (for example while a
        # checkpoint is still being materialized). Missing counters are not
        # evidence of a new edit; only counters explicitly present in the
        # payload can invalidate the token.
        return any(
            name in project and int(project[name]) != expected
            for name, expected in fields
        ) or (
            "reference_hashes" in project
            and token.reference_hashes is not None
            and dict(project.get("reference_hashes") or {}) != dict(token.reference_hashes)
        )

    def save(
        self,
        payload: dict[str, Any],
        token: CaptureToken | None = None,
        *,
        target: str | Path | None = None,
        force_partial: bool = False,
    ) -> int:
        # Resolve the workspace before taking the cross-process lock.  The
        # service starts without an active workspace in the application
        # lifespan, and ``_workspace_write_lock`` necessarily needs a real
        # workspace path to create/open its lock file.
        self._prepare_save_workspace(payload, token)
        # Register every captured asset before the writer releases the session
        # lock.  GC observes the pin count under the same workspace mutex and
        # therefore cannot delete an asset between closure capture and replace.
        asset_ids = {
            str(item["asset_id"])
            for item in payload.get("assets", [])
            if isinstance(item, dict) and item.get("asset_id")
        }
        asset_ids.update(
            str(item["asset_id"])
            for item in payload.get("asset_refs", [])
            if isinstance(item, dict) and item.get("asset_id")
        )
        if token is not None:
            asset_ids.update(token.root_asset_ids)
        payload = self._augment_payload_from_edit_session(payload)
        asset_ids.update(
            str(item["asset_id"])
            for item in payload.get("assets", [])
            if isinstance(item, dict) and item.get("asset_id")
        )
        with self.pin_assets(asset_ids):
            hydrated = self._hydrate_payload_assets(payload)
            return self._save_impl(hydrated, token, target=target, force_partial=force_partial)

    def _augment_payload_from_edit_session(self, payload: dict[str, Any]) -> dict[str, Any]:
        repository = self._edit_session_repository
        if repository is None or not hasattr(repository, "get_active_session"):
            return payload
        active = repository.get_active_session()
        if active is None or not active.head_snapshot_id:
            return payload
        requested_project_id = str(payload.get("project", {}).get("project_id", ""))
        if requested_project_id and requested_project_id != active.document_id:
            return payload
        snapshot_ids: list[str] = []
        for snapshot_id in (active.head_snapshot_id, active.baseline_snapshot_id):
            if snapshot_id and snapshot_id not in snapshot_ids:
                snapshot_ids.append(snapshot_id)
        checkpoint = repository.get_latest_checkpoint(active.document_id)
        if checkpoint is not None:
            for snapshot_id in (checkpoint.head_snapshot_id, checkpoint.working_snapshot_id):
                if snapshot_id and snapshot_id not in snapshot_ids:
                    snapshot_ids.append(snapshot_id)
        snapshots: list[dict[str, Any]] = []
        assets_by_id = {
            str(item.get("asset_id")): dict(item)
            for item in payload.get("assets", [])
            if isinstance(item, dict) and item.get("asset_id")
        }
        asset_refs = [dict(item) for item in payload.get("asset_refs", []) if isinstance(item, dict)]
        for snapshot_id in snapshot_ids:
            snapshot = repository.get_snapshot(snapshot_id)
            if snapshot is None:
                continue
            converted = self._snapshot_to_payload(snapshot)
            snapshots.append(converted)
            for asset in converted.pop("_assets", []):
                assets_by_id[str(asset["asset_id"])] = asset
            asset_refs.extend(converted.pop("_asset_refs", []))
        if not snapshots:
            return payload
        valid_snapshot_ids = {str(item["snapshot_id"]) for item in snapshots}
        valid_segment_ids = {
            str(segment["segment_id"])
            for item in snapshots
            for segment in item.get("segments", [])
        }
        valid_edge_ids = {
            str(edge["edge_id"])
            for item in snapshots
            for edge in item.get("edges", [])
        }
        asset_refs = [
            ref
            for ref in asset_refs
            if ref.get("owner_type") not in {"snapshot", "segment", "edge"}
            or (
                ref.get("owner_type") == "snapshot" and str(ref.get("owner_id")) in valid_snapshot_ids
            )
            or (
                ref.get("owner_type") == "segment" and str(ref.get("owner_id")) in valid_segment_ids
            )
            or (
                ref.get("owner_type") == "edge" and str(ref.get("owner_id")) in valid_edge_ids
            )
        ]
        project = dict(payload.get("project", {}))
        project.update(
            {
                "project_id": active.document_id,
                "head_snapshot_id": active.head_snapshot_id,
                "baseline_snapshot_id": active.baseline_snapshot_id,
            }
        )
        if checkpoint is not None:
            project["checkpoint_partial_id"] = checkpoint.head_snapshot_id
            project["checkpoint_working_id"] = checkpoint.working_snapshot_id
            project["timeline_manifest_id"] = checkpoint.timeline_manifest_id
        elif snapshots:
            project["timeline_manifest_id"] = snapshots[0].get("config", {}).get("timeline_manifest_id")
        augmented = dict(payload)
        augmented["project"] = project
        augmented["snapshots"] = snapshots
        augmented["assets"] = list(assets_by_id.values())
        unique_refs: dict[tuple[str, str, str, str], dict[str, Any]] = {}
        for ref in asset_refs:
            key = (
                str(ref.get("owner_type", "")),
                str(ref.get("owner_id", "")),
                str(ref.get("asset_id", "")),
                str(ref.get("purpose", "")),
            )
            unique_refs[key] = ref
        augmented["asset_refs"] = list(unique_refs.values())
        augmented = self._augment_timeline_block_assets(augmented)
        return self._augment_reference_assets(
            augmented,
            session_id=active.document_id,
        )

    def _augment_timeline_block_assets(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Expand block assets referenced by timeline manifests into the capture closure.

        A timeline manifest stores ``block_asset_id`` values inside its JSON
        payload.  ProjectStore only validates explicit asset rows/refs, so
        these nested references must be promoted to first-class assets before
        hydration; otherwise an imported project has a playable manifest but
        no block audio/metadata on disk.
        """
        store = self._asset_store
        if store is None or not hasattr(store, "timeline_manifest_path"):
            return payload
        assets = [dict(item) for item in payload.get("assets", []) if isinstance(item, dict)]
        refs = [dict(item) for item in payload.get("asset_refs", []) if isinstance(item, dict)]
        known = {str(item.get("asset_id")) for item in assets if item.get("asset_id")}
        for timeline in list(assets):
            if str(timeline.get("kind", "")) != "timeline" and str(timeline.get("role", "")) != "timeline":
                continue
            timeline_id = str(timeline.get("asset_id", ""))
            if not timeline_id:
                continue
            try:
                manifest_path = store.timeline_manifest_path(timeline_id) / "manifest.json"
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            except (AttributeError, OSError, ValueError, json.JSONDecodeError):
                continue
            entries = manifest.get("block_entries", []) if isinstance(manifest, dict) else []
            if not isinstance(entries, list):
                continue
            for entry in entries:
                if not isinstance(entry, dict) or not entry.get("block_asset_id"):
                    continue
                block_id = str(entry["block_asset_id"])
                if block_id not in known:
                    assets.append({
                        "asset_id": block_id,
                        "kind": "formal",
                        "role": "block",
                        "media_type": "audio/wav",
                        "codec": "raw",
                        "byte_count": 0,
                        "ready": 0,
                        "metadata": {"format_version": 1},
                    })
                    known.add(block_id)
                owner_id = next(
                    (str(ref.get("owner_id")) for ref in refs
                     if ref.get("asset_id") == timeline_id and ref.get("owner_type") == "snapshot"),
                    timeline_id,
                )
                refs.append({
                    "owner_type": "snapshot" if owner_id != timeline_id else "timeline",
                    "owner_id": owner_id,
                    "asset_id": block_id,
                    "purpose": "block",
                })
        deduped: dict[tuple[str, str, str, str], dict[str, Any]] = {}
        for ref in refs:
            key = (str(ref.get("owner_type", "")), str(ref.get("owner_id", "")), str(ref.get("asset_id", "")), str(ref.get("purpose", "")))
            deduped[key] = ref
        return {**payload, "assets": assets, "asset_refs": list(deduped.values())}

    @staticmethod
    def _snapshot_to_payload(snapshot: DocumentSnapshot) -> dict[str, Any]:
        bindings = {binding.voice_binding_id: binding.model_dump(mode="json") for binding in snapshot.voice_bindings}
        assets: list[dict[str, Any]] = []
        refs: list[dict[str, Any]] = []
        segments: list[dict[str, Any]] = []
        for position, segment in enumerate(snapshot.segments):
            binding = dict(bindings.get(segment.voice_binding_id or "", {}))
            for key in ("model_id", "model_revision", "preset_id", "preset_revision"):
                binding.setdefault(key, None)
            asset_id = segment.render_asset_id
            if asset_id:
                assets.append({
                    "asset_id": asset_id,
                    "kind": "formal",
                    "role": "segment",
                    "media_type": "audio/wav",
                    "codec": "raw",
                    "byte_count": 0,
                    "ready": 0,
                    "metadata": {"format_version": 1},
                })
                refs.append({"owner_type": "segment", "owner_id": segment.segment_id, "asset_id": asset_id, "purpose": "formal"})
            segments.append({
                "segment_id": segment.segment_id,
                "position": position,
                "group_id": segment.group_id,
                "text": {
                    "stem": segment.stem,
                    "terminal_raw": segment.terminal_raw,
                    "terminal_closer_suffix": segment.terminal_closer_suffix,
                    "terminal_source": segment.terminal_source,
                    "text_language": segment.text_language,
                },
                "binding": binding,
                "parameters": segment.inference_override,
                "status": {
                    "render_status": segment.render_status,
                    "render_version": segment.render_version,
                    "segment_revision": segment.segment_revision,
                    "risk_flags": segment.risk_flags,
                },
                "formal_asset_id": asset_id,
            })
        segments_by_id = {segment.segment_id: segment for segment in snapshot.segments}
        edges = []
        for position, edge in enumerate(snapshot.edges):
            edges.append({
                "edge_id": edge.edge_id,
                "position": position,
                "from_segment_id": edge.left_segment_id,
                "to_segment_id": edge.right_segment_id,
                "policy": {
                    "pause_duration_seconds": edge.pause_duration_seconds,
                    "boundary_strategy": edge.boundary_strategy,
                    "effective_boundary_strategy": edge.effective_boundary_strategy,
                },
                "status": {"edge_status": edge.edge_status, "edge_version": edge.edge_version},
            })
            left = segments_by_id.get(edge.left_segment_id)
            right = segments_by_id.get(edge.right_segment_id)
            if left is None or right is None or not left.render_asset_id or not right.render_asset_id:
                continue
            boundary_asset_id = build_boundary_asset_id(
                left_segment_id=edge.left_segment_id,
                left_render_version=left.render_version,
                right_segment_id=edge.right_segment_id,
                right_render_version=right.render_version,
                edge_version=edge.edge_version,
                boundary_strategy=edge.effective_boundary_strategy or edge.boundary_strategy,
            )
            assets.append({
                "asset_id": boundary_asset_id,
                "kind": "boundary",
                "role": "boundary",
                "media_type": "audio/wav",
                "codec": "raw",
                "byte_count": 0,
                "ready": 0,
                "metadata": {"format_version": 1},
            })
            refs.append({
                "owner_type": "edge",
                "owner_id": edge.edge_id,
                "asset_id": boundary_asset_id,
                "purpose": "boundary",
            })
        if snapshot.timeline_manifest_id:
            assets.append({
                "asset_id": snapshot.timeline_manifest_id,
                "kind": "timeline",
                "role": "timeline",
                "media_type": "application/json",
                "codec": "json",
                "byte_count": 0,
                "ready": 0,
                "metadata": {"format_version": 1},
            })
            refs.append({"owner_type": "snapshot", "owner_id": snapshot.snapshot_id, "asset_id": snapshot.timeline_manifest_id, "purpose": "timeline"})
        return {
            "snapshot_id": snapshot.snapshot_id,
            "kind": "working" if snapshot.snapshot_kind == "staging" else snapshot.snapshot_kind,
            "revision": snapshot.document_version,
            "config": {
                "default_render_profile_id": snapshot.default_render_profile_id,
                "default_voice_binding_id": snapshot.default_voice_binding_id,
                "timeline_manifest_id": snapshot.timeline_manifest_id,
                "groups": [group.model_dump(mode="json") for group in snapshot.groups],
                "render_profiles": [profile.model_dump(mode="json") for profile in snapshot.render_profiles],
                "voice_bindings": [binding.model_dump(mode="json") for binding in snapshot.voice_bindings],
            },
            "segments": segments,
            "edges": edges,
            "groups": [group.model_dump(mode="json") for group in snapshot.groups],
            "_assets": assets,
            "_asset_refs": refs,
        }

    def _augment_reference_assets(
        self,
        payload: dict[str, Any],
        *,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        """Freeze session reference overrides into the portable asset closure.

        The live edit-session stores only a logical ``session_reference_asset_id``
        in render-profile overrides.  A project capture must copy the managed
        audio bytes and the text/language fingerprints into the v1 tables so a
        different workspace does not depend on the old absolute path.  Style
        conditioning is intentionally not inferred here; S4 has not defined a
        runtime reference contract yet.
        """
        assets = [dict(item) for item in payload.get("assets", []) if isinstance(item, dict)]
        blobs = [dict(item) for item in payload.get("blobs", []) if isinstance(item, dict)]
        references = [
            dict(item)
            for item in payload.get("references", payload.get("reference_entries", []))
            if isinstance(item, dict)
        ]
        asset_refs = [dict(item) for item in payload.get("asset_refs", []) if isinstance(item, dict)]
        assets_by_id = {
            str(item.get("asset_id")): item
            for item in assets
            if item.get("asset_id")
        }
        blobs_by_digest = {
            str(item.get("sha256")): item
            for item in blobs
            if item.get("sha256")
        }
        references_by_id = {
            str(item.get("reference_id")): item
            for item in references
            if item.get("reference_id")
        }
        asset_ref_keys = {
            (
                str(item.get("owner_type", "")),
                str(item.get("owner_id", "")),
                str(item.get("asset_id", "")),
                str(item.get("purpose", "")),
            )
            for item in asset_refs
        }

        # A payload may be supplied directly by a non-UI caller.  In that case
        # only a session override with a managed ID is safe to materialize; an
        # arbitrary preset path remains an external dependency and is not
        # silently copied into a project file.
        candidates: list[tuple[str, dict[str, Any], int]] = []
        for snapshot in payload.get("snapshots", []):
            if not isinstance(snapshot, dict):
                continue
            config = snapshot.get("config_json", snapshot.get("config", {}))
            if not isinstance(config, dict):
                continue
            revision = int(snapshot.get("revision", snapshot.get("document_version", 0)) or 0)
            for profile in config.get("render_profiles", []):
                if not isinstance(profile, dict):
                    continue
                overrides = profile.get("reference_overrides_by_binding", {})
                if not isinstance(overrides, dict):
                    continue
                for binding_key, raw_override in overrides.items():
                    if not isinstance(raw_override, dict):
                        continue
                    reference_asset_id = raw_override.get("session_reference_asset_id")
                    if reference_asset_id:
                        candidates.append((str(binding_key), raw_override, revision))

        if not candidates:
            return self._with_reference_hashes(payload, references)

        for binding_key, override, revision in candidates:
            reference_asset_id = self._validate_logical_id(
                str(override["session_reference_asset_id"]),
                "session reference asset id",
            )
            reference_id = f"speaker-{reference_asset_id}"
            audio_asset_id = f"reference-audio-{reference_asset_id}"
            captured = self._read_session_reference_capture(
                session_id=session_id,
                reference_asset_id=reference_asset_id,
                override=override,
            )
            existing_asset = assets_by_id.get(audio_asset_id)
            if existing_asset is None:
                existing_asset = {
                    "asset_id": audio_asset_id,
                    "kind": "reference_audio",
                    "role": "speaker",
                    "media_type": captured["media_type"],
                    "codec": "raw",
                    "byte_count": captured["byte_count"],
                    "ready": int(captured["ready"]),
                    "metadata": captured["metadata"],
                }
                if captured["blob_sha256"]:
                    existing_asset["blob_sha256"] = captured["blob_sha256"]
                assets.append(existing_asset)
                assets_by_id[audio_asset_id] = existing_asset
            else:
                # The same managed reference can be bound to multiple profiles;
                # retain the one BLOB identity and merge only diagnostic binding
                # keys.  A changed file is rejected by _read_session_reference_capture.
                existing_asset.update(
                    {
                        "kind": "reference_audio",
                        "role": "speaker",
                        "media_type": captured["media_type"],
                        "codec": "raw",
                        "byte_count": captured["byte_count"],
                        "ready": int(captured["ready"]),
                    }
                )
                if captured["blob_sha256"]:
                    existing_asset["blob_sha256"] = captured["blob_sha256"]
                else:
                    existing_asset.pop("blob_sha256", None)
                existing_metadata = existing_asset.get("metadata", {})
                if not isinstance(existing_metadata, dict):
                    existing_metadata = {}
                existing_metadata = {**dict(existing_metadata), **captured["metadata"]}
                existing_keys = existing_metadata.get("binding_keys", [])
                if not isinstance(existing_keys, list):
                    existing_keys = []
                if binding_key not in existing_keys:
                    existing_keys.append(binding_key)
                existing_metadata["binding_keys"] = sorted({str(item) for item in existing_keys})
                existing_asset["metadata"] = existing_metadata

            if captured["blob_sha256"] and captured["data"] is not None:
                digest = str(captured["blob_sha256"])
                if digest not in blobs_by_digest:
                    blob = {
                        "sha256": digest,
                        "byte_count": len(captured["data"]),
                        "data": captured["data"],
                    }
                    blobs.append(blob)
                    blobs_by_digest[digest] = blob

            existing_reference = references_by_id.get(reference_id)
            if existing_reference is None:
                existing_reference = {
                    "reference_id": reference_id,
                    "role": "speaker",
                    "audio_asset_id": audio_asset_id,
                    "text_hash": captured["text_hash"],
                    "language": captured["language"],
                    "source": "session_override",
                    "revision": revision,
                    "status": captured["status"],
                    "metadata": {
                        **captured["metadata"],
                        "binding_keys": [binding_key],
                    },
                }
                references.append(existing_reference)
                references_by_id[reference_id] = existing_reference
            else:
                if (
                    existing_reference.get("text_hash") != captured["text_hash"]
                    or existing_reference.get("language", "") != captured["language"]
                ):
                    existing_reference["status"] = "invalid"
                metadata = existing_reference.get("metadata", {})
                if not isinstance(metadata, dict):
                    metadata = {}
                keys = metadata.get("binding_keys", [])
                if not isinstance(keys, list):
                    keys = []
                if binding_key not in keys:
                    keys.append(binding_key)
                metadata["binding_keys"] = sorted({str(item) for item in keys})
                existing_reference["metadata"] = metadata

            ref_key = ("reference", reference_id, audio_asset_id, "audio")
            if ref_key not in asset_ref_keys:
                asset_refs.append(
                    {
                        "owner_type": "reference",
                        "owner_id": reference_id,
                        "asset_id": audio_asset_id,
                        "purpose": "audio",
                    }
                )
                asset_ref_keys.add(ref_key)

        augmented = dict(payload)
        augmented["assets"] = assets
        augmented["blobs"] = blobs
        augmented["references"] = references
        augmented["asset_refs"] = asset_refs
        return self._with_reference_hashes(augmented, references)

    def _with_reference_hashes(
        self,
        payload: dict[str, Any],
        references: list[dict[str, Any]],
    ) -> dict[str, Any]:
        hashes: dict[str, str] = {}
        assets_by_id = {
            str(item.get("asset_id")): item
            for item in payload.get("assets", [])
            if isinstance(item, dict) and item.get("asset_id")
        }
        for reference in references:
            if not isinstance(reference, dict):
                continue
            metadata = reference.get("metadata", reference.get("metadata_json", {}))
            metadata = metadata if isinstance(metadata, dict) else {}
            binding_keys = metadata.get("binding_keys", [])
            if not isinstance(binding_keys, list):
                binding_keys = []
            asset = assets_by_id.get(str(reference.get("audio_asset_id")), {})
            asset_metadata = asset.get("metadata", asset.get("metadata_json", {})) if isinstance(asset, dict) else {}
            asset_metadata = asset_metadata if isinstance(asset_metadata, dict) else {}
            audio_hash = str(
                asset_metadata.get("reference_audio_fingerprint")
                or asset.get("blob_sha256", "")
                or ""
            )
            text_hash = str(reference.get("text_hash") or "")
            language = str(reference.get("language") or "")
            value = "|".join((audio_hash, text_hash, language))
            for binding_key in binding_keys:
                hashes[str(binding_key)] = value
        if not hashes:
            return payload
        augmented = dict(payload)
        project = dict(payload.get("project", {}))
        project["reference_hashes"] = hashes
        augmented["project"] = project
        return augmented

    def _read_session_reference_capture(
        self,
        *,
        session_id: str | None,
        reference_asset_id: str,
        override: dict[str, Any],
    ) -> dict[str, Any]:
        """Read and verify one managed reference without leaking its path."""
        fallback_text = str(override.get("reference_text") or "")
        fallback_language = str(override.get("reference_language") or "")
        fallback_text_hash = str(override.get("reference_text_fingerprint") or "") or None
        metadata: dict[str, Any] = {
            "reference_asset_id": reference_asset_id,
            "session_id": session_id,
            "reference_identity": override.get("reference_identity"),
            "reference_text": fallback_text,
            "reference_language": fallback_language,
            "reference_text_fingerprint": fallback_text_hash,
            "reference_audio_fingerprint": override.get("reference_audio_fingerprint"),
            "binding_keys": [],
        }
        asset: SessionReferenceAsset | None = None
        if self._session_reference_asset_service is not None and session_id:
            try:
                asset = self._session_reference_asset_service.get_asset(
                    session_id=session_id,
                    reference_asset_id=reference_asset_id,
                )
            except (AssetNotFoundError, ValueError, OSError):
                asset = None

        audio_path: Path | None = None
        if asset is not None:
            metadata.update(
                {
                    "reference_identity": f"{asset.session_id}:{asset.reference_asset_id}",
                    "reference_text": asset.reference_text,
                    "reference_language": asset.reference_language,
                    "reference_text_fingerprint": asset.reference_text_fingerprint,
                    "reference_audio_fingerprint": asset.audio_fingerprint,
                    "audio_suffix": Path(asset.audio_path).suffix.lower() or ".wav",
                    "created_at": asset.created_at.isoformat(),
                }
            )
            audio_path = self._safe_reference_audio_path(asset)
            if audio_path is not None and audio_path.is_file():
                data = audio_path.read_bytes()
                actual_digest = sha256_bytes(data)
                if asset.audio_fingerprint and asset.audio_fingerprint != actual_digest:
                    raise NeoHashMismatchError(reference_asset_id)
        else:
            # A missing session asset is recoverable metadata.  Keep a pending
            # reference row so opening the project can report the missing input
            # instead of dropping the binding or fabricating audio bytes.
            data = None

        if asset is None or audio_path is None or data is None:
            return {
                "ready": False,
                "data": None,
                "blob_sha256": None,
                "byte_count": 0,
                "media_type": "audio/wav",
                "text_hash": fallback_text_hash,
                "language": fallback_language,
                "status": "missing",
                "metadata": metadata,
            }

        text_hash = asset.reference_text_fingerprint or fallback_text_hash
        language = asset.reference_language or fallback_language
        status = "present" if text_hash and language.strip() else "invalid"
        metadata["audio_byte_count"] = len(data)
        return {
            "ready": True,
            "data": data,
            "blob_sha256": sha256_bytes(data),
            "byte_count": len(data),
            "media_type": self._reference_media_type(metadata.get("audio_suffix", ".wav")),
            "text_hash": text_hash,
            "language": language,
            "status": status,
            "metadata": metadata,
        }

    def _safe_reference_audio_path(self, asset: SessionReferenceAsset) -> Path | None:
        raw_path = Path(asset.audio_path)
        if not raw_path.is_absolute() or not hasattr(self._asset_store, "assets_root"):
            return None
        allowed_root = (
            Path(self._asset_store.assets_root)
            / "references"
            / self._validate_logical_id(asset.session_id, "session id")
            / self._validate_logical_id(asset.reference_asset_id, "reference asset id")
        ).resolve()
        if raw_path.is_symlink():
            return None
        resolved = raw_path.resolve()
        if allowed_root not in resolved.parents or resolved == allowed_root or resolved.is_symlink():
            return None
        return resolved

    @staticmethod
    def _reference_media_type(suffix: str) -> str:
        return {
            ".wav": "audio/wav",
            ".mp3": "audio/mpeg",
            ".flac": "audio/flac",
        }.get(str(suffix).lower(), "application/octet-stream")

    def _hydrate_payload_assets(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Attach bytes for existing formal assets captured by logical ID.

        The browser capture intentionally carries only stable asset IDs.  When
        the workspace has a materialized formal asset, the backend is the only
        layer allowed to read it and convert it into the `.neo` BLOB closure.
        Missing pending assets remain ``ready=0``; an already-ready asset with
        no readable material is rejected instead of silently dropping audio.
        """
        if self._asset_store is None or not payload.get("assets"):
            return payload
        assets = [dict(asset) for asset in payload.get("assets", [])]
        blobs = [dict(blob) for blob in payload.get("blobs", [])]
        blob_by_digest = {str(blob.get("sha256")): blob for blob in blobs if blob.get("sha256")}
        for asset in assets:
            asset_id = str(asset.get("asset_id", ""))
            if not asset_id:
                continue
            current_digest = asset.get("blob_sha256")
            if current_digest and current_digest in blob_by_digest:
                continue
            path = self._asset_material_path(asset)
            if path is None:
                if int(asset.get("ready", 0)):
                    raise NeoClosureError(f"ready asset {asset_id} is not materialized")
                continue
            data = path.read_bytes()
            digest = sha256_bytes(data)
            asset["blob_sha256"] = digest
            asset["byte_count"] = len(data)
            asset["ready"] = 1
            if not asset.get("media_type") or asset.get("media_type") == "application/octet-stream":
                asset["media_type"] = "application/json" if path.name.endswith(".json") else "audio/wav"
            if not asset.get("codec") or asset.get("codec") == "raw":
                asset["codec"] = "json" if path.name.endswith(".json") else "raw"
            metadata_path = path.parent / "metadata.json"
            if metadata_path.is_file() and not metadata_path.is_symlink():
                try:
                    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    metadata = None
                if isinstance(metadata, dict):
                    if str(asset.get("kind", "")) == "reference_audio":
                        existing_metadata = asset.get("metadata", {})
                        existing_metadata = existing_metadata if isinstance(existing_metadata, dict) else {}
                        merged_metadata = dict(metadata)
                        for key in (
                            "reference_text",
                            "reference_language",
                            "reference_text_fingerprint",
                            "binding_key",
                            "reference_identity",
                        ):
                            if not merged_metadata.get(key) and existing_metadata.get(key):
                                merged_metadata[key] = existing_metadata[key]
                        asset["metadata"] = merged_metadata
                    else:
                        asset["metadata"] = metadata
            if digest not in blob_by_digest:
                blob = {"sha256": digest, "byte_count": len(data), "data": data}
                blobs.append(blob)
                blob_by_digest[digest] = blob
        hydrated = dict(payload)
        hydrated["assets"] = assets
        hydrated["blobs"] = blobs
        references = [
            dict(item)
            for item in payload.get("references", payload.get("reference_entries", []))
            if isinstance(item, dict)
        ]
        references_by_audio = {
            str(item.get("audio_asset_id")): item
            for item in references
            if item.get("audio_asset_id")
        }
        for asset in assets:
            if str(asset.get("kind", "")) != "reference_audio":
                continue
            reference = references_by_audio.get(str(asset.get("asset_id", "")))
            if reference is None:
                continue
            metadata = asset.get("metadata", {})
            if not isinstance(metadata, dict):
                metadata = {}
            text_value = str(metadata.get("reference_text") or "")
            text_hash = str(
                metadata.get("reference_text_fingerprint")
                or reference.get("text_hash")
                or (fingerprint_text(text_value) if text_value else "")
            ) or None
            language = str(metadata.get("reference_language") or reference.get("language") or "")
            reference["text_hash"] = text_hash
            reference["language"] = language
            reference["status"] = "present" if int(asset.get("ready", 0)) and text_hash and language.strip() else (
                "missing" if not int(asset.get("ready", 0)) else "invalid"
            )
        hydrated["references"] = references
        hydrated = self._with_reference_hashes(hydrated, references)
        return hydrated

    def _asset_material_path(self, asset: dict[str, Any]) -> Path | None:
        store = self._asset_store
        if store is None:
            return None
        asset_id = str(asset.get("asset_id", ""))
        kind = str(asset.get("kind", ""))
        role = str(asset.get("role", ""))
        try:
            if kind == "reference_audio":
                return self._reference_payload_material_path(asset)
            if kind == "timeline" or role == "timeline":
                root = store.timeline_manifest_path(asset_id)
            elif kind == "boundary" or role == "boundary":
                root = store.boundary_asset_path(asset_id)
            elif role == "block":
                root = store.block_asset_path(asset_id)
            elif role == "composition":
                root = store.composition_asset_path(asset_id)
            elif kind == "formal" or role == "segment":
                root = store.segment_asset_path(asset_id)
            else:
                return None
        except (AttributeError, ValueError):
            return None
        for filename in ("audio.wav", "manifest.json", "metadata.json"):
            candidate = root / filename
            if candidate.is_file() and not candidate.is_symlink():
                return candidate
        return None

    def _reference_payload_material_path(self, asset: dict[str, Any]) -> Path | None:
        metadata = asset.get("metadata", asset.get("metadata_json", {}))
        if not isinstance(metadata, dict) or self._asset_store is None:
            return None
        raw_path = metadata.get("audio_path")
        session_id = metadata.get("session_id")
        reference_asset_id = metadata.get("reference_asset_id")
        if not session_id or not reference_asset_id or not hasattr(self._asset_store, "assets_root"):
            return None
        try:
            allowed_root = (
                Path(self._asset_store.assets_root)
                / "references"
                / self._validate_logical_id(str(session_id), "session id")
                / self._validate_logical_id(str(reference_asset_id), "reference asset id")
            ).resolve()
        except ValueError:
            return None
        if isinstance(raw_path, str) and raw_path:
            candidate = Path(raw_path)
            if candidate.is_absolute() and not candidate.is_symlink():
                resolved = candidate.resolve()
                if allowed_root in resolved.parents and resolved.is_file():
                    return resolved
        if not allowed_root.is_dir() or allowed_root.is_symlink():
            return None
        for candidate in sorted(allowed_root.glob("audio.*")):
            if candidate.is_file() and not candidate.is_symlink():
                return candidate
        return None

    @contextmanager
    def _workspace_write_lock(self) -> Iterator[None]:
        """Take a bounded, cross-process writer lock for this workspace.

        The in-process ``RLock`` protects one service instance only.  The
        sibling lock file extends the same invariant to another backend
        process without serializing readers or relying on SQLite's longer
        busy timeout.  The file is intentionally retained after release so a
        crash cannot leave a stale path that looks like an active lock; the OS
        releases the byte-range lock with the descriptor.
        """
        lock_path = self.workspace_path / ".project-write.lock"
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with lock_path.open("a+b") as handle:
            handle.seek(0, os.SEEK_END)
            if handle.tell() == 0:
                handle.write(b"\0")
                handle.flush()
            handle.seek(0)
            try:
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except (OSError, IOError) as exc:
                raise NeoWriteBusyError("workspace writer lock is busy") from exc
            try:
                yield
            finally:
                try:
                    handle.seek(0)
                    if os.name == "nt":
                        import msvcrt

                        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                    else:
                        import fcntl

                        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
                except (OSError, IOError):
                    # The OS closes the descriptor immediately afterwards and
                    # releases the lock even if explicit unlock is unavailable.
                    pass

    def _save_impl(
        self,
        payload: dict[str, Any],
        token: CaptureToken | None = None,
        *,
        target: str | Path | None = None,
        force_partial: bool = False,
    ) -> int:
        with self._workspace_write_lock():
            return self._save_impl_locked(
                payload,
                token,
                target=target,
                force_partial=force_partial,
            )

    def _save_impl_locked(
        self,
        payload: dict[str, Any],
        token: CaptureToken | None = None,
        *,
        target: str | Path | None = None,
        force_partial: bool = False,
    ) -> int:
        with self._lock:
            if self.workspace_id is None:
                raise RuntimeError("workspace not initialized")
            payload = dict(payload)
            project_payload = dict(payload.get("project", {}))
            self._validate_logical_id(str(project_payload.get("project_id", "")), "project id")
            project_payload["workspace_id"] = self.workspace_id
            payload["project"] = project_payload
            target_path = (
                Path(target).resolve()
                if target
                else self.workspace_path
                / f"{payload['project'].get('project_id', self.workspace_id)}.neo"
            )
            if target_path.exists() and target_path.is_symlink():
                raise ValueError("project target must not be a symlink")
            if target_path.suffix != ".neo":
                target_path = target_path.with_suffix(".neo")
            target_path.parent.mkdir(parents=True, exist_ok=True)
            partial = target_path.with_name(target_path.name + ".partial")
            if partial.exists():
                raise NeoTargetBusyError(f"partial save already exists: {partial.name}")
            base_revision = 0
            if target_path.exists() and not force_partial:
                existing = ProjectStore(target_path).load()["project"]
                base_revision = int(existing["save_revision"])
                if token is not None and base_revision != token.expected_save_revision:
                    raise NeoWriteBusyError(
                        f"expected revision {token.expected_save_revision}, got {base_revision}"
                    )
            elif not force_partial and token is not None and token.expected_save_revision != 0:
                raise NeoWriteBusyError(
                    "expected existing target revision but target does not exist"
                )
            if target_path.exists() and not force_partial:
                # Ordinary saves stay on the existing SQLite file. ProjectStore
                # performs one BEGIN IMMEDIATE transaction and only upserts or
                # removes rows in the captured closure; a rollback preserves the
                # previous file without a replacement window.
                store = ProjectStore(target_path)
                rev = store.save(payload, expected_save_revision=base_revision)
                with store.connect() as conn:
                    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                    conn.execute("PRAGMA journal_mode=DELETE")
                for suffix in ("-wal", "-shm"):
                    sidecar = Path(str(target_path) + suffix)
                    if sidecar.exists():
                        if sidecar.stat().st_size:
                            raise NeoTargetBusyError(f"sqlite sidecar not closed: {sidecar.name}")
                        sidecar.unlink()
            else:
                # First save, save-as, migration and explicit compaction use a
                # sibling partial and replace only after a complete validation.
                store = ProjectStore(partial)
                try:
                    rev = store.save(payload, base_save_revision=base_revision)
                    with store.connect() as conn:
                        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                        conn.execute("PRAGMA journal_mode=DELETE")
                    for suffix in ("-wal", "-shm"):
                        sidecar = Path(str(partial) + suffix)
                        if sidecar.exists():
                            if sidecar.stat().st_size:
                                raise NeoTargetBusyError(f"sqlite sidecar not closed: {sidecar.name}")
                            sidecar.unlink()
                    last_error: PermissionError | None = None
                    for delay in (0.05, 0.1, 0.2):
                        try:
                            os.replace(partial, target_path)
                            last_error = None
                            break
                        except PermissionError as exc:
                            last_error = exc
                            import time
                            time.sleep(delay)
                    if last_error is not None:
                        raise NeoTargetBusyError(str(last_error)) from last_error
                except Exception:
                    # retain partial for diagnostics; never remove a previously valid target
                    raise
            # A save-as writes an independent capture to ``target_path`` while
            # the source workspace remains the active project.  Its revision
            # and dirty/open metadata therefore belong to the source capture,
            # not to the newly-created target file.  Read the source metadata
            # after the target replace (so target failures leave it untouched)
            # and return that active revision to callers.
            save_as = target is not None and force_partial
            meta_path = self.workspace_path / "workspace.json"
            meta = (
                json.loads(meta_path.read_text(encoding="utf-8"))
                if meta_path.exists()
                else {}
            )
            stale = token is not None and self.is_token_stale(token, payload)
            self.last_save_stale = bool(stale)
            status = str(payload.get("project", {}).get("model_resolution_status", "exact"))
            self.current_capability = self.capability_for_status(status)
            if save_as:
                return int(meta.get("last_save_revision", 0))
            meta.update(
                {
                    "last_save_revision": rev,
                    "dirty": bool(stale),
                    "last_opened_at": _now(),
                }
            )
            meta_path.write_text(json.dumps(meta, sort_keys=True), encoding="utf-8")
            return rev

    def collect_unreferenced_formal_assets(
        self,
        referenced_asset_paths: set[str],
        *,
        asset_store: object | None = None,
    ) -> object:
        """Run formal-asset GC while honoring workspace pins.

        ``EditAssetStore`` uses category-relative paths while capture tokens
        use logical asset IDs.  Expand pinned IDs to every formal category so
        the existing store remains the single deletion implementation.
        """
        store = asset_store or self._asset_store
        if store is None or not hasattr(store, "collect_unreferenced_formal_assets"):
            raise RuntimeError("asset store is not configured")
        protected = set(referenced_asset_paths)
        with self.gc_mutex():
            for asset_id in self.pinned_asset_ids():
                protected.update(
                    f"{category}/{asset_id}"
                    for category in ("segments", "boundaries", "blocks", "compositions", "timelines")
                )
            return store.collect_unreferenced_formal_assets(protected)

    def open_project(self, path: str | Path) -> dict[str, Any]:
        raw_source = Path(path)
        if raw_source.is_symlink():
            raise ValueError("project path must not be a symlink")
        source = raw_source.resolve()
        if source.suffix != ".neo" or not source.is_file():
            raise ValueError("project path must be a .neo file")
        data = self._apply_model_resolution(ProjectStore(source).load())
        project = data["project"]
        root = self.create_workspace(project_id=project["project_id"])
        project["workspace_id"] = self.workspace_id
        # Importing a capture must preserve its save_revision; using the
        # normal save path would silently advance it and make workspace
        # metadata disagree with the .neo file.
        ProjectStore(root / "session.db").restore(data)
        self._materialize_assets(data, root)
        self._install_edit_session_state(data)
        self.current_capability = self.capability_for_status(
            str(data.get("project", {}).get("model_resolution_status", "exact"))
        )
        workspace_meta = json.loads((root / "workspace.json").read_text(encoding="utf-8"))
        workspace_meta["last_save_revision"] = int(data["project"].get("save_revision", 0))
        (root / "workspace.json").write_text(json.dumps(workspace_meta, sort_keys=True), encoding="utf-8")
        self.mark_dirty(False)
        return data

    def _materialize_assets(self, data: dict[str, Any], workspace_root: Path) -> None:
        blobs = {
            str(blob["sha256"]): bytes(blob["data"])
            for blob in data.get("blobs", [])
            if blob.get("sha256")
        }
        for asset in data.get("assets", []):
            if not int(asset.get("ready", 0)) or not asset.get("blob_sha256"):
                continue
            data_bytes = blobs.get(str(asset["blob_sha256"]))
            if data_bytes is None:
                continue
            asset_id = self._validate_logical_id(str(asset["asset_id"]), "asset id")
            kind = str(asset.get("kind", ""))
            role = str(asset.get("role", ""))
            metadata = asset.get("metadata_json", asset.get("metadata", {}))
            if kind == "reference_audio":
                self._materialize_reference_asset(
                    data_bytes=data_bytes,
                    asset=asset,
                    metadata=metadata if isinstance(metadata, dict) else {},
                    workspace_root=workspace_root,
                )
                continue
            category = {
                "boundary": "boundaries",
                "timeline": "timelines",
            }.get(kind, {
                "boundary": "boundaries",
                "block": "blocks",
                "composition": "compositions",
                "timeline": "timelines",
            }.get(role, "segments"))
            filename = "manifest.json" if category == "timelines" else "audio.wav"
            target_dir = workspace_root / "assets" / "formal" / category / asset_id
            target_dir.mkdir(parents=True, exist_ok=True)
            (target_dir / filename).write_bytes(data_bytes)
            if isinstance(metadata, dict) and metadata:
                (target_dir / "metadata.json").write_text(
                    json.dumps(metadata, ensure_ascii=False, sort_keys=True),
                    encoding="utf-8",
                )
            # The current EditAssetStore is the active runtime asset adapter;
            # mirror the same logical asset there when it is configured.
            store = self._asset_store
            if store is None:
                continue
            try:
                path_builder = {
                    "boundaries": store.boundary_asset_path,
                    "blocks": store.block_asset_path,
                    "compositions": store.composition_asset_path,
                    "timelines": store.timeline_manifest_path,
                    "segments": store.segment_asset_path,
                }[category]
                active_dir = path_builder(asset_id)
                active_dir.mkdir(parents=True, exist_ok=True)
                (active_dir / filename).write_bytes(data_bytes)
                if isinstance(metadata, dict) and metadata:
                    (active_dir / "metadata.json").write_text(
                        json.dumps(metadata, ensure_ascii=False, sort_keys=True),
                        encoding="utf-8",
                    )
            except (AttributeError, ValueError):
                continue

    def _materialize_reference_asset(
        self,
        *,
        data_bytes: bytes,
        asset: dict[str, Any],
        metadata: dict[str, Any],
        workspace_root: Path,
    ) -> None:
        reference_asset_id = self._validate_logical_id(
            str(metadata.get("reference_asset_id") or str(asset["asset_id"]).removeprefix("reference-audio-")),
            "reference asset id",
        )
        session_id = self._validate_logical_id(
            str(metadata.get("session_id") or "project"),
            "session id",
        )
        suffix = str(metadata.get("audio_suffix") or ".wav").lower()
        if suffix not in {".wav", ".mp3", ".flac"}:
            suffix = ".wav"
        digest = sha256_bytes(data_bytes)
        created_at = str(metadata.get("created_at") or _now())

        def write_tree(root: Path) -> None:
            target_dir = root / "assets" / "references" / session_id / reference_asset_id
            target_dir.mkdir(parents=True, exist_ok=True)
            audio_path = target_dir / f"audio{suffix}"
            audio_path.write_bytes(data_bytes)
            reference_metadata = {
                "reference_asset_id": reference_asset_id,
                "session_id": session_id,
                "binding_key": metadata.get("binding_key"),
                "audio_path": str(audio_path.resolve()),
                "audio_fingerprint": digest,
                "reference_text": str(metadata.get("reference_text") or ""),
                "reference_text_fingerprint": str(metadata.get("reference_text_fingerprint") or ""),
                "reference_language": str(metadata.get("reference_language") or ""),
                "created_at": created_at,
            }
            (target_dir / "metadata.json").write_text(
                json.dumps(reference_metadata, ensure_ascii=False, sort_keys=True),
                encoding="utf-8",
            )

        write_tree(workspace_root)
        store = self._asset_store
        if store is not None and hasattr(store, "assets_root"):
            write_tree(Path(store.assets_root).parent if Path(store.assets_root).name == "assets" else Path(store.assets_root))

    def _install_edit_session_state(self, data: dict[str, Any]) -> None:
        repository = self._edit_session_repository
        if repository is None:
            return
        snapshots = data.get("snapshots", [])
        converted: list[DocumentSnapshot] = []
        for raw in snapshots:
            converted.append(
                self._to_document_snapshot(
                    self._rewrite_reference_overrides(
                        raw,
                        data,
                        document_id=str(data["project"]["project_id"]),
                    ),
                    data["project"]["project_id"],
                )
            )
        if not converted:
            return
        repository.clear()
        for snapshot in converted:
            repository.save_snapshot(snapshot)
        project = data["project"]
        head_id = project.get("head_snapshot_id") or next(
            (item.snapshot_id for item in converted if item.snapshot_kind == "head"),
            converted[-1].snapshot_id,
        )
        baseline_id = project.get("baseline_snapshot_id")
        # A project capture predates the live edit-session runtime, so it does
        # not contain the transient initialize request.  Rebuild the request
        # from the restored head snapshot; edit/render endpoints require this
        # context and otherwise report a misleading "active session not found".
        head_snapshot = next((item for item in converted if item.snapshot_id == head_id), converted[-1])
        binding_id = head_snapshot.default_voice_binding_id
        binding = next(
            (item for item in head_snapshot.voice_bindings if item.voice_binding_id == binding_id),
            head_snapshot.voice_bindings[0] if head_snapshot.voice_bindings else None,
        )
        raw_text = "\n".join(segment.display_text for segment in head_snapshot.segments)
        initialize_request = InitializeEditSessionRequest(
            raw_text=raw_text,
            text_language="auto",
            voice_id=binding.voice_id if binding is not None else "",
            model_id=(binding.model_id or binding.model_key) if binding is not None else "gpt-sovits-v2",
            model_revision=binding.model_revision if binding is not None else "",
            preset_id=(binding.preset_id or binding.voice_id) if binding is not None else None,
            preset_revision=binding.preset_revision if binding is not None else "",
        )
        repository.upsert_active_session(
            ActiveDocumentState(
                document_id=str(project["project_id"]),
                session_status="ready",
                baseline_snapshot_id=baseline_id,
                head_snapshot_id=head_id,
                initialize_request=initialize_request,
            )
        )

    def _rewrite_reference_overrides(
        self,
        raw: dict[str, Any],
        data: dict[str, Any],
        *,
        document_id: str,
    ) -> dict[str, Any]:
        """Point restored profile overrides at the relocated session asset."""
        config = raw.get("config_json", raw.get("config", {}))
        if not isinstance(config, dict):
            return raw
        references_by_binding: dict[str, tuple[dict[str, Any], dict[str, Any] | None]] = {}
        assets_by_id = {
            str(item.get("asset_id")): item
            for item in data.get("assets", [])
            if isinstance(item, dict) and item.get("asset_id")
        }
        for reference in data.get("references", data.get("reference_entries", [])):
            if not isinstance(reference, dict):
                continue
            metadata = reference.get("metadata_json", reference.get("metadata", {}))
            metadata = metadata if isinstance(metadata, dict) else {}
            binding_keys = metadata.get("binding_keys", [])
            if not isinstance(binding_keys, list):
                continue
            asset = assets_by_id.get(str(reference.get("audio_asset_id")))
            for binding_key in binding_keys:
                references_by_binding[str(binding_key)] = (reference, asset)
        if not references_by_binding:
            return raw
        profiles = config.get("render_profiles", [])
        if not isinstance(profiles, list):
            return raw
        next_config = dict(config)
        next_profiles: list[dict[str, Any]] = []
        target_profile_index = next(
            (
                index
                for index, profile in enumerate(profiles)
                if isinstance(profile, dict) and profile.get("scope") == "session"
            ),
            0,
        )
        for profile_index, profile in enumerate(profiles):
            if not isinstance(profile, dict):
                next_profiles.append(profile)
                continue
            overrides = profile.get("reference_overrides_by_binding", {})
            if not isinstance(overrides, dict):
                next_profiles.append(profile)
                continue
            next_overrides = {str(key): dict(value) for key, value in overrides.items() if isinstance(value, dict)}
            if profile_index == target_profile_index:
                for binding_key in references_by_binding:
                    next_overrides.setdefault(binding_key, {})
            for binding_key, override in next_overrides.items():
                match = references_by_binding.get(binding_key)
                if match is None:
                    continue
                reference, asset = match
                reference_metadata = reference.get("metadata_json", reference.get("metadata", {}))
                reference_metadata = reference_metadata if isinstance(reference_metadata, dict) else {}
                reference_asset_id = reference_metadata.get("reference_asset_id")
                if not reference_asset_id:
                    continue
                reference_asset_id = self._validate_logical_id(str(reference_asset_id), "reference asset id")
                audio_path = self._materialized_reference_audio_path(document_id, reference_asset_id)
                asset_metadata = asset.get("metadata_json", asset.get("metadata", {})) if isinstance(asset, dict) else {}
                asset_metadata = asset_metadata if isinstance(asset_metadata, dict) else {}
                override.update(
                    {
                        "session_reference_asset_id": reference_asset_id,
                        "reference_identity": f"{document_id}:{reference_asset_id}",
                        "reference_audio_fingerprint": asset.get("blob_sha256") if isinstance(asset, dict) else override.get("reference_audio_fingerprint"),
                        "reference_text": asset_metadata.get("reference_text", override.get("reference_text")),
                        "reference_text_fingerprint": reference.get("text_hash", asset_metadata.get("reference_text_fingerprint")),
                        "reference_language": reference.get("language", asset_metadata.get("reference_language", override.get("reference_language"))),
                    }
                )
                if audio_path is not None:
                    override["reference_audio_path"] = str(audio_path)
            next_profiles.append({**profile, "reference_overrides_by_binding": next_overrides})
        next_config["render_profiles"] = next_profiles
        return {**raw, "config": next_config, "config_json": next_config}

    def _materialized_reference_audio_path(self, session_id: str, reference_asset_id: str) -> Path | None:
        store = self._asset_store
        if store is None or not hasattr(store, "assets_root"):
            return None
        try:
            root = (
                Path(store.assets_root)
                / "references"
                / self._validate_logical_id(session_id, "session id")
                / self._validate_logical_id(reference_asset_id, "reference asset id")
            )
        except ValueError:
            return None
        if not root.is_dir() or root.is_symlink():
            return None
        for candidate in sorted(root.glob("audio.*")):
            if candidate.is_file() and not candidate.is_symlink():
                return candidate.resolve()
        return None

    @staticmethod
    def _to_document_snapshot(raw: dict[str, Any], document_id: str) -> DocumentSnapshot:
        config = raw.get("config_json", raw.get("config", {}))
        config = config if isinstance(config, dict) else {}
        segments: list[EditableSegment] = []
        for position, item in enumerate(raw.get("segments", [])):
            text = item.get("text_json", item.get("text", {}))
            binding = item.get("binding_json", item.get("binding", {}))
            parameters = item.get("parameter_json", item.get("parameters", {}))
            status = item.get("status_json", item.get("status", {}))
            text = text if isinstance(text, dict) else {}
            binding = binding if isinstance(binding, dict) else {}
            parameters = parameters if isinstance(parameters, dict) else {}
            status = status if isinstance(status, dict) else {}
            segments.append(
                EditableSegment(
                    segment_id=str(item["segment_id"]),
                    document_id=document_id,
                    order_key=int(item.get("position", position)),
                    stem=str(text.get("stem", text.get("value", ""))),
                    text_language=str(text.get("text_language", "auto")),
                    terminal_raw=str(text.get("terminal_raw", "")),
                    terminal_closer_suffix=str(text.get("terminal_closer_suffix", "")),
                    terminal_source=text.get("terminal_source", "synthetic"),
                    render_version=int(status.get("render_version", 0)),
                    render_asset_id=item.get("formal_asset_id", item.get("render_asset_id")),
                    group_id=item.get("group_id"),
                    render_profile_id=binding.get("render_profile_id"),
                    voice_binding_id=binding.get("voice_binding_id"),
                    render_status=status.get("render_status", "ready"),
                    segment_revision=int(status.get("segment_revision", 1)),
                    inference_override=parameters,
                    risk_flags=list(status.get("risk_flags", [])),
                )
            )
        segment_ids = {item.segment_id for item in segments}
        edges: list[EditableEdge] = []
        for position, item in enumerate(raw.get("edges", [])):
            policy = item.get("policy_json", item.get("policy", {}))
            status = item.get("status_json", item.get("status", {}))
            policy = policy if isinstance(policy, dict) else {}
            status = status if isinstance(status, dict) else {}
            left_id = str(item.get("from_segment_id", item.get("left_segment_id", "")))
            right_id = str(item.get("to_segment_id", item.get("right_segment_id", "")))
            if left_id not in segment_ids or right_id not in segment_ids:
                continue
            edges.append(
                EditableEdge(
                    edge_id=str(item["edge_id"]),
                    document_id=document_id,
                    left_segment_id=left_id,
                    right_segment_id=right_id,
                    pause_duration_seconds=float(policy.get("pause_duration_seconds", 0.3)),
                    boundary_strategy=str(policy.get("boundary_strategy", "latent_overlap_then_equal_power_crossfade")),
                    effective_boundary_strategy=policy.get("effective_boundary_strategy"),
                    edge_status=status.get("edge_status", "ready"),
                    edge_version=int(status.get("edge_version", 1)),
                )
            )
        groups = [SegmentGroup.model_validate(item) for item in config.get("groups", []) if isinstance(item, dict)]
        profiles = [RenderProfile.model_validate(item) for item in config.get("render_profiles", []) if isinstance(item, dict)]
        bindings = [VoiceBinding.model_validate(item) for item in config.get("voice_bindings", []) if isinstance(item, dict)]
        return DocumentSnapshot(
            snapshot_id=str(raw["snapshot_id"]),
            document_id=document_id,
            snapshot_kind="head" if raw.get("kind") == "head" else "baseline" if raw.get("kind") == "baseline" else "staging",
            document_version=int(raw.get("revision", raw.get("document_version", 0))),
            segment_ids=[item.segment_id for item in segments],
            edge_ids=[item.edge_id for item in edges],
            groups=groups,
            render_profiles=profiles,
            voice_bindings=bindings,
            default_render_profile_id=config.get("default_render_profile_id"),
            default_voice_binding_id=config.get("default_voice_binding_id"),
            composition_manifest_id=config.get("composition_manifest_id"),
            timeline_manifest_id=config.get("timeline_manifest_id"),
            segments=segments,
            edges=edges,
        )

    def _apply_model_resolution(self, data: dict[str, Any]) -> dict[str, Any]:
        project = data.get("project")
        if not isinstance(project, dict):
            return data
        status = str(project.get("model_resolution_status", "exact"))
        identity = project.get("model_identity_json", project.get("model_identity", {}))
        identity = identity if isinstance(identity, dict) else {}
        model_id = str(identity.get("model_id", "")).strip()
        catalog = self._model_catalog
        diagnostics = project.get("diagnostics_json", project.get("diagnostics", {}))
        diagnostics = dict(diagnostics) if isinstance(diagnostics, dict) else {}
        # ``gpt-sovits-v2`` is the legacy runtime adapter selected by the edit
        # session router.  It is intentionally not a ModelCatalog entry, so
        # resolving it through the catalog would incorrectly downgrade an
        # otherwise usable imported project to read-only.
        if model_id == "gpt-sovits-v2":
            project["model_resolution_status"] = "exact"
            project["diagnostics_json"] = {
                **diagnostics,
                "code": "MODEL_LEGACY_RUNTIME",
                "model_id": model_id,
            }
            project["capability"] = self.capability_for_status("exact")
            self.current_capability = project["capability"]
            self.last_model_diagnostics = project["diagnostics_json"]
            return data
        if not model_id or catalog is None:
            project["capability"] = self.capability_for_status(status)
            self.current_capability = project["capability"]
            self.last_model_diagnostics = diagnostics
            return data

        try:
            model, preset = catalog.resolve(
                model_id=model_id,
                model_revision=str(identity.get("model_revision", "")),
                preset_id=identity.get("preset_id"),
                preset_revision=str(identity.get("preset_revision", "")),
            )
        except LookupError as exc:
            status = "read_only_degraded"
            diagnostics.update({"code": "MODEL_MISSING", "message": str(exc), "model_id": model_id})
        except ValueError as exc:
            status = "read_only_degraded"
            code = "MODEL_INCOMPATIBLE"
            try:
                model_record = catalog.get_model(model_id)
                if getattr(model_record, "version_status", "") in {"missing", "stale"}:
                    code = "MODEL_MISSING"
                elif getattr(model_record, "version_status", "") not in {"incompatible", "failed"}:
                    code = "MODEL_REVISION_MISMATCH"
            except LookupError:
                code = "MODEL_MISSING"
            diagnostics.update({"code": code, "message": str(exc), "model_id": model_id})
        else:
            model_paths = [
                getattr(model, "gpt_path_hint", ""),
                getattr(model, "sovits_path_hint", ""),
            ]
            missing_paths = [path for path in model_paths if path and not Path(path).is_file()]
            expected_hashes = {
                "gpt_content_sha256": getattr(model, "gpt_content_sha256", ""),
                "sovits_content_sha256": getattr(model, "sovits_content_sha256", ""),
            }
            stored_hashes = {
                key: str(identity.get(key, ""))
                for key in expected_hashes
                if identity.get(key)
            }
            actual_hashes: dict[str, str] = {}
            unreadable_paths: list[str] = []
            for key, path in zip(("gpt_content_sha256", "sovits_content_sha256"), model_paths):
                if not path or not Path(path).is_file():
                    continue
                try:
                    actual_hashes[key] = self._file_sha256(path)
                except OSError:
                    unreadable_paths.append(path)
            if missing_paths or unreadable_paths:
                status = "read_only_degraded"
                diagnostics.update({"code": "MODEL_MISSING", "message": "catalog model path is missing", "model_id": model_id})
            elif (
                stored_hashes and any(stored_hashes[key] != value for key, value in expected_hashes.items() if key in stored_hashes)
            ) or (
                actual_hashes and any(actual_hashes[key] != value for key, value in expected_hashes.items() if value and key in actual_hashes)
            ):
                status = "read_only_degraded"
                diagnostics.update({"code": "MODEL_INCOMPATIBLE", "message": "catalog content hash differs", "model_id": model_id})
            else:
                status = "exact"
                diagnostics.update({
                    "code": "MODEL_RESOLVED",
                    "model_id": getattr(model, "model_id", model_id),
                    "model_revision": getattr(model, "model_revision", identity.get("model_revision", "")),
                    "preset_id": getattr(preset, "preset_id", identity.get("preset_id")),
                    "preset_revision": getattr(preset, "preset_revision", identity.get("preset_revision", "")),
                    "capabilities": list(getattr(model, "capabilities", ())),
                })
        project["model_resolution_status"] = status
        project["diagnostics_json"] = diagnostics
        project["capability"] = self.capability_for_status(status)
        self.current_capability = project["capability"]
        self.last_model_diagnostics = diagnostics
        return data

    @staticmethod
    def _file_sha256(raw_path: str) -> str:
        digest = hashlib.sha256()
        with Path(raw_path).open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def import_legacy_session(
        self, session_db: str | Path, *, project_id: str | None = None
    ) -> Path:
        source = Path(session_db).resolve()
        if source.name != "session.db" or not source.is_file():
            raise ValueError("legacy session.db required")
        payload = self._read_legacy_payload(source, project_id=project_id)
        root = self.create_workspace(project_id=payload["project"]["project_id"])
        payload["project"]["workspace_id"] = self.workspace_id
        ProjectStore(root / "session.db").restore(payload)
        self._materialize_assets(payload, root)
        self._install_edit_session_state(payload)
        self.current_capability = self.capability_for_status(
            str(payload.get("project", {}).get("model_resolution_status", "exact"))
        )
        (root / "legacy.session.db").write_bytes(source.read_bytes())
        workspace_meta = json.loads((root / "workspace.json").read_text(encoding="utf-8"))
        workspace_meta["last_save_revision"] = int(payload["project"].get("save_revision", 0))
        (root / "workspace.json").write_text(json.dumps(workspace_meta, sort_keys=True), encoding="utf-8")
        self.mark_dirty(False)
        return root

    @staticmethod
    def _read_legacy_payload(source: Path, *, project_id: str | None) -> dict[str, Any]:
        """Convert the stable legacy repository tables into a v1 payload."""
        with sqlite3.connect(source) as conn:
            conn.row_factory = sqlite3.Row
            tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            required = {"snapshots", "segments", "edges"}
            if not required <= tables:
                raise ValueError("legacy session.db missing required snapshot tables")
            active = None
            if "active_session" in tables:
                row = conn.execute("SELECT payload FROM active_session WHERE singleton_key='active'").fetchone()
                active = json.loads(row[0]) if row else None
            snapshot_rows = conn.execute("SELECT snapshot_id,document_id,document_version,created_at,payload FROM snapshots").fetchall()
            if not snapshot_rows:
                raise ValueError("legacy session.db has no snapshots")
            document_id = project_id or str((active or {}).get("document_id") or snapshot_rows[0]["document_id"])
            snapshots: list[dict[str, Any]] = []
            for row in snapshot_rows:
                raw = json.loads(row["payload"])
                kind = str(raw.get("snapshot_kind", "head"))
                kind = {"staging": "working"}.get(kind, kind)
                if kind not in {"head", "baseline", "working"}:
                    kind = "working"
                segments = [json.loads(item[0]) for item in conn.execute("SELECT payload FROM segments WHERE snapshot_id=? ORDER BY order_key", (row["snapshot_id"],))]
                edges = [json.loads(item[0]) for item in conn.execute("SELECT payload FROM edges WHERE snapshot_id=? ORDER BY edge_order_key", (row["snapshot_id"],))]
                raw.update({"snapshot_id": row["snapshot_id"], "kind": kind, "revision": row["document_version"], "created_at": row["created_at"], "segments": segments, "edges": edges, "groups": raw.get("groups", [])})
                snapshots.append(raw)
            head = next((item["snapshot_id"] for item in snapshots if item["kind"] == "head"), snapshots[-1]["snapshot_id"])
            baseline = next((item["snapshot_id"] for item in snapshots if item["kind"] == "baseline"), None)
            assets, blobs, asset_refs = ProjectSessionService._read_legacy_assets(source.parent / "assets", snapshots)
            for asset_ref in asset_refs:
                asset_ref["owner_id"] = document_id
            timeline_id = next((item.get("timeline_manifest_id") for item in reversed(snapshots) if item.get("timeline_manifest_id")), None)
            return {"project": {"project_id": document_id, "head_snapshot_id": head, "baseline_snapshot_id": baseline, "timeline_manifest_id": timeline_id, "draft_payload": {}, "model_identity": {}, "workspace_id": None}, "snapshots": snapshots, "assets": assets, "references": [], "asset_refs": asset_refs, "blobs": blobs}

    @staticmethod
    def _read_legacy_assets(assets_root: Path, snapshots: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
        """Read only the asset layout owned by EditAssetStore; missing files stay pending."""
        specs: dict[str, tuple[str, str, str]] = {}
        for snapshot in snapshots:
            for segment in snapshot.get("segments", []):
                asset_id = segment.get("render_asset_id") or segment.get("formal_asset_id")
                if asset_id:
                    specs[str(asset_id)] = ("formal", "segments", str(asset_id))
            for edge in snapshot.get("edges", []):
                asset_id = edge.get("asset_id") or edge.get("boundary_asset_id")
                if asset_id:
                    specs[str(asset_id)] = ("boundary", "boundaries", str(asset_id))
            for asset_id in snapshot.get("block_ids", []):
                # ``block`` is the legacy domain role, while the v1 container
                # kind is intentionally limited to the stable ``formal``
                # category.  Preserve the role so the importer does not
                # invent a new storage kind that ProjectStore cannot validate.
                specs[str(asset_id)] = ("formal", "blocks", str(asset_id))
            for key, kind, directory in (("composition_manifest_id", "formal", "compositions"), ("timeline_manifest_id", "timeline", "timelines")):
                if snapshot.get(key):
                    specs[str(snapshot[key])] = (kind, directory, str(snapshot[key]))
        assets: list[dict[str, Any]] = []
        blobs: list[dict[str, Any]] = []
        refs: list[dict[str, Any]] = []
        for asset_id, (kind, directory, leaf) in specs.items():
            root = assets_root / "formal" / directory / leaf
            audio_path = root / "audio.wav"
            json_path = root / ("manifest.json" if kind == "timeline" else "metadata.json")
            path = audio_path if audio_path.is_file() else json_path if json_path.is_file() else None
            data = path.read_bytes() if path else b""
            digest = sha256_bytes(data) if path else None
            if path:
                blobs.append({"sha256": digest, "data": data})
            metadata: dict[str, Any] = {"legacy_path": str(path) if path else None}
            metadata_path = root / "metadata.json"
            if metadata_path.is_file() and not metadata_path.is_symlink():
                try:
                    decoded_metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    decoded_metadata = None
                if isinstance(decoded_metadata, dict):
                    metadata.update(decoded_metadata)
            role = {
                "blocks": "block",
                "compositions": "composition",
            }.get(directory, kind)
            assets.append({"asset_id": asset_id, "kind": kind, "role": role, "blob_sha256": digest, "media_type": "audio/wav" if path is audio_path else "application/json", "codec": "raw", "byte_count": len(data), "ready": int(path is not None), "metadata": metadata})
            refs.append({"owner_type": "project", "owner_id": "legacy", "asset_id": asset_id, "purpose": role})
        return assets, blobs, refs

    @contextmanager
    def gc_mutex(self) -> Iterator[None]:
        with self._gc_lock:
            yield
