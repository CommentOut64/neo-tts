from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from backend.app.inference.text_processing import normalize_whitespace
from backend.app.text.language_profiles import LanguageProfile


TerminalSource = Literal["original", "synthetic"]

_TERMINAL_GROUPS: dict[str, str] = {
    ".": "period",
    "。": "period",
    "?": "question",
    "？": "question",
    "!": "exclamation",
    "！": "exclamation",
    "...": "ellipsis",
    "......": "ellipsis",
    "…": "ellipsis",
    "……": "ellipsis",
    "?!": "combo",
    "!?": "combo",
    "？！": "combo",
    "！？": "combo",
}
_TERMINALS_BY_LENGTH = sorted(_TERMINAL_GROUPS, key=len, reverse=True)
_CLOSER_CHARACTERS = frozenset(('”', "’", '"', ")", "）", "]", "】", ">", "》", "」", "』", "〉", "〕", "｝", "｠"))
TERMINAL_STRINGS = tuple(_TERMINALS_BY_LENGTH)
CLOSER_CHARACTERS = _CLOSER_CHARACTERS
_ZH_RENDER_MAP = {
    ".": "。",
    "。": "。",
    "?": "?",
    "？": "？",
    "!": "!",
    "！": "！",
    "...": "…",
    "......": "……",
    "…": "…",
    "……": "……",
    "?!": "?!",
    "!?": "!?",
    "？！": "？！",
    "！？": "！？",
}
_JA_RENDER_MAP = {
    ".": "。",
    "。": "。",
    "?": "？",
    "？": "？",
    "!": "！",
    "！": "！",
    "...": "…",
    "......": "…",
    "…": "…",
    "……": "…",
    "?!": "？！",
    "!?": "？！",
    "？！": "？！",
    "！？": "？！",
}
_EN_RENDER_MAP = {
    ".": ".",
    "。": ".",
    "?": "?",
    "？": "?",
    "!": "!",
    "！": "!",
    "...": "...",
    "......": "...",
    "…": "...",
    "……": "...",
    "?!": "?!",
    "!?": "!?",
    "？！": "?!",
    "！？": "!?",
}


@dataclass(frozen=True)
class TerminalCapsule:
    terminal_raw: str
    terminal_closer_suffix: str
    terminal_source: TerminalSource

    def __post_init__(self) -> None:
        if self.terminal_source == "original" and not self.terminal_raw:
            raise ValueError("Original terminal capsule requires non-empty terminal_raw.")
        if self.terminal_source == "synthetic" and self.terminal_raw:
            raise ValueError("Synthetic terminal capsule must not carry original terminal_raw.")


@dataclass(frozen=True)
class SegmentTextState:
    stem: str
    terminal_raw: str
    terminal_closer_suffix: str
    terminal_source: TerminalSource

    def __post_init__(self) -> None:
        normalized_stem = self.stem.rstrip()
        if not normalized_stem:
            raise ValueError("Segment text must contain readable speech content.")
        object.__setattr__(self, "stem", normalized_stem)
        TerminalCapsule(
            terminal_raw=self.terminal_raw,
            terminal_closer_suffix=self.terminal_closer_suffix,
            terminal_source=self.terminal_source,
        )

    @property
    def capsule(self) -> TerminalCapsule:
        return TerminalCapsule(
            terminal_raw=self.terminal_raw,
            terminal_closer_suffix=self.terminal_closer_suffix,
            terminal_source=self.terminal_source,
        )


def parse_terminal_capsule(text: str) -> SegmentTextState:
    normalized = normalize_whitespace(text)
    if not normalized:
        raise ValueError("Segment text must not be empty.")

    trimmed = normalized.rstrip()
    base_text, closer_suffix = _split_terminal_closer_suffix(trimmed)
    terminal_raw = _match_terminal_raw(base_text)
    if terminal_raw is None:
        stem = base_text.rstrip()
        capsule = TerminalCapsule(
            terminal_raw="",
            terminal_closer_suffix=closer_suffix,
            terminal_source="synthetic",
        )
    else:
        stem = base_text[: -len(terminal_raw)].rstrip()
        capsule = TerminalCapsule(
            terminal_raw=terminal_raw,
            terminal_closer_suffix=closer_suffix,
            terminal_source="original",
        )
    return SegmentTextState(
        stem=stem,
        terminal_raw=capsule.terminal_raw,
        terminal_closer_suffix=capsule.terminal_closer_suffix,
        terminal_source=capsule.terminal_source,
    )


def build_display_text(stem: str, capsule: TerminalCapsule, profile: LanguageProfile) -> str:
    return f"{stem}{_resolve_display_terminal(capsule, profile)}{capsule.terminal_closer_suffix}"


def build_render_text(stem: str, capsule: TerminalCapsule, profile: LanguageProfile) -> str:
    return f"{stem}{_resolve_render_terminal(capsule, profile)}"


def build_display_text_from_state(state: SegmentTextState, profile: LanguageProfile) -> str:
    return build_display_text(state.stem, state.capsule, profile)


def build_render_text_from_state(state: SegmentTextState, profile: LanguageProfile) -> str:
    return build_render_text(state.stem, state.capsule, profile)


def derive_terminal_kind(terminal_raw: str) -> str:
    try:
        return _TERMINAL_GROUPS[terminal_raw]
    except KeyError as exc:
        raise ValueError(f"Unsupported terminal_raw: {terminal_raw!r}") from exc


def _split_terminal_closer_suffix(text: str) -> tuple[str, str]:
    index = len(text) - 1
    closer_chars: list[str] = []
    while index >= 0:
        current_char = text[index]
        if current_char.isspace():
            index -= 1
            continue
        if current_char not in _CLOSER_CHARACTERS:
            break
        closer_chars.append(current_char)
        index -= 1
    closer_suffix = "".join(reversed(closer_chars))
    return text[: index + 1].rstrip(), closer_suffix


def _match_terminal_raw(text: str) -> str | None:
    stripped = text.rstrip()
    for candidate in _TERMINALS_BY_LENGTH:
        if stripped.endswith(candidate):
            return candidate
    return None


def _resolve_display_terminal(capsule: TerminalCapsule, profile: LanguageProfile) -> str:
    if capsule.terminal_source == "synthetic":
        return profile["default_display_period"]
    return capsule.terminal_raw


def _resolve_render_terminal(capsule: TerminalCapsule, profile: LanguageProfile) -> str:
    if capsule.terminal_source == "synthetic":
        return profile["default_render_period"]

    language = profile["language"]
    if language == "zh":
        return _ZH_RENDER_MAP[capsule.terminal_raw]
    if language == "ja":
        return _JA_RENDER_MAP[capsule.terminal_raw]
    if language == "en":
        return _EN_RENDER_MAP[capsule.terminal_raw]
    return _ZH_RENDER_MAP[capsule.terminal_raw]
