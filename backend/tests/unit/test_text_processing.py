from backend.app.inference.text_processing import normalize_whitespace, split_text_segments


def test_normalize_whitespace_collapses_multiple_spaces():
    assert normalize_whitespace("hello   world") == "hello world"
    assert normalize_whitespace("  a   b  ") == "a b"


def test_split_text_segments_keeps_punctuation_and_merges_short_sentences():
    text = "你好。你好吗？很好！"

    segments = split_text_segments(text, min_segment_length=10)

    assert segments == ["你好。你好吗？", "很好！"]


def test_split_text_segments_returns_empty_for_blank_input():
    assert split_text_segments("   \n  ") == []
