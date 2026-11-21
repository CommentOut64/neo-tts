from __future__ import annotations

import sqlite3

import pytest

from backend.app.services.project_store import (
    ProjectStore,
    NeoClosureError,
    NeoHashMismatchError,
    NeoUnsupportedVersionError,
    sha256_bytes,
)


def payload(project_id: str = "p1") -> dict:
    blob = b"formal-audio"
    digest = sha256_bytes(blob)
    return {
        "project": {
            "project_id": project_id,
            "workspace_id": "w1",
            "head_snapshot_id": "s1",
            "draft_payload": {"draft_revision": 2},
            "model_identity": {"model_id": "m1", "model_revision": "r1"},
        },
        "blobs": [{"sha256": digest, "data": blob}],
        "assets": [
            {
                "asset_id": "a1",
                "kind": "formal",
                "blob_sha256": digest,
                "byte_count": len(blob),
                "ready": 1,
            }
        ],
        "snapshots": [
            {
                "snapshot_id": "s1",
                "kind": "head",
                "segments": [{"segment_id": "seg1", "text": {"value": "hello"}}],
            }
        ],
        "references": [],
        "asset_refs": [
            {
                "owner_type": "snapshot",
                "owner_id": "s1",
                "asset_id": "a1",
                "purpose": "formal",
            }
        ],
    }


def test_project_store_roundtrip_and_revision(tmp_path):
    store = ProjectStore(tmp_path / "sample.neo")
    revision = store.save(payload())
    assert revision == 1
    loaded = store.load()
    assert loaded["project"]["save_revision"] == 1
    assert loaded["project"]["head_snapshot_id"] == "s1"
    assert loaded["snapshots"][0]["segments"][0]["segment_id"] == "seg1"
    assert store.get_blob(loaded["blobs"][0]["sha256"]) == b"formal-audio"


def test_incremental_save_reuses_unchanged_blob_not_present_in_capture_delta(tmp_path):
    store = ProjectStore(tmp_path / "sample.neo")
    first = payload()
    assert store.save(first) == 1
    second = payload()
    second["project"]["draft_payload"] = {"draft_revision": 3}
    second["blobs"] = []

    assert store.save(second, expected_save_revision=1) == 2
    assert store.get_blob(first["assets"][0]["blob_sha256"]) == b"formal-audio"


def test_project_store_rejects_hash_mismatch(tmp_path):
    bad = payload()
    bad["blobs"][0]["sha256"] = "0" * 64
    with pytest.raises(NeoHashMismatchError):
        ProjectStore(tmp_path / "sample.neo").save(bad)


def test_project_store_rejects_ready_asset_without_blob(tmp_path):
    bad = payload()
    bad["assets"][0]["blob_sha256"] = "1" * 64
    with pytest.raises(NeoClosureError):
        ProjectStore(tmp_path / "sample.neo").save(bad)


def test_project_store_rejects_unknown_version(tmp_path):
    path = tmp_path / "sample.neo"
    ProjectStore(path).initialize(project_id="p1")
    with sqlite3.connect(path) as conn:
        conn.execute("PRAGMA user_version=99")
    with pytest.raises(NeoUnsupportedVersionError):
        ProjectStore(path)
