from __future__ import annotations

from pathlib import Path


def test_clean_text_does_not_prepend_comma_to_short_english_by_default(monkeypatch):
    project_root = Path(__file__).resolve().parents[3]
    monkeypatch.syspath_prepend(str(project_root / "GPT_SoVITS"))
    monkeypatch.delenv("GPT_SOVITS_PREPEND_COMMA_TO_SHORT_ENGLISH", raising=False)

    from text.cleaner import clean_text

    phones, _, _ = clean_text("A", "en", "v2")

    assert phones == ["EY1"]


def test_clean_text_can_prepend_comma_to_short_english_when_enabled(monkeypatch):
    project_root = Path(__file__).resolve().parents[3]
    monkeypatch.syspath_prepend(str(project_root / "GPT_SoVITS"))
    monkeypatch.setenv("GPT_SOVITS_PREPEND_COMMA_TO_SHORT_ENGLISH", "1")

    from text.cleaner import clean_text

    phones, _, _ = clean_text("A", "en", "v2")

    assert phones == [",", "EY1"]
