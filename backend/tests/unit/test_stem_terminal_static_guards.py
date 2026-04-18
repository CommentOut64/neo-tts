from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]


def _read(relative_path: str) -> str:
    return (REPO_ROOT / relative_path).read_text(encoding="utf-8")


def test_terminal_capsule_core_no_longer_exposes_canonical_text():
    source = _read("backend/app/text/terminal_capsule.py")

    assert "canonical_text" not in source
    assert "build_canonical_text" not in source


def test_segment_standardizer_no_longer_uses_fixed_period_shortcut():
    source = _read("backend/app/text/segment_standardizer.py")

    assert 'normalized.endswith("。")' not in source
    assert "parsed.canonical_text" not in source


def test_edit_session_schema_no_longer_keeps_legacy_segment_text_upgrade_helpers():
    source = _read("backend/app/schemas/edit_session.py")

    assert "_upgrade_legacy_segment_payload" not in source
    assert "_upgrade_legacy_raw_text_patch" not in source
