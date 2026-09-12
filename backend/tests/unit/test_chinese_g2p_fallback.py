from __future__ import annotations

import builtins
import importlib
import sys
import types
from pathlib import Path

import pytest


def test_clean_text_falls_back_to_pypinyin_when_g2pw_init_fails(monkeypatch):
    project_root = Path(__file__).resolve().parents[3]
    gpt_sovits_root = str(project_root / "GPT_SoVITS")
    monkeypatch.syspath_prepend(gpt_sovits_root)

    monkeypatch.delitem(sys.modules, "text.chinese2", raising=False)
    monkeypatch.delitem(sys.modules, "text.g2pw", raising=False)

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

    monkeypatch.delitem(sys.modules, "text.chinese2", raising=False)
    monkeypatch.delitem(sys.modules, "text.g2pw", raising=False)

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


def test_importing_chinese_frontend_does_not_initialize_g2pw(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[3] / "GPT_SoVITS"))
    monkeypatch.setenv("is_g2pw", "true")
    monkeypatch.delitem(sys.modules, "text.chinese2", raising=False)
    attempts = []
    fake_g2pw = types.ModuleType("text.g2pw")

    def unexpected_initialization(**kwargs):
        attempts.append(kwargs)
        raise AssertionError("Import must not load pronunciation models")

    fake_g2pw.G2PWPinyin = unexpected_initialization
    monkeypatch.setitem(sys.modules, "text.g2pw", fake_g2pw)
    frontend = importlib.import_module("text.chinese2")
    assert frontend.g2pw is None
    assert attempts == []


@pytest.mark.parametrize("text", ["今天。", "今天￥。"])
def test_explicit_converter_bypasses_default_fallback_and_handles_specials(monkeypatch, text):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[3] / "GPT_SoVITS"))
    chinese = importlib.import_module("text.chinese2")
    from pypinyin import lazy_pinyin
    from text.cleaner import clean_text

    calls = []

    class Converter:
        def lazy_pinyin(self, value, **kwargs):
            calls.append(value)
            return lazy_pinyin(value, **kwargs)

    def unexpected_default():
        raise AssertionError("An explicit converter must not use the default fallback")

    monkeypatch.setattr(chinese, "_get_default_g2pw", unexpected_default)
    monkeypatch.setattr(chinese, "is_g2pw", False)
    phones, word2ph, normalized = clean_text(text, "zh", "v2", pinyin_converter=Converter())
    assert calls
    assert len(phones) == sum(word2ph)
    assert len(normalized) == len(word2ph)
    if "￥" in text:
        assert "SP2" in phones
