from datetime import datetime, timedelta, timezone
import os
from pathlib import Path

from backend.app.services.edit_asset_store import EditAssetStore


def _build_store(tmp_path: Path) -> EditAssetStore:
    return EditAssetStore(
        project_root=tmp_path,
        assets_dir=Path("storage/edit_session/assets"),
        staging_ttl_seconds=60,
    )


def test_edit_asset_store_writes_staging_bytes_and_promotes_tree(tmp_path: Path):
    store = _build_store(tmp_path)

    staging_file = store.write_staging_bytes("job-1", "segments/render-1/audio.wav", b"abc")

    assert staging_file.exists()

    promoted_paths = store.promote_staging_tree("job-1", "formal")

    assert any(path.as_posix().endswith("formal/segments/render-1/audio.wav") for path in promoted_paths)
    assert (tmp_path / "storage" / "edit_session" / "assets" / "formal" / "segments" / "render-1" / "audio.wav").read_bytes() == b"abc"


def test_edit_asset_store_cleans_up_expired_staging(tmp_path: Path):
    store = _build_store(tmp_path)
    expired_file = store.write_staging_bytes("job-old", "segments/render-1/audio.wav", b"old")
    store.write_staging_bytes("job-fresh", "segments/render-2/audio.wav", b"new")
    old_timestamp = (datetime.now(timezone.utc) - timedelta(seconds=3600)).timestamp()
    os.utime(expired_file.parents[2], (old_timestamp, old_timestamp))

    expired_now = datetime.now(timezone.utc)

    removed_count = store.cleanup_expired_staging(now=expired_now)

    assert removed_count == 1
    assert not (tmp_path / "storage" / "edit_session" / "assets" / "staging" / "job-old").exists()
    assert (tmp_path / "storage" / "edit_session" / "assets" / "staging" / "job-fresh").exists()


def test_edit_asset_store_resolves_segment_and_boundary_asset_paths(tmp_path: Path):
    store = _build_store(tmp_path)

    assert store.segment_asset_path("render-1").as_posix().endswith("/formal/segments/render-1")
    assert store.boundary_asset_path("boundary-1").as_posix().endswith("/formal/boundaries/boundary-1")
