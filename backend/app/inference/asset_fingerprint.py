from __future__ import annotations

import hashlib
from collections import OrderedDict
from pathlib import Path
from threading import RLock


class ContentHashCache:
    """Bounded probe cache that accelerates, but never replaces, content identity."""

    def __init__(self, *, max_entries: int = 256) -> None:
        self._max_entries = max_entries
        self._entries: OrderedDict[tuple[str, int, int], str] = OrderedDict()
        self._lock = RLock()

    def digest(self, path: str | Path) -> str:
        resolved = Path(path).resolve()
        stat = resolved.stat()
        probe = (str(resolved), stat.st_size, stat.st_mtime_ns)
        with self._lock:
            cached = self._entries.get(probe)
            if cached is not None:
                self._entries.move_to_end(probe)
                return cached
        digest = content_sha256(resolved)
        with self._lock:
            self._entries[probe] = digest
            self._entries.move_to_end(probe)
            while len(self._entries) > self._max_entries:
                self._entries.popitem(last=False)
        return digest


_content_hash_cache = ContentHashCache()


def fingerprint_file(path: str | Path) -> str:
    resolved = Path(path).resolve()
    stat = resolved.stat()
    encoded = "|".join(
        [
            resolved.as_posix(),
            str(stat.st_size),
            str(stat.st_mtime_ns),
        ]
    )
    return hashlib.sha1(encoded.encode("utf-8")).hexdigest()


def content_sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def cached_content_sha256(path: str | Path) -> str:
    return _content_hash_cache.digest(path)


def fingerprint_text(value: str) -> str:
    return hashlib.sha1(value.encode("utf-8")).hexdigest()
