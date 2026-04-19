import sys
from types import ModuleType

import pytest
import torch

from backend.app.inference.text_processing import (
    build_phones_and_bert_features,
    normalize_whitespace,
    split_text_segments,
    split_text_segments_raw_strong_punctuation,
    split_text_segments_zh_period,
    split_text_segments_official,
)


def test_normalize_whitespace_collapses_multiple_spaces():
    assert normalize_whitespace("hello   world") == "hello world"
    assert normalize_whitespace("  a   b  ") == "a b"


def test_split_text_segments_keeps_punctuation_and_merges_short_sentences():
    text = "你好。你好吗？很好！"

    segments = split_text_segments(text, min_segment_length=10)

    assert segments == ["你好。你好吗？", "很好！"]


def test_split_text_segments_returns_empty_for_blank_input():
    assert split_text_segments("   \n  ") == []


def test_split_text_segments_official_cut5_merges_short_chunks():
    text = "你好，我是小明。你好，我是小红！"
    segments = split_text_segments_official(text, text_split_method="cut5")
    assert segments == ["你好，我是小明。", "你好，我是小红！"]


def test_split_text_segments_official_supports_cut0():
    text = "第一句。第二句。"
    segments = split_text_segments_official(text, text_split_method="cut0")
    assert segments == ["第一句。第二句。"]


def test_split_text_segments_official_rejects_unknown_method():
    with pytest.raises(ValueError, match="Unsupported text_split_method"):
        split_text_segments_official("你好。", text_split_method="cut999")


def test_split_text_segments_zh_period_only_splits_on_chinese_period():
    text = "第一句，带逗号。第二句，还有逗号。第三句，没有别的句号"

    segments = split_text_segments_zh_period(text)

    assert segments == [
        "第一句，带逗号。",
        "第二句，还有逗号。",
        "第三句，没有别的句号",
    ]


def test_split_text_segments_zh_period_supports_english_period_and_skips_decimal_dot():
    text = "The price is 3.14.\nNext sentence."

    segments = split_text_segments_zh_period(text)

    assert segments == [
        "The price is 3.14.",
        "\nNext sentence.",
    ]


def test_split_text_segments_zh_period_keeps_trailing_closer_with_previous_segment():
    text = "第一句。”\n\n第二句。"

    segments = split_text_segments_zh_period(text)

    assert segments == [
        "第一句。”",
        "\n\n第二句。",
    ]


def test_split_text_segments_zh_period_does_not_create_closer_only_tail_segment():
    text = "第一句。”"

    segments = split_text_segments_zh_period(text)

    assert segments == ["第一句。”"]


def test_split_text_segments_raw_strong_punctuation_keeps_trailing_closer_with_previous_segment():
    text = 'Hello!”Next sentence.'

    segments = split_text_segments_raw_strong_punctuation(text)

    assert segments == [
        "Hello!”",
        "Next sentence.",
    ]


def test_build_phones_and_bert_features_logs_stage_breakdown(monkeypatch):
    logged: list[tuple[str, tuple]] = []

    class _FakeLogger:
        def info(self, message, *args):
            logged.append(("info", (message, *args)))

        def debug(self, message, *args):
            logged.append(("debug", (message, *args)))

    fake_root = ModuleType("GPT_SoVITS")
    fake_text_package = ModuleType("GPT_SoVITS.text")
    fake_lang_segmenter_module = ModuleType("GPT_SoVITS.text.LangSegmenter")
    fake_cleaner_module = ModuleType("GPT_SoVITS.text.cleaner")

    class _FakeLangSegmenter:
        @staticmethod
        def getTexts(text, default_lang=None):
            del default_lang
            return [{"lang": "en", "text": text}]

    fake_lang_segmenter_module.LangSegmenter = _FakeLangSegmenter
    fake_text_package.cleaned_text_to_sequence = lambda phones, version: [len(phones), len(version)]
    fake_cleaner_module.clean_text = lambda text, lang, version: (["AA"], None, f"{text}:{lang}:{version}")
    fake_root.text = fake_text_package

    monkeypatch.setattr("backend.app.inference.text_processing.text_processing_logger", _FakeLogger())
    monkeypatch.setitem(sys.modules, "GPT_SoVITS", fake_root)
    monkeypatch.setitem(sys.modules, "GPT_SoVITS.text", fake_text_package)
    monkeypatch.setitem(sys.modules, "GPT_SoVITS.text.LangSegmenter", fake_lang_segmenter_module)
    monkeypatch.setitem(sys.modules, "GPT_SoVITS.text.cleaner", fake_cleaner_module)

    phones, bert, norm_text = build_phones_and_bert_features(
        text="Hello world",
        language="en",
        version="v2",
        tokenizer=lambda *args, **kwargs: None,
        bert_model=None,
        device="cpu",
        is_half=False,
        return_norm_text=True,
    )

    assert phones == [1, 2]
    assert tuple(bert.shape) == (1024, 2)
    assert norm_text == "Hello world:en:v2"
    info_entries = [entry[1] for entry in logged if entry[0] == "info"]
    assert any(
        len(entry) == 5
        and entry[0] == "phones_and_bert stage={} language={} elapsed_ms={:.2f} detail={}"
        and entry[1] == "module_imports"
        and entry[2] == "en"
        for entry in info_entries
    )
    assert any(
        len(entry) == 5
        and entry[0] == "phones_and_bert stage={} language={} elapsed_ms={:.2f} detail={}"
        and entry[1] == "lang_segment"
        and entry[2] == "en"
        for entry in info_entries
    )
    assert any(
        len(entry) == 5
        and entry[0] == "phones_and_bert stage={} language={} elapsed_ms={:.2f} detail={}"
        and entry[1] == "clean_text"
        and entry[2] == "en"
        and "word2ph_len=none" in entry[4]
        for entry in info_entries
    )
    assert any(
        len(entry) == 5
        and entry[0] == "phones_and_bert stage={} language={} elapsed_ms={:.2f} detail={}"
        and entry[1] == "cleaned_text_to_sequence"
        and entry[2] == "en"
        for entry in info_entries
    )
    assert any(
        len(entry) == 5
        and entry[0] == "phones_and_bert stage={} language={} elapsed_ms={:.2f} detail={}"
        and entry[1] == "bert_features"
        and entry[2] == "en"
        and "mode=zeros" in entry[4]
        for entry in info_entries
    )


def test_build_phones_and_bert_features_reports_stage_before_clean_text(monkeypatch):
    stage_events: list[tuple[str, str, str]] = []

    fake_root = ModuleType("GPT_SoVITS")
    fake_text_package = ModuleType("GPT_SoVITS.text")
    fake_lang_segmenter_module = ModuleType("GPT_SoVITS.text.LangSegmenter")
    fake_cleaner_module = ModuleType("GPT_SoVITS.text.cleaner")

    class _FakeLangSegmenter:
        @staticmethod
        def getTexts(text, default_lang=None):
            del default_lang
            return [{"lang": "en", "text": text}]

    def _fake_clean_text(text, lang, version):
        assert stage_events[-1][0] == "clean_text"
        assert stage_events[-1][1] == "en"
        assert "chunk_index=0" in stage_events[-1][2]
        return ["AA"], None, f"{text}:{lang}:{version}"

    fake_lang_segmenter_module.LangSegmenter = _FakeLangSegmenter
    fake_text_package.cleaned_text_to_sequence = lambda phones, version: [len(phones), len(version)]
    fake_cleaner_module.clean_text = _fake_clean_text
    fake_root.text = fake_text_package

    monkeypatch.setitem(sys.modules, "GPT_SoVITS", fake_root)
    monkeypatch.setitem(sys.modules, "GPT_SoVITS.text", fake_text_package)
    monkeypatch.setitem(sys.modules, "GPT_SoVITS.text.LangSegmenter", fake_lang_segmenter_module)
    monkeypatch.setitem(sys.modules, "GPT_SoVITS.text.cleaner", fake_cleaner_module)

    build_phones_and_bert_features(
        text="Hello world",
        language="en",
        version="v2",
        tokenizer=lambda *args, **kwargs: None,
        bert_model=None,
        device="cpu",
        is_half=False,
        return_norm_text=True,
        stage_reporter=lambda stage, language, detail: stage_events.append((stage, language, detail)),
    )

    assert [stage for stage, _, _ in stage_events[:4]] == [
        "module_imports",
        "lang_segment",
        "clean_text",
        "cleaned_text_to_sequence",
    ]
