import type { ResolvedLanguage } from "@/types/editSession";

export interface SegmentDisplayLike {
  stem?: string;
  text_language?: string | null;
  terminal_raw?: string;
  terminal_closer_suffix?: string;
  terminal_source?: "original" | "synthetic";
  detected_language?: ResolvedLanguage | null;
}

export interface SegmentTerminalCapsuleParts {
  stem: string;
  terminal: string;
  closerSuffix: string;
  capsule: string;
}

const TERMINAL_CANDIDATES = [
  "......",
  "……",
  "...",
  "？！",
  "！？",
  "?!",
  "!?",
  "。",
  ".",
  "？",
  "?",
  "！",
  "!",
  "…",
] as const;

const TERMINAL_CLOSER_CHARACTERS = new Set(["”", "’", "」", "』", "）", ")", "]", "】", "》"]);

function resolveSyntheticTerminal(language: ResolvedLanguage | null | undefined): string {
  return language === "en" ? "." : "。";
}

function resolveDisplayLanguage(segment: SegmentDisplayLike): ResolvedLanguage | null | undefined {
  if (segment.detected_language && segment.detected_language !== "unknown") {
    return segment.detected_language;
  }
  if (
    segment.text_language === "zh" ||
    segment.text_language === "ja" ||
    segment.text_language === "en" ||
    segment.text_language === "unknown"
  ) {
    return segment.text_language;
  }
  return segment.detected_language;
}

export function splitSegmentTerminalCapsule(rawText: string): SegmentTerminalCapsuleParts {
  const trimmed = rawText.trimEnd();
  let cursor = trimmed.length - 1;
  let closerSuffix = "";

  while (cursor >= 0 && TERMINAL_CLOSER_CHARACTERS.has(trimmed[cursor])) {
    closerSuffix = `${trimmed[cursor]}${closerSuffix}`;
    cursor -= 1;
  }

  const baseText = trimmed.slice(0, cursor + 1);
  const terminal = TERMINAL_CANDIDATES.find((candidate) => baseText.endsWith(candidate)) ?? "";
  const stem = terminal.length > 0
    ? baseText.slice(0, -terminal.length).trimEnd()
    : baseText.trimEnd();

  return {
    stem,
    terminal,
    closerSuffix,
    capsule: `${terminal}${closerSuffix}`,
  };
}

export function buildSegmentDisplayText(segment: SegmentDisplayLike): string {
  if (segment.stem === undefined) {
    return "";
  }

  const stem = segment.stem.trimEnd();
  if (!stem) {
    return "";
  }

  const terminal = segment.terminal_raw && segment.terminal_raw.length > 0
    ? segment.terminal_raw
    : resolveSyntheticTerminal(resolveDisplayLanguage(segment));
  return `${stem}${terminal}${segment.terminal_closer_suffix ?? ""}`;
}
