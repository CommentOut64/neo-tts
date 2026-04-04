import asyncio
from pathlib import Path

from backend.app.repositories.edit_session_repository import EditSessionRepository
from backend.app.schemas.edit_session import ExportJobRecord
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
        export_root=tmp_path / "exports",
        staging_ttl_seconds=60,
    )


def test_reconcile_marks_zombie_export_job_failed_and_cleans_staging(tmp_path: Path):
    repository = _build_repository(tmp_path)
    store = _build_store(tmp_path)
    runtime = EditSessionRuntime()
    target_dir, staging_dir = store.prepare_export_staging_dir(
        export_job_id="export-zombie",
        target_dir=tmp_path / "exports" / "segments",
    )
    (staging_dir / "0001.wav").write_bytes(b"audio")

    repository.save_export_job(
        ExportJobRecord(
            export_job_id="export-zombie",
            document_id="doc-1",
            document_version=3,
            timeline_manifest_id="timeline-3",
            export_kind="segments",
            status="exporting",
            target_dir=str(target_dir),
            overwrite_policy="fail",
            progress=0.5,
            message="still exporting",
            staging_dir=str(staging_dir),
        )
    )

    maintenance = EditSessionMaintenanceService(repository=repository, asset_store=store, runtime=runtime)
    report = asyncio.run(maintenance.reconcile_on_startup())

    updated = repository.get_export_job("export-zombie")
    assert updated is not None
    assert updated.status == "failed"
    assert report.zombie_export_job_ids == ["export-zombie"]
    assert not staging_dir.exists()
