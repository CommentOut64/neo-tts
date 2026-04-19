from __future__ import annotations

import builtins
from pathlib import Path
import sys
import types


def test_clean_text_falls_back_to_pypinyin_when_g2pw_init_fails(monkeypatch):
    project_root = Path(__file__).resolve().parents[3]
    gpt_sovits_root = str(project_root / "GPT_SoVITS")
    monkeypatch.syspath_prepend(gpt_sovits_root)

    sys.modules.pop("text.chinese2", None)
    sys.modules.pop("text.g2pw", None)

    fake_g2pw = types.ModuleType("text.g2pw")

    class BrokenG2PWPinyin:
        def __init__(self, *args, **kwargs):
            raise RuntimeError("simulated g2pw init failure")

    fake_g2pw.G2PWPinyin = BrokenG2PWPinyin
    fake_g2pw.correct_pronunciation = lambda word, pinyin: pinyin
    monkeypatch.setitem(sys.modules, "text.g2pw", fake_g2pw)

    from text.cleaner import clean_text

    phones, word2ph, norm_text = clean_text("今天是个好日子。", "zh", "v2")

    assert phones
    assert word2ph
    assert len(phones) == sum(word2ph)
    assert len(norm_text) == len(word2ph)


def test_clean_text_skips_g2pw_import_in_packaged_runtime(monkeypatch):
    project_root = Path(__file__).resolve().parents[3]
    gpt_sovits_root = str(project_root / "GPT_SoVITS")
    monkeypatch.syspath_prepend(gpt_sovits_root)
    monkeypatch.setenv("NEO_TTS_DISTRIBUTION_KIND", "portable")

    sys.modules.pop("text.chinese2", None)
    sys.modules.pop("text.g2pw", None)

    import_attempts: list[str] = []
    original_import = builtins.__import__

    def tracking_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "text.g2pw":
            import_attempts.append(name)
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", tracking_import)

    from text.cleaner import clean_text

    phones, word2ph, norm_text = clean_text("今天是个好日子。", "zh", "v2")

    assert phones
    assert word2ph
    assert len(phones) == sum(word2ph)
    assert len(norm_text) == len(word2ph)
    assert import_attempts == []
