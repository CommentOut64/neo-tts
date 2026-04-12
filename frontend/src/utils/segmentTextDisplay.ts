import type { ResolvedLanguage } from "@/types/editSession";

export interface SegmentDisplayLike {
  raw_text: string;
  terminal_raw?: string;
  terminal_closer_suffix?: string;
  terminal_source?: "original" | "synthetic";
  detected_language?: ResolvedLanguage | null;
}

function deriveStem(rawText: string): string {
  return rawText.endsWith("。")
    ? rawText.slice(0, -1)
    : rawText;
}

function resolveSyntheticTerminal(language: ResolvedLanguage | null | undefined): string {
  return language === "en" ? "." : "。";
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
  return `${deriveStem(segment.raw_text)}${terminal}${closerSuffix}`;
}
