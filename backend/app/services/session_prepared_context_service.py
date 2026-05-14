from __future__ import annotations

from collections import OrderedDict
from typing import Callable

from backend.app.core.logging import get_logger
from backend.app.inference.prepared_context_types import (
    PreparedContextDescriptor,
    PreparedContextEntry,
    PreparedContextStats,
)

prepared_context_logger = get_logger("session_prepared_context_service")


class SessionPreparedContextService:
    def __init__(
        self,
        *,
        max_entries: int = 64,
        max_total_bytes: int = 256 * 1024 * 1024,
    ) -> None:
        self._max_entries = max(1, int(max_entries))
        self._max_total_bytes = max(1, int(max_total_bytes))
        self._entries_by_session: dict[str, OrderedDict[str, PreparedContextEntry]] = {}
        self._global_lru: OrderedDict[tuple[str, str], None] = OrderedDict()
        self._total_estimated_bytes = 0

    def get(self, *, session_id: str, cache_key: str) -> PreparedContextEntry | None:
        session_entries = self._entries_by_session.get(session_id)
        if session_entries is None:
            return None
        entry = session_entries.get(cache_key)
        if entry is None:
            return None
        entry.touch()
        session_entries.move_to_end(cache_key)
        self._touch_global(session_id=session_id, cache_key=cache_key)
        return entry

    def put(self, *, session_id: str, entry: PreparedContextEntry) -> PreparedContextEntry:
        session_entries = self._entries_by_session.setdefault(session_id, OrderedDict())
        existing = session_entries.pop(entry.cache_key, None)
        if existing is not None:
            self._total_estimated_bytes -= max(0, int(existing.estimated_bytes))
            self._dispose_entry(existing)
        entry.touch()
        session_entries[entry.cache_key] = entry
        self._touch_global(session_id=session_id, cache_key=entry.cache_key)
        self._total_estimated_bytes += max(0, int(entry.estimated_bytes))
        self._evict_if_needed()
        return entry

    def get_or_build(
        self,
        *,
        session_id: str,
        descriptor: PreparedContextDescriptor,
        builder: Callable[[PreparedContextDescriptor], PreparedContextEntry],
    ) -> PreparedContextEntry:
        cached = self.get(session_id=session_id, cache_key=descriptor.cache_key)
        if cached is not None:
            return cached
        built = builder(descriptor)
        if built.cache_key != descriptor.cache_key:
            raise ValueError("Prepared context entry cache_key must match descriptor cache_key.")
        if built.adapter_id != descriptor.adapter_id:
            raise ValueError("Prepared context entry adapter_id must match descriptor adapter_id.")
        return self.put(session_id=session_id, entry=built)

    def get_or_build_many(
        self,
        *,
        session_id: str,
        descriptors: list[PreparedContextDescriptor],
        builder: Callable[[PreparedContextDescriptor], PreparedContextEntry],
    ) -> dict[str, PreparedContextEntry]:
        resolved: dict[str, PreparedContextEntry] = {}
        for descriptor in descriptors:
            resolved[descriptor.cache_key] = self.get_or_build(
                session_id=session_id,
                descriptor=descriptor,
                builder=builder,
            )
        return resolved

    def clear_session(self, session_id: str) -> None:
        session_entries = self._entries_by_session.pop(session_id, None)
        if session_entries is None:
            return
        cleared_entry_count = len(session_entries)
        cleared_bytes = sum(max(0, int(entry.estimated_bytes)) for entry in session_entries.values())
        for cache_key, entry in list(session_entries.items()):
            self._global_lru.pop((session_id, cache_key), None)
            self._total_estimated_bytes -= max(0, int(entry.estimated_bytes))
            self._dispose_entry(entry)
        if self._total_estimated_bytes < 0:
            self._total_estimated_bytes = 0
        stats = self.stats()
        prepared_context_logger.info(
            "prepared context cleared session_id={} prepared_context_result=cleared prepared_context_reason=session_delete prepared_context_count={} prepared_context_total_bytes={} cleared_estimated_bytes={}",
            session_id,
            cleared_entry_count,
            stats.total_estimated_bytes,
            cleared_bytes,
        )

    def clear_all(self) -> None:
        cleared_session_count = len(self._entries_by_session)
        cleared_entry_count = sum(len(entries) for entries in self._entries_by_session.values())
        cleared_bytes = max(0, self._total_estimated_bytes)
        for session_id in list(self._entries_by_session):
            self.clear_session(session_id)
        self._global_lru.clear()
        self._total_estimated_bytes = 0
        prepared_context_logger.info(
            "prepared context cleared all prepared_context_result=cleared prepared_context_reason=process_exit session_count={} prepared_context_count={} prepared_context_total_bytes={} cleared_estimated_bytes={}",
            cleared_session_count,
            cleared_entry_count,
            self._total_estimated_bytes,
            cleared_bytes,
        )

    def stats(self) -> PreparedContextStats:
        return PreparedContextStats(
            session_count=len(self._entries_by_session),
            entry_count=sum(len(entries) for entries in self._entries_by_session.values()),
            total_estimated_bytes=max(0, self._total_estimated_bytes),
        )

    def _touch_global(self, *, session_id: str, cache_key: str) -> None:
        full_key = (session_id, cache_key)
        self._global_lru.pop(full_key, None)
        self._global_lru[full_key] = None

    def _evict_if_needed(self) -> None:
        while self.stats().entry_count > self._max_entries or self._total_estimated_bytes > self._max_total_bytes:
            try:
                session_id, cache_key = next(iter(self._global_lru))
            except StopIteration:
                break
            self._evict_one(session_id=session_id, cache_key=cache_key)

    def _evict_one(self, *, session_id: str, cache_key: str) -> None:
        self._global_lru.pop((session_id, cache_key), None)
        session_entries = self._entries_by_session.get(session_id)
        if session_entries is None:
            return
        entry = session_entries.pop(cache_key, None)
        if entry is None:
            return
        self._total_estimated_bytes -= max(0, int(entry.estimated_bytes))
        self._dispose_entry(entry)
        if not session_entries:
            self._entries_by_session.pop(session_id, None)
        if self._total_estimated_bytes < 0:
            self._total_estimated_bytes = 0
        stats = self.stats()
        prepared_context_logger.info(
            "prepared context evicted session_id={} adapter_id={} prepared_context_key={} prepared_context_result=evicted prepared_context_reason=lru prepared_context_estimated_bytes={} prepared_context_count={} prepared_context_total_bytes={}",
            session_id,
            entry.adapter_id,
            cache_key,
            max(0, int(entry.estimated_bytes)),
            stats.entry_count,
            stats.total_estimated_bytes,
        )

    @staticmethod
    def _dispose_entry(entry: PreparedContextEntry) -> None:
        if not callable(entry.dispose):
            return
        try:
            entry.dispose()
        except Exception:
            prepared_context_logger.warning(
                "prepared context dispose failed adapter_id={} prepared_context_key={}",
                entry.adapter_id,
                entry.cache_key,
            )
            return
