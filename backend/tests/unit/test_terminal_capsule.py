from backend.app.text.language_profiles import get_language_profile
from backend.app.text.terminal_capsule import (
    SegmentTextState,
    TerminalCapsule,
    build_display_text,
    build_display_text_from_state,
    build_render_text,
    build_render_text_from_state,
    derive_terminal_kind,
    parse_terminal_capsule,
)


def test_parse_terminal_capsule_preserves_original_combo_terminal_and_closer():
    parsed = parse_terminal_capsule('真的么？！ 」')

    assert parsed == SegmentTextState(
        stem="真的么",
        terminal_raw="？！",
        terminal_closer_suffix="」",
        terminal_source="original",
    )


def test_parse_terminal_capsule_marks_missing_terminal_as_synthetic():
    parsed = parse_terminal_capsule("Hello")

    assert parsed == SegmentTextState(
        stem="Hello",
        terminal_raw="",
        terminal_closer_suffix="",
        terminal_source="synthetic",
    )


def test_parse_terminal_capsule_returns_state_without_canonical_text():
    parsed = parse_terminal_capsule('真的么？！」')

    assert parsed.stem == "真的么"
    assert not hasattr(parsed, "canonical_text")
    assert build_display_text_from_state(parsed, get_language_profile("zh")) == '真的么？！」'


def test_parse_terminal_capsule_inserts_synthetic_period_before_closer():
    parsed = parse_terminal_capsule('你好”')

    assert parsed.stem == "你好"
    assert build_display_text_from_state(parsed, get_language_profile("zh")) == '你好。”'


def test_parse_terminal_capsule_recognizes_ascii_and_unicode_ellipsis_clusters():
    assert parse_terminal_capsule("Wait...").capsule.terminal_raw == "..."
    assert parse_terminal_capsule("Wait......").capsule.terminal_raw == "......"
    assert parse_terminal_capsule("等等……").capsule.terminal_raw == "……"
    assert parse_terminal_capsule("等等…").capsule.terminal_raw == "…"


def test_build_display_text_uses_language_default_for_synthetic_terminal():
    capsule = TerminalCapsule(
        terminal_raw="",
        terminal_closer_suffix="",
        terminal_source="synthetic",
    )

    assert build_display_text("你好", capsule, get_language_profile("zh")) == "你好。"
    assert build_display_text("こんにちは", capsule, get_language_profile("ja")) == "こんにちは。"
    assert build_display_text("Hello", capsule, get_language_profile("en")) == "Hello."
    assert build_display_text("Unknown", capsule, get_language_profile("unknown")) == "Unknown。"


def test_build_render_text_normalizes_terminal_by_language_profile():
    zh_profile = get_language_profile("zh")
    ja_profile = get_language_profile("ja")
    en_profile = get_language_profile("en")

    assert build_render_text("真的吗", TerminalCapsule("......", "", "original"), zh_profile) == "真的吗……"
    assert build_render_text("本当です", TerminalCapsule("?!", "", "original"), ja_profile) == "本当です？！"
    assert build_render_text("Really", TerminalCapsule("？！", "", "original"), en_profile) == "Really?!"


def test_build_render_text_drops_closer_suffix():
    text = build_render_text(
        "你好",
        TerminalCapsule("？", "”", "original"),
        get_language_profile("zh"),
    )

    assert text == "你好？"


def test_build_display_and_render_text_from_state_use_same_structured_source():
    state = SegmentTextState(
        stem="Hello",
        terminal_raw="",
        terminal_closer_suffix="",
        terminal_source="synthetic",
    )

    assert build_display_text_from_state(state, get_language_profile("en")) == "Hello."
    assert build_render_text_from_state(state, get_language_profile("en")) == "Hello."


def test_derive_terminal_kind_groups_supported_terminals():
    assert derive_terminal_kind(".") == "period"
    assert derive_terminal_kind("。") == "period"
    assert derive_terminal_kind("?") == "question"
    assert derive_terminal_kind("！") == "exclamation"
    assert derive_terminal_kind("...") == "ellipsis"
    assert derive_terminal_kind("......") == "ellipsis"
    assert derive_terminal_kind("？！") == "combo"
