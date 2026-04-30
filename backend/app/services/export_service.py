from __future__ import annotations

from contextlib import suppress
from datetime import datetime, timezone
import json
from pathlib import Path
import queue
import shutil
import threading
from uuid import uuid4

from backend.app.core.exceptions import EditSessionNotFoundError
from backend.app.inference.audio_processing import build_wav_bytes, float_audio_chunk_to_pcm16_bytes
from backend.app.repositories.edit_session_repository import EditSessionRepository
from backend.app.schemas.edit_session import (
    CompositionExportRequest,
    ExportRequest,
    ExportJobAcceptedResponse,
    ExportJobRecord,
    ExportJobResponse,
    ExportOutputManifest,
    ExportSubtitleManifest,
    ExportSubtitleRequest,
    SegmentExportRequest,
)
from backend.app.services.composition_builder import CompositionBuilder
from backend.app.services.edit_asset_store import EditAssetStore
from backend.app.services.subtitle_export_service import SubtitleExportService


class ExportService:
    ACTIVE_STATUSES = {"queued", "exporting"}
    TERMINAL_STATUSES = {"completed", "failed"}

    def __init__(
        self,
        *,
        repository: EditSessionRepository,
        asset_store: EditAssetStore,
        subtitle_export_service: SubtitleExportService | None = None,
        run_jobs_in_background: bool = True,
    ) -> None:
        self._repository = repository
        self._asset_store = asset_store
        self._subtitle_export_service = subtitle_export_service or SubtitleExportService()
        self._run_jobs_in_background = run_jobs_in_background
        self._composition_builder = CompositionBuilder()
        self._lock = threading.Lock()
        self._jobs: dict[str, ExportJobResponse] = {}
        self._events: dict[str, list[dict[str, object]]] = {}
        self._subscribers: dict[str, set[queue.Queue[dict[str, object]]]] = {}

    def create_export_job(self, request: ExportRequest) -> ExportJobAcceptedResponse:
        return self._create_export_job(
            export_kind=request.audio.kind,
            document_version=request.document_version,
            target_dir=request.target_dir,
            overwrite_policy=request.audio.overwrite_policy,
            subtitle=request.subtitle,
            message="已创建统一导出作业。",
        )

    def create_segment_export_job(self, request: SegmentExportRequest) -> ExportJobAcceptedResponse:
        return self.create_export_job(
            ExportRequest(
                document_version=request.document_version,
                target_dir=request.target_dir,
                audio={
                    "kind": "segments",
                    "overwrite_policy": request.overwrite_policy,
                },
            )
        )

    def create_composition_export_job(self, request: CompositionExportRequest) -> ExportJobAcceptedResponse:
        return self.create_export_job(
            ExportRequest(
                document_version=request.document_version,
                target_dir=request.target_dir,
                audio={
                    "kind": "composition",
                    "overwrite_policy": request.overwrite_policy,
                },
            )
        )

    def get_job(self, export_job_id: str) -> ExportJobResponse | None:
        with self._lock:
            runtime_job = self._jobs.get(export_job_id)
            if runtime_job is not None:
                return runtime_job.model_copy(deep=True)
        record = self._repository.get_export_job(export_job_id)
        if record is None:
            return None
        return ExportJobResponse.model_validate(record.model_dump())

    def subscribe(self, export_job_id: str) -> queue.Queue[dict[str, object]]:
        subscriber: queue.Queue[dict[str, object]] = queue.Queue(maxsize=64)
        with self._lock:
            subscribers = self._subscribers.setdefault(export_job_id, set())
            subscribers.add(subscriber)
            for event in self._events.get(export_job_id, []):
                self._put_nowait(subscriber, event)
        return subscriber

    def unsubscribe(self, export_job_id: str, subscriber: queue.Queue[dict[str, object]]) -> None:
        with self._lock:
            subscribers = self._subscribers.get(export_job_id)
            if subscribers is None:
                return
            subscribers.discard(subscriber)
            if not subscribers:
                self._subscribers.pop(export_job_id, None)

    def run_export_job(self, export_job_id: str) -> None:
        job = self.get_job(export_job_id)
        if job is None:
            raise EditSessionNotFoundError(f"Export job '{export_job_id}' not found.")

        try:
            self._update_job(
                export_job_id,
                status="exporting",
                progress=0.05,
                message="正在准备导出目录与清单。",
            )
            output_manifest = self._export(job)
        except Exception as exc:
            current_job = self.get_job(export_job_id)
            if current_job is not None and current_job.staging_dir:
                with suppress(Exception):
                    self._asset_store.cleanup_export_staging_dir(current_job.staging_dir)
            self._update_job(
                export_job_id,
                status="failed",
                progress=0.0,
                message=str(exc),
            )
            return

        self._emit_event(
            export_job_id,
            "export_completed",
            {
                "export_job_id": export_job_id,
                "export_kind": job.export_kind,
                "output_manifest": output_manifest.model_dump(mode="json"),
            },
        )
        self._update_job(
            export_job_id,
            status="completed",
            progress=1.0,
            message="导出完成。",
            output_manifest=output_manifest,
            staging_dir=None,
        )

    def _create_export_job(
        self,
        *,
        export_kind: str,
        document_version: int,
        target_dir: str,
        overwrite_policy: str,
        subtitle: ExportSubtitleRequest,
        message: str,
    ) -> ExportJobAcceptedResponse:
        active_session = self._repository.get_active_session()
        if active_session is None:
            raise EditSessionNotFoundError("Active edit session not found.")
        snapshot = self._repository.get_snapshot_by_document_version(active_session.document_id, document_version)
        if snapshot is None:
            raise EditSessionNotFoundError(f"Document version '{document_version}' not found.")
        if snapshot.timeline_manifest_id is None:
            raise EditSessionNotFoundError("Timeline manifest not found for requested document version.")

        resolved_target_dir = str(self._asset_store.resolve_export_target_dir(target_dir))
        now = datetime.now(timezone.utc)
        job = ExportJobResponse(
            export_job_id=uuid4().hex,
            document_id=snapshot.document_id,
            document_version=snapshot.document_version,
            timeline_manifest_id=snapshot.timeline_manifest_id,
            export_kind=export_kind,
            subtitle=subtitle,
            status="queued",
            target_dir=resolved_target_dir,
            overwrite_policy=overwrite_policy,
            progress=0.0,
            message=message,
            updated_at=now,
        )
        self._repository.save_export_job(
            ExportJobRecord(
                **job.model_dump(mode="python"),
                created_at=now,
            )
        )
        self._start_job(job)
        if self._run_jobs_in_background:
            worker = threading.Thread(target=self.run_export_job, args=(job.export_job_id,), daemon=True)
            worker.start()
        return ExportJobAcceptedResponse(job=self.get_job(job.export_job_id) or job)

    def _export(self, job: ExportJobResponse) -> ExportOutputManifest:
        snapshot = self._repository.get_snapshot_by_document_version(job.document_id, job.document_version)
        if snapshot is None:
            raise EditSessionNotFoundError(
                f"Document version '{job.document_version}' not found for export job '{job.export_job_id}'."
            )
        export_root_dir, staging_dir = self._asset_store.prepare_export_staging_dir(
            export_job_id=job.export_job_id,
            target_dir=job.target_dir,
        )
        self._update_job(job.export_job_id, staging_dir=str(staging_dir))
        timeline = self._asset_store.load_timeline_manifest(snapshot.timeline_manifest_id)
        if job.export_kind == "segments":
            return self._export_segments(
                job=job,
                snapshot=snapshot,
                timeline=timeline,
                export_root_dir=export_root_dir,
                staging_dir=staging_dir,
            )
        if job.export_kind == "composition":
            return self._export_composition(
                job=job,
                snapshot=snapshot,
                timeline=timeline,
                export_root_dir=export_root_dir,
                staging_dir=staging_dir,
            )
        raise ValueError(f"Unsupported export kind: {job.export_kind}")

    def _export_segments(
        self,
        *,
        job: ExportJobResponse,
        snapshot,
        timeline,
        export_root_dir: Path,
        staging_dir: Path,
    ) -> ExportOutputManifest:
        export_dir_name = self._build_export_name(job)
        segment_files: list[str] = []
        subtitle_file_name = f"{export_dir_name}.srt"
        subtitle_payload = self._build_subtitle_export_payload(job=job, snapshot=snapshot, timeline=timeline)
        total_file_count = len(snapshot.segments) + (1 if subtitle_payload is not None else 0) + 1
        for index, segment in enumerate(snapshot.segments, start=1):
            if segment.render_asset_id is None:
                raise EditSessionNotFoundError(f"Segment '{segment.segment_id}' has no render asset to export.")
            destination = staging_dir / f"segments-{index}.wav"
            shutil.copy2(self._asset_store.segment_asset_path(segment.render_asset_id) / "audio.wav", destination)
            segment_files.append(str(destination))
            self._emit_export_progress(
                job=job,
                completed_file_count=index,
                total_file_count=total_file_count,
                current_path=destination,
            )

        subtitle_files: list[str] = []
        subtitle_manifest: ExportSubtitleManifest | None = None
        if subtitle_payload is not None:
            subtitle_path = staging_dir / subtitle_file_name
            subtitle_path.write_text(subtitle_payload.payload, encoding="utf-8")
            subtitle_files.append(str(subtitle_path))
            subtitle_manifest = ExportSubtitleManifest(
                format=subtitle_payload.format,
                offset_seconds=subtitle_payload.offset_seconds,
                strip_trailing_punctuation=subtitle_payload.strip_trailing_punctuation,
            )
            self._emit_export_progress(
                job=job,
                completed_file_count=len(snapshot.segments) + 1,
                total_file_count=total_file_count,
                current_path=subtitle_path,
            )

        manifest_path = staging_dir / "manifest.json"
        manifest_payload = {
            "export_kind": "segments",
            "document_id": snapshot.document_id,
            "document_version": snapshot.document_version,
            "timeline_manifest_id": snapshot.timeline_manifest_id,
            "segment_files": [Path(path).name for path in segment_files],
            "audio_files": [Path(path).name for path in segment_files],
            "subtitle_files": [Path(path).name for path in subtitle_files],
            "subtitle_manifest": subtitle_manifest.model_dump(mode="json") if subtitle_manifest is not None else None,
        }
        manifest_path.write_text(json.dumps(manifest_payload, ensure_ascii=False, indent=2), encoding="utf-8")
        stored_manifest_path = self._write_export_manifest(job.export_job_id, manifest_payload)
        manifest_path.unlink(missing_ok=True)
        final_dir = self._asset_store.finalize_export_staging_dir(
            staging_dir=staging_dir,
            target_dir=export_root_dir / export_dir_name,
            overwrite_policy=job.overwrite_policy,
        )
        final_segment_files = [str(final_dir / f"segments-{index}.wav") for index in range(1, len(segment_files) + 1)]
        final_subtitle_files = [str(final_dir / subtitle_file_name)] if subtitle_files else []
        all_files = final_segment_files + final_subtitle_files
        return ExportOutputManifest(
            export_kind="segments",
            target_dir=str(final_dir),
            files=all_files,
            audio_files=final_segment_files,
            subtitle_files=final_subtitle_files,
            segment_files=final_segment_files,
            subtitle_manifest=subtitle_manifest,
            manifest_file=str(stored_manifest_path),
        )

    def _export_composition(
        self,
        *,
        job: ExportJobResponse,
        snapshot,
        timeline,
        export_root_dir: Path,
        staging_dir: Path,
    ) -> ExportOutputManifest:
        export_name = self._build_export_name(job)
        blocks = [self._asset_store.load_block_asset(entry.block_asset_id) for entry in timeline.block_entries]
        composition_manifest = self._composition_builder.compose_document(
            document_id=snapshot.document_id,
            document_version=snapshot.document_version,
            blocks=blocks,
        )
        composition_source = self._write_formal_composition_asset(composition_manifest)
        composition_path = staging_dir / f"{export_name}.wav"
        shutil.copy2(composition_source, composition_path)
        subtitle_payload = self._build_subtitle_export_payload(job=job, snapshot=snapshot, timeline=timeline)
        total_file_count = 2 + (1 if subtitle_payload is not None else 0)
        self._emit_export_progress(
            job=job,
            completed_file_count=1,
            total_file_count=total_file_count,
            current_path=composition_path,
        )
        subtitle_path: Path | None = None
        subtitle_manifest: ExportSubtitleManifest | None = None
        if subtitle_payload is not None:
            subtitle_path = staging_dir / f"{export_name}.srt"
            subtitle_path.write_text(subtitle_payload.payload, encoding="utf-8")
            subtitle_manifest = ExportSubtitleManifest(
                format=subtitle_payload.format,
                offset_seconds=subtitle_payload.offset_seconds,
                strip_trailing_punctuation=subtitle_payload.strip_trailing_punctuation,
            )
            self._emit_export_progress(
                job=job,
                completed_file_count=2,
                total_file_count=total_file_count,
                current_path=subtitle_path,
            )
        manifest_path = staging_dir / f"{export_name}.manifest.json"
        manifest_payload = {
            "export_kind": "composition",
            "document_id": snapshot.document_id,
            "document_version": snapshot.document_version,
            "timeline_manifest_id": snapshot.timeline_manifest_id,
            "composition_file": composition_path.name,
            "audio_files": [composition_path.name],
            "subtitle_files": [subtitle_path.name] if subtitle_path is not None else [],
            "subtitle_manifest": subtitle_manifest.model_dump(mode="json") if subtitle_manifest is not None else None,
        }
        manifest_path.write_text(json.dumps(manifest_payload, ensure_ascii=False, indent=2), encoding="utf-8")
        stored_manifest_path = self._write_export_manifest(job.export_job_id, manifest_payload)
        manifest_path.unlink(missing_ok=True)
        final_composition_path = self._asset_store.finalize_export_file(
            staging_file=composition_path,
            target_file=export_root_dir / composition_path.name,
            overwrite_policy=job.overwrite_policy,
        )
        final_subtitle_files: list[str] = []
        if subtitle_path is not None:
            final_subtitle_path = self._asset_store.finalize_export_file(
                staging_file=subtitle_path,
                target_file=export_root_dir / subtitle_path.name,
                overwrite_policy=job.overwrite_policy,
            )
            final_subtitle_files = [str(final_subtitle_path)]
        self._asset_store.cleanup_export_staging_dir(staging_dir)
        return ExportOutputManifest(
            export_kind="composition",
            target_dir=str(export_root_dir),
            files=[str(final_composition_path), *final_subtitle_files],
            audio_files=[str(final_composition_path)],
            subtitle_files=final_subtitle_files,
            composition_file=str(final_composition_path),
            composition_manifest_id=composition_manifest.composition_manifest_id,
            subtitle_manifest=subtitle_manifest,
            manifest_file=str(stored_manifest_path),
        )

    @staticmethod
    def _build_export_name(job: ExportJobResponse) -> str:
        timestamp = job.updated_at.astimezone().strftime("%Y%m%d-%H%M%S-%f")[:-3]
        return f"neo-tts-export-{timestamp}"

    def _write_export_manifest(self, export_job_id: str, payload: dict[str, object]) -> Path:
        return self._asset_store.write_formal_json_atomic(
            f"exports/{export_job_id}/manifest.json",
            payload,
        )

    def _build_subtitle_export_payload(self, *, job: ExportJobResponse, snapshot, timeline):
        if not job.subtitle.enabled:
            return None
        return self._subtitle_export_service.export(
            request=job.subtitle,
            snapshot=snapshot,
            timeline=timeline,
        )

    def _emit_export_progress(
        self,
        *,
        job: ExportJobResponse,
        completed_file_count: int,
        total_file_count: int,
        current_path: Path,
    ) -> None:
        progress = completed_file_count / max(total_file_count, 1)
        self._update_job(
            job.export_job_id,
            progress=progress,
            message=f"正在导出 {current_path.name}。",
        )
        self._emit_event(
            job.export_job_id,
            "export_progress",
            {
                "export_job_id": job.export_job_id,
                "export_kind": job.export_kind,
                "completed_file_count": completed_file_count,
                "total_file_count": total_file_count,
                "current_path": str(current_path),
                "progress": progress,
            },
        )

    def _start_job(self, job: ExportJobResponse) -> None:
        with self._lock:
            started_job = job.model_copy(deep=True)
            started_job.updated_at = datetime.now(timezone.utc)
            self._jobs[started_job.export_job_id] = started_job
            self._events[started_job.export_job_id] = []
            self._append_job_state_event_locked(started_job.export_job_id)

    def _update_job(self, export_job_id: str, **changes) -> None:
        with self._lock:
            job = self._jobs.get(export_job_id)
            if job is None:
                record = self._repository.get_export_job(export_job_id)
                if record is None:
                    return
                job = ExportJobResponse.model_validate(record.model_dump())
                self._jobs[export_job_id] = job
                self._events.setdefault(export_job_id, [])
            for field_name, value in changes.items():
                if not hasattr(job, field_name):
                    continue
                if field_name == "progress" and value is not None:
                    value = max(0.0, min(1.0, float(value)))
                setattr(job, field_name, value)
            job.updated_at = datetime.now(timezone.utc)
            self._repository.save_export_job(
                ExportJobRecord(
                    **job.model_dump(mode="python"),
                    created_at=self._repository.get_export_job(export_job_id).created_at
                    if self._repository.get_export_job(export_job_id) is not None
                    else datetime.now(timezone.utc),
                )
            )
            self._append_job_state_event_locked(export_job_id)

    def _append_job_state_event_locked(self, export_job_id: str) -> None:
        job = self._jobs.get(export_job_id)
        if job is None:
            return
        self._append_event_locked(export_job_id, "job_state_changed", job.model_dump(mode="json"))

    def _emit_event(self, export_job_id: str, event_type: str, payload: dict[str, object]) -> None:
        with self._lock:
            if export_job_id not in self._jobs:
                return
            self._append_event_locked(export_job_id, event_type, payload)

    def _append_event_locked(self, export_job_id: str, event_type: str, payload: dict[str, object]) -> None:
        event = {"event": event_type, "data": payload}
        history = self._events.setdefault(export_job_id, [])
        history.append(event)
        if len(history) > 256:
            del history[:-256]
        stale: list[queue.Queue[dict[str, object]]] = []
        for subscriber in self._subscribers.get(export_job_id, set()):
            try:
                self._put_nowait(subscriber, event)
            except Exception:
                stale.append(subscriber)
        for subscriber in stale:
            subscribers = self._subscribers.get(export_job_id)
            if subscribers is not None:
                subscribers.discard(subscriber)

    @staticmethod
    def _put_nowait(subscriber: queue.Queue[dict[str, object]], payload: dict[str, object]) -> None:
        if subscriber.full():
            with suppress(queue.Empty):
                subscriber.get_nowait()
        subscriber.put_nowait(payload)

    def _write_formal_composition_asset(self, composition_manifest) -> Path:
        audio = composition_manifest.audio
        wav_bytes = build_wav_bytes(
            composition_manifest.sample_rate,
            float_audio_chunk_to_pcm16_bytes(audio.astype("float32", copy=False)),
        )
        return self._asset_store.write_formal_bytes_atomic(
            f"compositions/{composition_manifest.composition_manifest_id}/audio.wav",
            wav_bytes,
        )
