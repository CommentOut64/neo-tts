import asyncio
from datetime import datetime, timezone
from pathlib import Path

from backend.app.repositories.edit_session_repository import EditSessionRepository
from backend.app.schemas.edit_session import (
    ActiveDocumentState,
    DocumentSnapshot,
    EditableSegment,
    RenderJobRecord,
)
from backend.app.services.edit_asset_store import EditAssetStore
from backend.app.services.edit_session_maintenance_service import EditSessionMaintenanceService
from backend.app.services.edit_session_runtime import EditSessionRuntime


def _build_repository(tmp_path: Path) -> EditSessionRepository:
    repository = EditSessionRepository(project_root=tmp_path, db_file=tmp_path / "session.db")
    repository.initialize_schema()
    return repository


def _build_store(tmp_path: Path) -> EditAssetStore:
    return EditAssetStore(
        project_root=tmp_path,
        assets_dir=tmp_path / "assets",
        staging_ttl_seconds=60,
    )


def test_service_recovers_head_snapshot_after_restart(tmp_path: Path):
    repository = _build_repository(tmp_path)
    store = _build_store(tmp_path)
    runtime = EditSessionRuntime()
    snapshot = DocumentSnapshot(
        snapshot_id="head-1",
        document_id="doc-1",
        snapshot_kind="head",
        document_version=2,
        raw_text="你好。",
        normalized_text="你好。",
        segments=[
            EditableSegment(
                segment_id="seg-1",
                document_id="doc-1",
                order_key=1,
                raw_text="你好。",
                normalized_text="你好。",
                text_language="zh",
                render_asset_id="render-1",
            )
        ],
    )
    repository.save_snapshot(snapshot)
    repository.upsert_active_session(
        ActiveDocumentState(
            document_id="doc-1",
            session_status="ready",
            baseline_snapshot_id="head-1",
            head_snapshot_id="head-1",
        )
    )
    maintenance = EditSessionMaintenanceService(repository=repository, asset_store=store, runtime=runtime)

    report = asyncio.run(maintenance.reconcile_on_startup())

    assert report.recovered_document_id == "doc-1"
    assert repository.get_active_session() is not None
    assert repository.get_active_session().head_snapshot_id == "head-1"


def test_reconcile_marks_zombie_jobs_as_failed(tmp_path: Path):
    repository = _build_repository(tmp_path)
    store = _build_store(tmp_path)
    runtime = EditSessionRuntime()
    repository.save_render_job(
        RenderJobRecord(
            job_id="job-zombie",
            document_id="doc-1",
            job_kind="initialize",
            status="rendering",
            progress=0.4,
            message="still running",
            cancel_requested=False,
            updated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
    )
    maintenance = EditSessionMaintenanceService(repository=repository, asset_store=store, runtime=runtime)

    report = asyncio.run(maintenance.reconcile_on_startup())

    updated = repository.get_render_job("job-zombie")
    assert updated is not None
    assert updated.status == "failed"
    assert report.zombie_job_ids == ["job-zombie"]


def test_run_periodic_loop_executes_cleanup_cycle_once_before_cancel(tmp_path: Path):
    repository = _build_repository(tmp_path)
    store = _build_store(tmp_path)
    runtime = EditSessionRuntime()
    maintenance = EditSessionMaintenanceService(
        repository=repository,
        asset_store=store,
        runtime=runtime,
        interval_seconds=0.01,
    )

    async def _exercise() -> int:
        task = asyncio.create_task(maintenance.run_periodic_loop())
        await asyncio.sleep(0.03)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        return maintenance.last_periodic_report.preview_purged_count

    preview_purged_count = asyncio.run(_exercise())
    assert preview_purged_count >= 0
