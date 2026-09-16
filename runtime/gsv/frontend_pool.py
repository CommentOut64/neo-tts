"""Process-local frontend resources shared explicitly by Runtime owners."""
from __future__ import annotations

import hashlib
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any


def content_revision(path: str | Path) -> str:
    root = Path(path)
    digest = hashlib.sha256()
    paths = (item for item in root.rglob("*") if item.is_file()) if root.is_dir() else (root,)
    for item in sorted(paths):
        digest.update(str(item.relative_to(root) if root.is_dir() else item.name).encode("utf-8"))
        with item.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
    return digest.hexdigest()


@dataclass
class _Entry:
    value: dict[str, Any]
    active: int = 0


class SharedFrontendPool:
    """Lease CNHubert/BERT/tokenizer/SV by content revision, device and dtype."""

    def __init__(self) -> None:
        self._entries: dict[tuple[str, ...], _Entry] = {}
        self._lock = threading.RLock()

    def acquire(self, *, cnhubert_path: str | Path, bert_path: str | Path, sv_path: str | Path, device: str, dtype: str, factory: Callable[[], dict[str, Any]]) -> tuple[tuple[str, ...], dict[str, Any]]:
        key = (
            content_revision(cnhubert_path),
            content_revision(bert_path),
            content_revision(sv_path),
            device,
            dtype,
        )
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                entry = _Entry(factory())
                self._entries[key] = entry
            entry.active += 1
            return key, entry.value

    def release(self, key: tuple[str, ...] | None) -> None:
        if key is None:
            return
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return
            entry.active -= 1
            if entry.active > 0:
                return
            self._entries.pop(key, None)
        for resource in entry.value.values():
            close = getattr(resource, "close", None)
            if callable(close):
                close()
