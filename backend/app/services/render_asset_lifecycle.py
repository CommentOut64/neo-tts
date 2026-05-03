from __future__ import annotations

from dataclasses import dataclass, field

from backend.app.repositories.edit_session_repository import EditSessionRepository
from backend.app.services.edit_asset_store import EditAssetStore


@dataclass(frozen=True)
class PublishedAssetRef:
    asset_kind: str
    asset_id: str
    owner_id: str | None = None

    @property
    def relative_path(self) -> str:
        category = {
            "segment": "segments",
            "block": "blocks",
            "timeline": "timelines",
            "composition": "compositions",
            "boundary": "boundaries",
            "preview": "previews",
        }.get(self.asset_kind, f"{self.asset_kind}s")
        return f"{category}/{self.asset_id}"


@dataclass(frozen=True)
class ReusableSourceAssetRef:
    segment_id: str
    render_asset_id: str
    owner_id: str | None = None

    @property
    def relative_path(self) -> str:
        return f"segments/{self.render_asset_id}"


@dataclass(frozen=True)
class EphemeralExecutionAssetRef:
    asset_kind: str
    asset_id: str
    job_id: str


@dataclass(frozen=True)
class AssetPinSet:
    published_assets: list[PublishedAssetRef] = field(default_factory=list)
    reusable_source_assets: list[ReusableSourceAssetRef] = field(default_factory=list)
    pinned_relative_paths: set[str] = field(default_factory=set)


@dataclass(frozen=True)
class OrphanedAssetReport:
    pin_set: AssetPinSet
    orphaned_relative_paths: list[str] = field(default_factory=list)
    kept_relative_paths: list[str] = field(default_factory=list)


class RenderAssetLifecycle:
    def __init__(self, *, repository: EditSessionRepository, asset_store: EditAssetStore) -> None:
        self._repository = repository
        self._asset_store = asset_store

    def collect_pin_set(self) -> AssetPinSet:
        graph = self._repository.collect_referenced_asset_ids()
        published_assets: list[PublishedAssetRef] = []
        reusable_source_assets: list[ReusableSourceAssetRef] = []
        seen_published: set[tuple[str, str]] = set()
        seen_reusable: set[str] = set()

        for asset_id in sorted(graph.block_ids):
            published_assets.append(PublishedAssetRef(asset_kind="block", asset_id=asset_id))
            seen_published.add(("block", asset_id))
        for asset_id in sorted(graph.timeline_manifest_ids):
            published_assets.append(PublishedAssetRef(asset_kind="timeline", asset_id=asset_id))
            seen_published.add(("timeline", asset_id))
        for asset_id in sorted(graph.composition_manifest_ids):
            published_assets.append(PublishedAssetRef(asset_kind="composition", asset_id=asset_id))
            seen_published.add(("composition", asset_id))
        for asset_id in sorted(graph.boundary_asset_ids):
            published_assets.append(PublishedAssetRef(asset_kind="boundary", asset_id=asset_id))
            seen_published.add(("boundary", asset_id))
        for asset_id in sorted(graph.preview_asset_ids):
            published_assets.append(PublishedAssetRef(asset_kind="preview", asset_id=asset_id))
            seen_published.add(("preview", asset_id))

        for snapshot in self._collect_snapshots_for_scan():
            for segment in snapshot.segments:
                if segment.render_asset_id is not None and ("segment", segment.render_asset_id) not in seen_published:
                    published_assets.append(
                        PublishedAssetRef(
                            asset_kind="segment",
                            asset_id=segment.render_asset_id,
                            owner_id=segment.segment_id,
                        )
                    )
                    seen_published.add(("segment", segment.render_asset_id))
                if segment.base_render_asset_id is not None and segment.base_render_asset_id not in seen_reusable:
                    reusable_source_assets.append(
                        ReusableSourceAssetRef(
                            segment_id=segment.segment_id,
                            render_asset_id=segment.base_render_asset_id,
                            owner_id=segment.segment_id,
                        )
                    )
                    seen_reusable.add(segment.base_render_asset_id)

        return AssetPinSet(
            published_assets=published_assets,
            reusable_source_assets=reusable_source_assets,
            pinned_relative_paths=graph.as_relative_asset_paths(),
        )

    def scan_orphaned_assets(self) -> OrphanedAssetReport:
        pin_set = self.collect_pin_set()
        gc_report = self._asset_store.collect_unreferenced_formal_assets(
            pin_set.pinned_relative_paths,
            dry_run=True,
        )
        return OrphanedAssetReport(
            pin_set=pin_set,
            orphaned_relative_paths=sorted(
                path.relative_to(self._asset_store._formal_root).as_posix()  # noqa: SLF001
                for path in gc_report.deleted_asset_paths
            ),
            kept_relative_paths=sorted(
                path.relative_to(self._asset_store._formal_root).as_posix()  # noqa: SLF001
                for path in gc_report.kept_asset_paths
            ),
        )

    def _collect_snapshots_for_scan(self):
        snapshots = []
        recoverable = self._repository.load_recoverable_state()
        if recoverable is not None:
            snapshots.append(recoverable.head_snapshot)
            if recoverable.baseline_snapshot is not None:
                snapshots.append(recoverable.baseline_snapshot)

        active_session = self._repository.get_active_session()
        if active_session is not None:
            checkpoint = self._repository.get_latest_checkpoint(active_session.document_id)
            if checkpoint is not None:
                checkpoint_head = self._repository.get_snapshot(checkpoint.head_snapshot_id)
                checkpoint_working = self._repository.get_snapshot(checkpoint.working_snapshot_id)
                if checkpoint_head is not None:
                    snapshots.append(checkpoint_head)
                if checkpoint_working is not None:
                    snapshots.append(checkpoint_working)
        return snapshots
