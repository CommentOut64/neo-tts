from __future__ import annotations

from typing import Literal, TypedDict


SupportedLanguage = Literal["zh", "ja", "en"]
ResolvedLanguage = Literal["zh", "ja", "en", "unknown"]


class LanguageProfile(TypedDict):
    language: ResolvedLanguage
    default_display_period: str
    default_render_period: str
    default_render_question: str
    default_render_exclamation: str
    default_render_ellipsis: str
    preserve_combo_by_default: bool


_LANGUAGE_PROFILES: dict[ResolvedLanguage, LanguageProfile] = {
    "zh": {
        "language": "zh",
        "default_display_period": "。",
        "default_render_period": "。",
        "default_render_question": "？",
        "default_render_exclamation": "！",
        "default_render_ellipsis": "…",
        "preserve_combo_by_default": True,
    },
    "ja": {
        "language": "ja",
        "default_display_period": "。",
        "default_render_period": "。",
        "default_render_question": "？",
        "default_render_exclamation": "！",
        "default_render_ellipsis": "…",
        "preserve_combo_by_default": False,
    },
    "en": {
        "language": "en",
        "default_display_period": ".",
        "default_render_period": ".",
        "default_render_question": "?",
        "default_render_exclamation": "!",
        "default_render_ellipsis": "...",
        "preserve_combo_by_default": False,
    },
    "unknown": {
        "language": "unknown",
        "default_display_period": "。",
        "default_render_period": "。",
        "default_render_question": "？",
        "default_render_exclamation": "！",
        "default_render_ellipsis": "…",
        "preserve_combo_by_default": False,
    },
}


def get_language_profile(language: ResolvedLanguage | str) -> LanguageProfile:
    return _LANGUAGE_PROFILES.get(language, _LANGUAGE_PROFILES["unknown"])
