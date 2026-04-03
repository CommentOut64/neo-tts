from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import asyncio

from backend.app.repositories.edit_session_repository import EditSessionRepository
from backend.app.services.edit_asset_store import AssetGcReport, EditAssetStore
from backend.app.services.edit_session_runtime import EditSessionRuntime


@dataclass(frozen=True)
class MaintenanceReport:
    recovered_document_id: str | None = None
    zombie_job_ids: list[str] = field(default_factory=list)
    staging_purged_count: int = 0
    preview_purged_count: int = 0
    orphan_preview_removed_count: int = 0
    formal_gc_report: AssetGcReport = field(
        default_factory=lambda: AssetGcReport(deleted_asset_paths=[], kept_asset_paths=[])
    )


class EditSessionMaintenanceService:
    def __init__(
        self,
        *,
        repository: EditSessionRepository,
        asset_store: EditAssetStore,
        runtime: EditSessionRuntime,
        interval_seconds: float = 300.0,
    ) -> None:
        self._repository = repository
        self._asset_store = asset_store
        self._runtime = runtime
        self._interval_seconds = interval_seconds
        self.last_periodic_report = MaintenanceReport()

    async def reconcile_on_startup(self) -> MaintenanceReport:
        recoverable = self._repository.load_recoverable_state()
        recovered_document_id = recoverable.active_session.document_id if recoverable is not None else None
        zombie_job_ids: list[str] = []
        active_session = self._repository.get_active_session()
        for job in self._repository.list_non_terminal_jobs():
            terminal_status = "cancelled" if job.cancel_requested else "failed"
            self._repository.mark_job_terminal(
                job.job_id,
                status=terminal_status,
                message="Recovered on startup after interrupted render job.",
            )
            zombie_job_ids.append(job.job_id)

        if active_session is not None and zombie_job_ids:
            recovered_status = "ready" if recoverable is not None else "failed"
            self._repository.upsert_active_session(
                active_session.model_copy(
                    update={
                        "active_job_id": None,
                        "session_status": recovered_status,
                        "updated_at": datetime.now(timezone.utc),
                    }
                )
            )

        cleanup_report = self._run_cleanup_cycle(cleanup_orphan_previews=True)
        report = MaintenanceReport(
            recovered_document_id=recovered_document_id,
            zombie_job_ids=zombie_job_ids,
            staging_purged_count=cleanup_report.staging_purged_count,
            preview_purged_count=cleanup_report.preview_purged_count,
            orphan_preview_removed_count=cleanup_report.orphan_preview_removed_count,
            formal_gc_report=cleanup_report.formal_gc_report,
        )
        self.last_periodic_report = report
        return report

    async def run_periodic_loop(self) -> None:
        while True:
            self.last_periodic_report = self._run_cleanup_cycle(cleanup_orphan_previews=False)
            await asyncio.sleep(self._interval_seconds)

    def _run_cleanup_cycle(self, *, cleanup_orphan_previews: bool) -> MaintenanceReport:
        referenced_graph = self._repository.collect_referenced_asset_ids()
        staging_purged_count = self._asset_store.cleanup_expired_staging()
        preview_purged_count = self._asset_store.purge_expired_preview_assets()
        orphan_preview_removed_count = (
            self._asset_store.cleanup_orphan_preview_assets(referenced_graph.preview_asset_ids)
            if cleanup_orphan_previews
            else 0
        )
        formal_gc_report = self._asset_store.collect_unreferenced_formal_assets(
            referenced_graph.as_relative_asset_paths()
        )
        return MaintenanceReport(
            recovered_document_id=(
                self._repository.get_active_session().document_id
                if self._repository.get_active_session() is not None
                else None
            ),
            staging_purged_count=staging_purged_count,
            preview_purged_count=preview_purged_count,
            orphan_preview_removed_count=orphan_preview_removed_count,
            formal_gc_report=formal_gc_report,
        )
