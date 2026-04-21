from pathlib import Path

import pytest

from backend.app.inference.asset_fingerprint import fingerprint_file, fingerprint_text


def test_fingerprint_file_changes_when_file_metadata_changes(tmp_path: Path):
    target = tmp_path / "demo.ckpt"
    target.write_bytes(b"first")

    first = fingerprint_file(target)

    target.write_bytes(b"second")

    second = fingerprint_file(target)

    assert first != second


def test_fingerprint_file_requires_existing_file(tmp_path: Path):
    missing = tmp_path / "missing.ckpt"

    with pytest.raises(FileNotFoundError):
        fingerprint_file(missing)


def test_fingerprint_text_changes_when_text_changes():
    assert fingerprint_text("参考文本一") != fingerprint_text("参考文本二")
