import type { JSONContent } from "@tiptap/vue-3";

import type { ResolvedLanguage } from "@/types/editSession";
import { splitSegmentTerminalCapsule } from "@/utils/segmentTextDisplay";

export interface WorkspaceSegmentTextDraft {
  segmentId: string;
  stem: string;
  terminal_raw: string;
  terminal_closer_suffix: string;
  terminal_source: "original" | "synthetic";
}

export interface WorkspaceSegmentDraftDisplayOptions {
  detectedLanguage?: ResolvedLanguage | null;
  textLanguage?: string | null;
}

export interface WorkspaceSegmentRegionProjection {
  stemText: string;
  terminalText: string;
}

function resolveSyntheticDisplayTerminal(
  options: WorkspaceSegmentDraftDisplayOptions,
): string {
  const language =
    options.detectedLanguage && options.detectedLanguage !== "unknown"
      ? options.detectedLanguage
      : options.textLanguage;
  return language === "en" ? "." : "。";
}

export function createEmptyWorkspaceSegmentTextDraft(
  segmentId: string,
): WorkspaceSegmentTextDraft {
  return {
    segmentId,
    stem: "",
    terminal_raw: "",
    terminal_closer_suffix: "",
    terminal_source: "original",
  };
}

export function projectWorkspaceSegmentDraftToRegions(input: {
  draft: WorkspaceSegmentTextDraft;
  detectedLanguage?: ResolvedLanguage | null;
  textLanguage?: string | null;
}): WorkspaceSegmentRegionProjection {
  const terminalText = input.draft.terminal_source === "synthetic"
    ? `${resolveSyntheticDisplayTerminal(input)}${input.draft.terminal_closer_suffix}`
    : `${input.draft.terminal_raw}${input.draft.terminal_closer_suffix}`;

  return {
    stemText: input.draft.stem,
    terminalText,
  };
}

export function buildWorkspaceSegmentDisplayTextFromDraft(input: {
  draft: WorkspaceSegmentTextDraft;
  detectedLanguage?: ResolvedLanguage | null;
  textLanguage?: string | null;
}): string {
  const projection = projectWorkspaceSegmentDraftToRegions(input);
  return `${projection.stemText}${projection.terminalText}`;
}

export function buildWorkspaceSegmentTextNodes(input: {
  segmentId: string;
  stemText: string;
  terminalText: string;
  terminalSource?: "original" | "synthetic" | null;
}): JSONContent[] {
  const nodes: JSONContent[] = [];

  if (input.stemText.length > 0) {
    nodes.push({
      type: "text",
      text: input.stemText,
      marks: [{ type: "segmentAnchor", attrs: { segmentId: input.segmentId } }],
    });
  }

  if (input.terminalText.length > 0) {
    const terminalCapsuleAttrs: Record<string, unknown> = {
      segmentId: input.segmentId,
    };
    if (input.terminalSource !== undefined && input.terminalSource !== null) {
      terminalCapsuleAttrs.terminalSource = input.terminalSource;
    }
    nodes.push({
      type: "text",
      text: input.terminalText,
      marks: [
        { type: "segmentAnchor", attrs: { segmentId: input.segmentId } },
        {
          type: "terminalCapsule",
          attrs: terminalCapsuleAttrs,
        },
      ],
    });
  }

  return nodes;
}

export function buildWorkspaceSegmentTextNodesFromDisplayText(input: {
  segmentId: string;
  text: string;
}): JSONContent[] {
  const parts = splitSegmentTerminalCapsule(input.text);
  return buildWorkspaceSegmentTextNodes({
    segmentId: input.segmentId,
    stemText: parts.stem,
    terminalText: parts.capsule,
  });
}

export function resolveWorkspaceSegmentDraftFromRegions(input: {
  previousDraft: WorkspaceSegmentTextDraft;
  stemText: string;
  terminalRegionText: string;
  detectedLanguage?: ResolvedLanguage | null;
  textLanguage?: string | null;
}): WorkspaceSegmentTextDraft {
  const previousTerminalText = projectWorkspaceSegmentDraftToRegions({
    draft: input.previousDraft,
    detectedLanguage: input.detectedLanguage,
    textLanguage: input.textLanguage,
  }).terminalText;

  if (input.terminalRegionText === previousTerminalText) {
    return {
      ...input.previousDraft,
      stem: input.stemText,
    };
  }

  const parsedTerminal = splitSegmentTerminalCapsule(input.terminalRegionText);
  return {
    segmentId: input.previousDraft.segmentId,
    stem: `${input.stemText}${parsedTerminal.stem}`,
    terminal_raw: parsedTerminal.terminal,
    terminal_closer_suffix: parsedTerminal.closerSuffix,
    terminal_source: "original",
  };
}
