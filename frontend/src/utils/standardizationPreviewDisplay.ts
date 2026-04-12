import type { StandardizationPreviewSegment } from "@/types/editSession";

function deriveStem(canonicalText: string): string {
  return canonicalText.endsWith("。")
    ? canonicalText.slice(0, -1)
    : canonicalText;
}

function resolveSyntheticTerminal(
  segment: StandardizationPreviewSegment,
): string {
  return segment.detected_language === "en" ? "." : "。";
}

export function buildStandardizationPreviewDisplayText(
  segment: StandardizationPreviewSegment,
): string {
  const terminal = segment.terminal_raw.length > 0
    ? segment.terminal_raw
    : resolveSyntheticTerminal(segment);
  return `${deriveStem(segment.canonical_text)}${terminal}${segment.terminal_closer_suffix}`;
}
