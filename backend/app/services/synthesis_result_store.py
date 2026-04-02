from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from uuid import uuid4


_RESULT_ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")


@dataclass(frozen=True)
class SavedSynthesisResult:
    result_id: str
    file_path: Path


class SynthesisResultStore:
    def __init__(self, *, project_root: Path, results_dir: Path) -> None:
        self._project_root = project_root
        self._results_dir = self._resolve_path(results_dir)
        self._results_dir.mkdir(parents=True, exist_ok=True)

    def save_wav(self, wav_bytes: bytes) -> SavedSynthesisResult:
        result_id = uuid4().hex
        path = self._build_file_path(result_id)
        path.write_bytes(wav_bytes)
        return SavedSynthesisResult(result_id=result_id, file_path=path)

    def delete_result(self, result_id: str) -> bool:
        path = self._build_file_path(result_id)
        if not path.exists():
            return False
        path.unlink()
        return True

    def clear_all_results(self) -> int:
        removed = 0
        for file in self._results_dir.glob("*.wav"):
            file.unlink()
            removed += 1
        return removed

    def _build_file_path(self, result_id: str) -> Path:
        if not _RESULT_ID_PATTERN.fullmatch(result_id):
            raise ValueError("Invalid result_id format.")
        return self._results_dir / f"{result_id}.wav"

    def _resolve_path(self, value: Path) -> Path:
        if value.is_absolute():
            return value
        return (self._project_root / value).resolve()
