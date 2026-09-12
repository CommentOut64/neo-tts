from __future__ import annotations

import string
from dataclasses import dataclass
from typing import Literal

from runtime.gsv.language import LanguageResolutionService

from backend.app.inference.text_processing import is_decimal_dot_at, normalize_whitespace
from backend.app.text.language_profiles import ResolvedLanguage, get_language_profile
from backend.app.text.terminal_capsule import (
    CLOSER_CHARACTERS,
    SegmentTextState,
    TERMINAL_STRINGS,
    TerminalCapsule,
    build_display_text_from_state,
    build_render_text_from_state,
    parse_terminal_capsule,
)


SHORT_NATURALNESS_RISK = "short_naturalness_risk"
LONG_EDIT_COST_RISK = "long_edit_cost_risk"
_NON_SPEECH_CHARACTERS = set(string.punctuation) | set("，。！？；：、（）【】《》“”‘’…·—")
_APPROX_CHARS_PER_SECOND = 5.0
_SHORT_SEGMENT_SECONDS = 3.0
_LONG_SEGMENT_SECONDS = 30.0
_SUPPORTED_LANGUAGES = {"zh", "ja", "en"}
_language_resolver = LanguageResolutionService()
_FORCED_NEWLINE_TRAILING_PUNCTUATION = frozenset("，,、；;：:。．.!！？?…—")
_FORCED_NEWLINE_LEADING_PUNCTUATION = (
    _FORCED_NEWLINE_TRAILING_PUNCTUATION | CLOSER_CHARACTERS
)
LanguageDetectionSource = Literal["explicit", "auto"]


@dataclass(frozen=True)
class SegmentStandardizationResult:
    stem: str
    display_text: str
    render_text: str
    terminal_raw: str
    terminal_closer_suffix: str
    terminal_source: str
    detected_language: ResolvedLanguage
    inference_exclusion_reason: str
    risk_flags: list[str]

    @property
    def capsule(self) -> TerminalCapsule:
        return TerminalCapsule(
            terminal_raw=self.terminal_raw,
            terminal_closer_suffix=self.terminal_closer_suffix,
            terminal_source=self.terminal_source,
        )

    @property
    def state(self) -> SegmentTextState:
        return SegmentTextState(
            stem=self.stem,
            terminal_raw=self.terminal_raw,
            terminal_closer_suffix=self.terminal_closer_suffix,
            terminal_source=self.terminal_source,
        )

    @property
    def raw_text(self) -> str:
        return self.display_text

    @property
    def normalized_text(self) -> str:
        return _build_legacy_normalized_text(self.stem)


@dataclass(frozen=True)
class SegmentLanguageMeta:
    detected_language: ResolvedLanguage
    inference_exclusion_reason: str


@dataclass(frozen=True)
class StandardizationBatchResult:
    segments: list[SegmentStandardizationResult]
    resolved_document_language: ResolvedLanguage
    language_detection_source: LanguageDetectionSource


@dataclass(frozen=True)
class StandardizationPreviewSegmentResult:
    order_key: int
    stem: str
    display_text: str
    terminal_raw: str
    terminal_closer_suffix: str
    terminal_source: str
    detected_language: ResolvedLanguage | None
    inference_exclusion_reason: str | None
    warnings: list[str]


@dataclass(frozen=True)
class StandardizationPreviewResult:
    analysis_stage: Literal["light", "complete"]
    document_char_count: int
    total_segments: int
    next_cursor: int | None
    resolved_document_language: ResolvedLanguage | None
    language_detection_source: LanguageDetectionSource | None
    warnings: list[str]
    segments: list[StandardizationPreviewSegmentResult]


def standardize_segment_text(
    raw_text: str,
    text_language: str,
    *,
    detected_language: ResolvedLanguage | None = None,
    inference_exclusion_reason: str | None = None,
) -> SegmentStandardizationResult:
    normalized_input = normalize_whitespace(raw_text)
    state = parse_terminal_capsule(normalized_input)
    return standardize_segment_text_state(
        state,
        text_language,
        detected_language=detected_language,
        inference_exclusion_reason=inference_exclusion_reason,
    )


def standardize_segment_text_state(
    state: SegmentTextState,
    text_language: str,
    *,
    detected_language: ResolvedLanguage | None = None,
    inference_exclusion_reason: str | None = None,
) -> SegmentStandardizationResult:
    if detected_language is None or inference_exclusion_reason is None:
        language_meta = _resolve_single_segment_language_meta(state.stem, text_language)
        detected_language = language_meta.detected_language
        inference_exclusion_reason = language_meta.inference_exclusion_reason
    profile = get_language_profile(detected_language if detected_language != "unknown" else "unknown")
    display_text = build_display_text_from_state(state, profile)
    render_text = build_render_text_from_state(state, profile)
    return SegmentStandardizationResult(
        stem=state.stem,
        display_text=display_text,
        render_text=render_text,
        terminal_raw=state.terminal_raw,
        terminal_closer_suffix=state.terminal_closer_suffix,
        terminal_source=state.terminal_source,
        detected_language=detected_language,
        inference_exclusion_reason=inference_exclusion_reason,
        risk_flags=_derive_risk_flags(state.stem),
    )


def standardize_segment_texts(raw_segments: list[str], text_language: str) -> StandardizationBatchResult:
    segment_language_meta, resolved_document_language, detection_source = _resolve_batch_language_meta(
        raw_segments,
        text_language,
    )
    standardized_segments = [
        standardize_segment_text(
            raw_text,
            text_language,
            detected_language=language_meta.detected_language,
            inference_exclusion_reason=language_meta.inference_exclusion_reason,
        )
        for raw_text, language_meta in zip(raw_segments, segment_language_meta, strict=True)
    ]
    return StandardizationBatchResult(
        segments=standardized_segments,
        resolved_document_language=resolved_document_language,
        language_detection_source=detection_source,
    )


def build_standardization_preview(
    *,
    raw_text: str,
    text_language: str,
    segment_limit: int,
    cursor: int | None,
    include_language_analysis: bool,
) -> StandardizationPreviewResult:
    normalized_input = raw_text.strip("\n")
    segments = split_text_segments_with_terminal_capsules(normalized_input)
    if not segments:
        raise ValueError("请输入有效文本")

    offset = cursor or 0
    if offset < 0:
        raise ValueError("cursor must be >= 0")
    if offset > len(segments):
        raise ValueError("cursor out of range")

    if include_language_analysis:
        batch = standardize_segment_texts(segments, text_language)
        resolved_document_language: ResolvedLanguage | None = batch.resolved_document_language
        language_detection_source: LanguageDetectionSource | None = batch.language_detection_source
        standardized_segments = batch.segments
        analysis_stage: Literal["light", "complete"] = "complete"
    else:
        standardized_segments = [standardize_segment_text(raw_segment, "unknown") for raw_segment in segments]
        resolved_document_language = None
        language_detection_source = None
        analysis_stage = "light"

    page = standardized_segments[offset:offset + segment_limit]
    next_cursor = offset + len(page)
    if next_cursor >= len(standardized_segments):
        next_cursor = None

    return StandardizationPreviewResult(
        analysis_stage=analysis_stage,
        document_char_count=len(normalize_whitespace(normalized_input)),
        total_segments=len(standardized_segments),
        next_cursor=next_cursor,
        resolved_document_language=resolved_document_language,
        language_detection_source=language_detection_source,
        warnings=[],
        segments=[
            StandardizationPreviewSegmentResult(
                order_key=offset + index,
                stem=segment.stem,
                display_text=segment.display_text,
                terminal_raw=segment.terminal_raw,
                terminal_closer_suffix=segment.terminal_closer_suffix,
                terminal_source=segment.terminal_source,
                detected_language=segment.detected_language if include_language_analysis else None,
                inference_exclusion_reason=segment.inference_exclusion_reason if include_language_analysis else None,
                warnings=list(segment.risk_flags),
            )
            for index, segment in enumerate(page, start=1)
        ],
    )


def build_segment_display_text(
    *,
    stem: str | None = None,
    raw_text: str | None = None,
    normalized_text: str | None = None,
    text_language: str,
    terminal_raw: str,
    terminal_closer_suffix: str,
    terminal_source: str,
) -> str:
    del normalized_text
    state = _resolve_segment_text_state(
        stem=stem,
        raw_text=raw_text,
        terminal_raw=terminal_raw,
        terminal_closer_suffix=terminal_closer_suffix,
        terminal_source=terminal_source,
    )
    profile = get_language_profile(_profile_language(text_language))
    return build_display_text_from_state(state, profile)


def build_segment_render_text(
    *,
    stem: str | None = None,
    raw_text: str | None = None,
    normalized_text: str | None = None,
    text_language: str,
    terminal_raw: str,
    terminal_closer_suffix: str,
    terminal_source: str,
) -> str:
    del normalized_text
    state = _resolve_segment_text_state(
        stem=stem,
        raw_text=raw_text,
        terminal_raw=terminal_raw,
        terminal_closer_suffix=terminal_closer_suffix,
        terminal_source=terminal_source,
    )
    profile = get_language_profile(_profile_language(text_language))
    return build_render_text_from_state(state, profile)


def extract_segment_stem(
    *,
    stem: str | None = None,
    raw_text: str | None = None,
    normalized_text: str | None = None,
    terminal_raw: str | None = None,
    terminal_closer_suffix: str | None = None,
    terminal_source: str | None = None,
) -> str:
    del normalized_text
    return _resolve_segment_text_state(
        stem=stem,
        raw_text=raw_text,
        terminal_raw=terminal_raw,
        terminal_closer_suffix=terminal_closer_suffix,
        terminal_source=terminal_source,
    ).stem


def split_text_segments_with_terminal_capsules(raw_text: str) -> list[str]:
    normalized = raw_text.strip("\n")
    if not normalized:
        return []

    segments: list[str] = []
    start = 0
    index = 0
    while index < len(normalized):
        current_char = normalized[index]
        if current_char == "\n":
            _append_forced_newline_segment(segments, normalized[start:index])
            start = _consume_forced_newline_leading_punctuation(normalized, index + 1)
            index = start
            continue

        terminal = _match_terminal_at(normalized, index)
        if terminal is None:
            index += 1
            continue

        end = index + len(terminal)
        cursor = end
        while True:
            whitespace_cursor = cursor
            while whitespace_cursor < len(normalized) and normalized[whitespace_cursor].isspace() and normalized[whitespace_cursor] != "\n":
                whitespace_cursor += 1
            if whitespace_cursor < len(normalized) and normalized[whitespace_cursor] in CLOSER_CHARACTERS:
                cursor = whitespace_cursor + 1
                end = cursor
                continue
            break
        _append_segment_slice(segments, normalized[start:end])
        start = end
        index = end

    _append_segment_slice(segments, normalized[start:])
    return segments


def _append_forced_newline_segment(segments: list[str], text: str) -> None:
    normalized = normalize_whitespace(text.replace("\n", " "))
    if not normalized:
        return

    state = parse_terminal_capsule(normalized)
    stem = state.stem.rstrip("".join(_FORCED_NEWLINE_TRAILING_PUNCTUATION)).rstrip()
    if not stem:
        return

    segments.append(f"{stem}{state.terminal_closer_suffix}")


def _consume_forced_newline_leading_punctuation(text: str, start_index: int) -> int:
    cursor = start_index
    while cursor < len(text):
        current_char = text[cursor]
        if current_char.isspace() and current_char != "\n":
            cursor += 1
            continue
        if current_char in _FORCED_NEWLINE_LEADING_PUNCTUATION:
            cursor += 1
            continue
        break
    return cursor


def _append_segment_slice(segments: list[str], text: str) -> None:
    normalized = normalize_whitespace(text.replace("\n", " "))
    if normalized:
        segments.append(normalized)


def _match_terminal_at(text: str, index: int) -> str | None:
    for terminal in TERMINAL_STRINGS:
        if terminal == "." and is_decimal_dot_at(text, index):
            continue
        if text.startswith(terminal, index):
            return terminal
    return None


def _resolve_single_segment_language_meta(text: str, text_language: str) -> SegmentLanguageMeta:
    language = text_language.lower()
    if language not in _SUPPORTED_LANGUAGES | {"auto", "mixed"}:
        reason = "language_unresolved" if language in {"unknown", ""} else "unsupported_language"
        return SegmentLanguageMeta(detected_language="unknown", inference_exclusion_reason=reason)
    if not text.strip():
        return SegmentLanguageMeta(detected_language="unknown", inference_exclusion_reason="language_unresolved")
    resolution = _language_resolver.resolve(language, text)
    supported = all(span.language in _SUPPORTED_LANGUAGES for span in resolution.spans)
    detected = resolution.mode if supported else "unknown"
    return SegmentLanguageMeta(
        detected_language=detected,
        inference_exclusion_reason="none" if supported else "language_unresolved",
    )


def _resolve_batch_language_meta(
    raw_segments: list[str],
    text_language: str,
) -> tuple[list[SegmentLanguageMeta], ResolvedLanguage, LanguageDetectionSource]:
    metadata = [_resolve_single_segment_language_meta(text, text_language) for text in raw_segments]
    resolved = _resolve_document_language([item.detected_language for item in metadata])
    return metadata, resolved, "auto" if text_language.lower() in {"auto", "mixed"} else "explicit"


def _resolve_document_language(detected_languages: list[ResolvedLanguage]) -> ResolvedLanguage:
    known = {language for language in detected_languages if language != "unknown"}
    if not known:
        return "unknown"
    return "mixed" if len(known) > 1 or "mixed" in known else next(iter(known))


def _profile_language(text_language: str) -> ResolvedLanguage:
    language = text_language.lower()
    if language in _SUPPORTED_LANGUAGES:
        return language
    return "unknown"


def _resolve_segment_text_state(
    *,
    stem: str | None,
    raw_text: str | None,
    terminal_raw: str | None,
    terminal_closer_suffix: str | None,
    terminal_source: str | None,
) -> SegmentTextState:
    if stem is None:
        if raw_text is None:
            raise ValueError("Either stem or raw_text must be provided.")
        stem = parse_terminal_capsule(raw_text).stem
    return SegmentTextState(
        stem=stem,
        terminal_raw=terminal_raw or "",
        terminal_closer_suffix=terminal_closer_suffix or "",
        terminal_source=terminal_source or "synthetic",
    )


def _build_legacy_normalized_text(stem: str) -> str:
    normalized_stem = stem.rstrip()
    if not normalized_stem:
        raise ValueError("Segment text must contain readable speech content.")
    return f"{normalized_stem}。"


def _derive_risk_flags(speech_text: str) -> list[str]:
    speech_char_count = sum(
        1
        for char in speech_text
        if not char.isspace() and char not in _NON_SPEECH_CHARACTERS
    )
    if speech_char_count <= 0:
        raise ValueError("Segment text must contain readable speech content.")

    approx_seconds = speech_char_count / _APPROX_CHARS_PER_SECOND
    risk_flags: list[str] = []
    if approx_seconds < _SHORT_SEGMENT_SECONDS:
        risk_flags.append(SHORT_NATURALNESS_RISK)
    if approx_seconds > _LONG_SEGMENT_SECONDS:
        risk_flags.append(LONG_EDIT_COST_RISK)
    return risk_flags
