import pytest

from backend.app.inference.text_processing import (
    normalize_whitespace,
    split_text_segments,
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
