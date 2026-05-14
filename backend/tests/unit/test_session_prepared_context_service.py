from __future__ import annotations

from pathlib import Path

import pytest

from backend.app.repositories.edit_session_repository import EditSessionRepository
from backend.app.schemas.edit_session import ActiveDocumentState
from backend.app.services.edit_session_runtime import EditSessionRuntime
from backend.app.services.edit_session_service import EditSessionService
from backend.app.services.session_prepared_context_service import SessionPreparedContextService
from backend.app.inference.prepared_context_types import PreparedContextDescriptor, PreparedContextEntry


class _FakeAssetStore:
    def __init__(self, *, assets_root: Path) -> None:
        self.assets_root = assets_root
        self.clear_calls = 0

    def clear_all(self) -> None:
        self.clear_calls += 1


def _build_repository(tmp_path: Path) -> EditSessionRepository:
    repository = EditSessionRepository(
        project_root=tmp_path,
        db_file=tmp_path / "storage" / "edit_session" / "session.db",
    )
    repository.initialize_schema()
    return repository


def _build_descriptor(cache_key: str) -> PreparedContextDescriptor:
    return PreparedContextDescriptor(
        adapter_id="demo_adapter",
        cache_key=cache_key,
        debug_summary={"cache_key": cache_key},
    )


def _build_entry(cache_key: str, *, disposed: list[str]) -> PreparedContextEntry:
    return PreparedContextEntry(
        adapter_id="demo_adapter",
        cache_key=cache_key,
        payload={"cache_key": cache_key},
        estimated_bytes=16,
        dispose=lambda: disposed.append(cache_key),
    )


def test_session_prepared_context_service_reuses_same_entry_within_session():
    service = SessionPreparedContextService(max_entries=4, max_total_bytes=1_024)
    build_calls: list[str] = []

    def _builder(descriptor: PreparedContextDescriptor) -> PreparedContextEntry:
        build_calls.append(descriptor.cache_key)
        return PreparedContextEntry(
            adapter_id=descriptor.adapter_id,
            cache_key=descriptor.cache_key,
            payload={"cache_key": descriptor.cache_key},
            estimated_bytes=8,
        )

    first = service.get_or_build(session_id="doc-1", descriptor=_build_descriptor("ctx-1"), builder=_builder)
    second = service.get_or_build(session_id="doc-1", descriptor=_build_descriptor("ctx-1"), builder=_builder)

    assert build_calls == ["ctx-1"]
    assert first is second
    assert service.stats().entry_count == 1


def test_session_prepared_context_service_clear_session_only_disposes_current_session_entries():
    service = SessionPreparedContextService(max_entries=4, max_total_bytes=1_024)
    disposed: list[str] = []

    service.put(session_id="doc-1", entry=_build_entry("ctx-1", disposed=disposed))
    service.put(session_id="doc-2", entry=_build_entry("ctx-2", disposed=disposed))

    service.clear_session("doc-1")

    assert disposed == ["ctx-1"]
    assert service.get(session_id="doc-1", cache_key="ctx-1") is None
    assert service.get(session_id="doc-2", cache_key="ctx-2") is not None
    assert service.stats().entry_count == 1


def test_session_prepared_context_service_clear_session_logs_summary(monkeypatch: pytest.MonkeyPatch):
    logged: list[tuple[str, tuple]] = []

    class _FakeLogger:
        def info(self, message, *args):
            logged.append((message, args))

        def warning(self, message, *args):
            return None

    monkeypatch.setattr(
        "backend.app.services.session_prepared_context_service.prepared_context_logger",
        _FakeLogger(),
    )
    service = SessionPreparedContextService(max_entries=4, max_total_bytes=1_024)
    disposed: list[str] = []

    service.put(session_id="doc-1", entry=_build_entry("ctx-1", disposed=disposed))
    service.put(session_id="doc-2", entry=_build_entry("ctx-2", disposed=disposed))
    service.clear_session("doc-1")

    assert logged == [
        (
            "prepared context cleared session_id={} prepared_context_result=cleared prepared_context_reason=session_delete prepared_context_count={} prepared_context_total_bytes={} cleared_estimated_bytes={}",
            ("doc-1", 1, 16, 16),
        )
    ]


def test_session_prepared_context_service_clear_all_disposes_every_entry():
    service = SessionPreparedContextService(max_entries=4, max_total_bytes=1_024)
    disposed: list[str] = []

    service.put(session_id="doc-1", entry=_build_entry("ctx-1", disposed=disposed))
    service.put(session_id="doc-2", entry=_build_entry("ctx-2", disposed=disposed))

    service.clear_all()

    assert disposed == ["ctx-1", "ctx-2"]
    assert service.stats().entry_count == 0
    assert service.stats().session_count == 0


def test_session_prepared_context_service_clear_all_logs_summary(monkeypatch: pytest.MonkeyPatch):
    logged: list[tuple[str, tuple]] = []

    class _FakeLogger:
        def info(self, message, *args):
            logged.append((message, args))

        def warning(self, message, *args):
            return None

    monkeypatch.setattr(
        "backend.app.services.session_prepared_context_service.prepared_context_logger",
        _FakeLogger(),
    )
    service = SessionPreparedContextService(max_entries=4, max_total_bytes=1_024)
    disposed: list[str] = []

    service.put(session_id="doc-1", entry=_build_entry("ctx-1", disposed=disposed))
    service.put(session_id="doc-2", entry=_build_entry("ctx-2", disposed=disposed))
    service.clear_all()

    assert logged == [
        (
            "prepared context cleared session_id={} prepared_context_result=cleared prepared_context_reason=session_delete prepared_context_count={} prepared_context_total_bytes={} cleared_estimated_bytes={}",
            ("doc-1", 1, 16, 16),
        ),
        (
            "prepared context cleared session_id={} prepared_context_result=cleared prepared_context_reason=session_delete prepared_context_count={} prepared_context_total_bytes={} cleared_estimated_bytes={}",
            ("doc-2", 1, 0, 16),
        ),
        (
            "prepared context cleared all prepared_context_result=cleared prepared_context_reason=process_exit session_count={} prepared_context_count={} prepared_context_total_bytes={} cleared_estimated_bytes={}",
            (2, 2, 0, 32),
        ),
    ]


def test_session_prepared_context_service_evicts_oldest_entry_when_capacity_is_exceeded():
    service = SessionPreparedContextService(max_entries=1, max_total_bytes=1_024)
    disposed: list[str] = []

    service.put(session_id="doc-1", entry=_build_entry("ctx-1", disposed=disposed))
    service.put(session_id="doc-1", entry=_build_entry("ctx-2", disposed=disposed))

    assert disposed == ["ctx-1"]
    assert service.get(session_id="doc-1", cache_key="ctx-1") is None
    assert service.get(session_id="doc-1", cache_key="ctx-2") is not None


def test_session_prepared_context_service_evict_logs_summary(monkeypatch: pytest.MonkeyPatch):
    logged: list[tuple[str, tuple]] = []

    class _FakeLogger:
        def info(self, message, *args):
            logged.append((message, args))

        def warning(self, message, *args):
            return None

    monkeypatch.setattr(
        "backend.app.services.session_prepared_context_service.prepared_context_logger",
        _FakeLogger(),
    )
    service = SessionPreparedContextService(max_entries=1, max_total_bytes=1_024)
    disposed: list[str] = []

    service.put(session_id="doc-1", entry=_build_entry("ctx-1", disposed=disposed))
    service.put(session_id="doc-1", entry=_build_entry("ctx-2", disposed=disposed))

    assert logged == [
        (
            "prepared context evicted session_id={} adapter_id={} prepared_context_key={} prepared_context_result=evicted prepared_context_reason=lru prepared_context_estimated_bytes={} prepared_context_count={} prepared_context_total_bytes={}",
            ("doc-1", "demo_adapter", "ctx-1", 16, 1, 16),
        )
    ]


def test_session_prepared_context_service_logs_dispose_failure_warning(monkeypatch: pytest.MonkeyPatch):
    logged_warnings: list[tuple[str, tuple]] = []

    class _FakeLogger:
        def info(self, message, *args):
            return None

        def warning(self, message, *args):
            logged_warnings.append((message, args))

    monkeypatch.setattr(
        "backend.app.services.session_prepared_context_service.prepared_context_logger",
        _FakeLogger(),
    )
    service = SessionPreparedContextService(max_entries=1, max_total_bytes=1_024)

    service.put(
        session_id="doc-1",
        entry=PreparedContextEntry(
            adapter_id="demo_adapter",
            cache_key="ctx-1",
            payload={"cache_key": "ctx-1"},
            estimated_bytes=16,
            dispose=lambda: (_ for _ in ()).throw(RuntimeError("dispose failed")),
        ),
    )
    service.clear_session("doc-1")

    assert logged_warnings == [
        (
            "prepared context dispose failed adapter_id={} prepared_context_key={}",
            ("demo_adapter", "ctx-1"),
        )
    ]


def test_edit_session_service_delete_session_clears_prepared_context_for_active_document(tmp_path: Path):
    repository = _build_repository(tmp_path)
    repository.upsert_active_session(
        ActiveDocumentState(
            document_id="doc-1",
            session_status="ready",
            active_job_id=None,
        )
    )
    asset_store = _FakeAssetStore(assets_root=tmp_path / "assets")
    runtime = EditSessionRuntime()
    prepared_context_service = SessionPreparedContextService(max_entries=4, max_total_bytes=1_024)
    prepared_context_service.put(
        session_id="doc-1",
        entry=PreparedContextEntry(
            adapter_id="demo_adapter",
            cache_key="ctx-1",
            payload={"cache_key": "ctx-1"},
            estimated_bytes=8,
        ),
    )
    service = EditSessionService(
        repository=repository,
        asset_store=asset_store,
        runtime=runtime,
        session_prepared_context_service=prepared_context_service,
    )

    service.delete_session()

    assert prepared_context_service.stats().entry_count == 0
    assert asset_store.clear_calls == 1
    assert repository.get_active_session() is None
