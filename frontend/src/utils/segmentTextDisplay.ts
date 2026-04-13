import type { ResolvedLanguage } from "@/types/editSession";

export interface SegmentDisplayLike {
  raw_text: string;
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

function deriveStem(rawText: string): string {
  return rawText.endsWith("。")
    ? rawText.slice(0, -1)
    : rawText;
}

function stripTerminalCluster(
  rawText: string,
  terminal: string,
  closerSuffix: string,
): string {
  const exactCluster = `${terminal}${closerSuffix}`;
  if (exactCluster.length > 0 && rawText.endsWith(exactCluster)) {
    return rawText.slice(0, -exactCluster.length);
  }

  if (closerSuffix.length > 0 && rawText.endsWith(closerSuffix)) {
    const withoutCloserSuffix = rawText.slice(0, -closerSuffix.length);
    if (terminal.length > 0 && withoutCloserSuffix.endsWith(terminal)) {
      return withoutCloserSuffix.slice(0, -terminal.length);
    }
    return withoutCloserSuffix;
  }

  if (terminal.length > 0 && rawText.endsWith(terminal)) {
    return rawText.slice(0, -terminal.length);
  }

  return deriveStem(rawText);
}

function resolveSyntheticTerminal(language: ResolvedLanguage | null | undefined): string {
  return language === "en" ? "." : "。";
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
  if (
    segment.terminal_source === undefined &&
    segment.terminal_raw === undefined &&
    segment.terminal_closer_suffix === undefined
  ) {
    return segment.raw_text;
  }

  const terminal = segment.terminal_raw && segment.terminal_raw.length > 0
    ? segment.terminal_raw
    : resolveSyntheticTerminal(segment.detected_language);
  const closerSuffix = segment.terminal_closer_suffix ?? "";
  const { stem } = splitSegmentTerminalCapsule(
    stripTerminalCluster(segment.raw_text, terminal, closerSuffix),
  );
  return `${stem}${terminal}${closerSuffix}`;
}
