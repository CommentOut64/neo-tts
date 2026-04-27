from __future__ import annotations

import hashlib
from pathlib import Path


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


def fingerprint_text(value: str) -> str:
    return hashlib.sha1(value.encode("utf-8")).hexdigest()
