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


def test_edit_asset_store_creates_and_purges_preview_assets(tmp_path: Path):
    store = _build_store(tmp_path)
    created_at = datetime(2026, 1, 1, tzinfo=timezone.utc)

    record = store.create_preview_asset(
        job_id="job-preview-1",
        preview_asset_id="preview-1",
        preview_kind="segment",
        payload=b"preview-bytes",
        ttl_seconds=60,
        now=created_at,
    )

    assert record.audio_file_path.exists()
    assert store.get_preview_asset_record("preview-1").preview_kind == "segment"
    assert store.get_preview_asset_record("preview-1").job_id == "job-preview-1"

    removed = store.purge_expired_preview_assets(now=created_at + timedelta(seconds=61))

    assert removed == 1
    assert not store.preview_asset_path("preview-1").exists()


def test_collect_unreferenced_formal_assets_keeps_head_and_baseline(tmp_path: Path):
    store = _build_store(tmp_path)
    keep_segment = store.segment_asset_path("render-keep")
    delete_segment = store.segment_asset_path("render-delete")
    keep_boundary = store.boundary_asset_path("boundary-keep")
    delete_boundary = store.boundary_asset_path("boundary-delete")
    keep_block = store.block_asset_path("block-keep")
    delete_block = store.block_asset_path("block-delete")
    keep_composition = store.composition_asset_path("comp-keep")
    delete_composition = store.composition_asset_path("comp-delete")
    for path in [
        keep_segment,
        delete_segment,
        keep_boundary,
        delete_boundary,
        keep_block,
        delete_block,
        keep_composition,
        delete_composition,
    ]:
        path.mkdir(parents=True, exist_ok=True)
        (path / "audio.wav").write_bytes(b"wav")

    report = store.collect_unreferenced_formal_assets(
        referenced_asset_ids={
            "segments/render-keep",
            "boundaries/boundary-keep",
            "blocks/block-keep",
            "compositions/comp-keep",
        }
    )

    assert report.deleted_asset_paths
    assert keep_segment.exists()
    assert keep_boundary.exists()
    assert keep_block.exists()
    assert keep_composition.exists()
    assert not delete_segment.exists()
    assert not delete_boundary.exists()
    assert not delete_block.exists()
    assert not delete_composition.exists()


def test_edit_asset_store_cleans_up_orphan_preview_assets(tmp_path: Path):
    store = _build_store(tmp_path)
    store.create_preview_asset(
        job_id="job-keep",
        preview_asset_id="preview-keep",
        preview_kind="segment",
        payload=b"keep",
        ttl_seconds=60,
    )
    store.create_preview_asset(
        job_id="job-delete",
        preview_asset_id="preview-delete",
        preview_kind="segment",
        payload=b"delete",
        ttl_seconds=60,
    )

    removed = store.cleanup_orphan_preview_assets({"preview-keep"})

    assert removed == 1
    assert store.preview_asset_path("preview-keep").exists()
    assert not store.preview_asset_path("preview-delete").exists()
