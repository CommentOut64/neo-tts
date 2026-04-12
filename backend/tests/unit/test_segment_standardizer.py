import backend.app.text.segment_standardizer as segment_standardizer
from backend.app.text.segment_standardizer import (
    split_text_segments_with_terminal_capsules,
    standardize_segment_text,
    standardize_segment_texts,
)


def test_standardize_segment_text_auto_detects_en_for_single_segment():
    result = standardize_segment_text("Hello world!", "auto")

    assert result.raw_text == "Hello world!"
    assert result.normalized_text == "Hello world。"
    assert result.detected_language == "en"
    assert result.inference_exclusion_reason == "none"


def test_standardize_segment_text_marks_explicit_unsupported_language():
    result = standardize_segment_text("안녕하세요!", "ko")

    assert result.detected_language == "unknown"
    assert result.inference_exclusion_reason == "unsupported_language"


def test_standardize_segment_text_auto_uses_lang_segmenter(monkeypatch):
    calls: list[tuple[str, str]] = []

    class FakeLangSegmenter:
        @staticmethod
        def getTexts(text: str, default_lang: str = ""):
            calls.append((text, default_lang))
            return [{"lang": "en", "text": text}]

    monkeypatch.setattr(segment_standardizer, "_get_lang_segmenter", lambda: FakeLangSegmenter)

    result = standardize_segment_text("Hello world!", "auto")

    assert result.detected_language == "en"
    assert calls == [("Hello world", "")]


def test_standardize_segment_texts_auto_uses_lang_segmenter_for_batch_document_language(monkeypatch):
    calls: list[tuple[str, str]] = []

    class FakeLangSegmenter:
        @staticmethod
        def getTexts(text: str, default_lang: str = ""):
            calls.append((text, default_lang))
            if "Second" in text:
                return [{"lang": "en", "text": text}]
            return [{"lang": "zh", "text": text}]

    monkeypatch.setattr(segment_standardizer, "_get_lang_segmenter", lambda: FakeLangSegmenter)

    batch = standardize_segment_texts(["第一句？！", "Second sentence!"], "auto")

    assert batch.resolved_document_language == "unknown"
    assert [segment.detected_language for segment in batch.segments] == ["zh", "en"]
    assert calls == [("第一句？！", ""), ("Second sentence!", "")]


def test_standardize_segment_text_auto_marks_mixed_segment_as_unknown(monkeypatch):
    class FakeLangSegmenter:
        @staticmethod
        def getTexts(text: str, default_lang: str = ""):
            return [
                {"lang": "zh", "text": "今天开始 "},
                {"lang": "en", "text": "deploy API server"},
            ]

    monkeypatch.setattr(segment_standardizer, "_get_lang_segmenter", lambda: FakeLangSegmenter)

    result = standardize_segment_text("今天开始 deploy API server。", "auto")

    assert result.detected_language == "unknown"
    assert result.inference_exclusion_reason == "language_unresolved"


def test_standardize_segment_text_auto_marks_real_mixed_script_segment_as_unknown():
    result = standardize_segment_text("版本号是 v0.0.3，ready to ship 吗？", "auto")

    assert result.detected_language == "unknown"
    assert result.inference_exclusion_reason == "language_unresolved"


def test_split_text_segments_with_terminal_capsules_skips_decimal_dot_and_keeps_english_period():
    segments = split_text_segments_with_terminal_capsules("The price is 3.14. Next sentence.")

    assert segments == [
        "The price is 3.14.",
        "Next sentence.",
    ]
