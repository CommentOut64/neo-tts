import type { JSONContent } from "@tiptap/vue-3";

import {
  normalizeCompositionLayoutHints,
  type WorkspaceCompositionLayoutHints,
} from "@/components/workspace/workspace-editor/compositionLayoutHints";
import type { WorkspaceSegmentTextDraft } from "@/components/workspace/workspace-editor/terminalRegionModel";

export const WORKSPACE_DRAFT_SCHEMA_VERSION = 3 as const;
export const WORKSPACE_DRAFT_STORAGE_PREFIX = "neo-tts-workspace-local-draft::";
export const WORKSPACE_DRAFT_INDEX_KEY = "neo-tts-workspace-local-draft-index";

export type WorkspaceDraftMode = "editing" | "preview";

export interface WorkspaceDraftSnapshot {
  schemaVersion: typeof WORKSPACE_DRAFT_SCHEMA_VERSION;
  documentId: string;
  documentVersion: number;
  segmentIds: string[];
  mode: WorkspaceDraftMode;
  editorDoc: JSONContent;
  sourceDoc: JSONContent;
  segmentDrafts: Record<string, WorkspaceSegmentTextDraft>;
  effectiveText: string;
  compositionLayoutHints: WorkspaceCompositionLayoutHints | null;
  updatedAt: string;
}

export interface WorkspaceDraftCompatibilityInput {
  documentId: string;
  documentVersion: number;
  segmentIds: string[];
}

function isRecord(raw: unknown): raw is Record<string, unknown> {
  return raw !== null && typeof raw === "object" && !Array.isArray(raw);
}

function normalizeSegmentDraftValue(
  segmentId: string,
  raw: unknown,
): WorkspaceSegmentTextDraft | null {
  if (!isRecord(raw)) {
    return null;
  }

  if (
    typeof raw.stem !== "string" ||
    typeof raw.terminal_raw !== "string" ||
    typeof raw.terminal_closer_suffix !== "string" ||
    (raw.terminal_source !== "original" && raw.terminal_source !== "synthetic")
  ) {
    return null;
  }

  return {
    segmentId,
    stem: raw.stem,
    terminal_raw: raw.terminal_raw,
    terminal_closer_suffix: raw.terminal_closer_suffix,
    terminal_source: raw.terminal_source,
  };
}

function normalizeSegmentDrafts(
  raw: unknown,
): Record<string, WorkspaceSegmentTextDraft> | null {
  if (!isRecord(raw)) {
    return null;
  }

  const entries = Object.entries(raw);
  const normalizedEntries = entries.map(([segmentId, value]) => [
    segmentId,
    normalizeSegmentDraftValue(segmentId, value),
  ] as const);
  if (normalizedEntries.some(([, value]) => value === null)) {
    return null;
  }

  return Object.fromEntries(
    normalizedEntries as Array<[string, WorkspaceSegmentTextDraft]>,
  );
}

function normalizeEditorDoc(raw: unknown): JSONContent | null {
  if (!isRecord(raw) || typeof raw.type !== "string") {
    return null;
  }

  return raw as JSONContent;
}

function normalizeSourceMode(raw: unknown): WorkspaceDraftMode | null {
  if (raw === "editing" || raw === "preview") {
    return raw;
  }

  return null;
}

export function buildWorkspaceDraftStorageKey(documentId: string): string {
  return `${WORKSPACE_DRAFT_STORAGE_PREFIX}${documentId}`;
}

export function normalizeWorkspaceDraftSnapshot(
  raw: unknown,
): WorkspaceDraftSnapshot | null {
  if (!isRecord(raw)) {
    return null;
  }

  if (raw.schemaVersion !== WORKSPACE_DRAFT_SCHEMA_VERSION) {
    return null;
  }

  if (typeof raw.documentId !== "string" || raw.documentId.length === 0) {
    return null;
  }

  if (
    typeof raw.documentVersion !== "number" ||
    !Number.isFinite(raw.documentVersion)
  ) {
    return null;
  }

  if (!Array.isArray(raw.segmentIds) || !raw.segmentIds.every((id) => typeof id === "string")) {
    return null;
  }

  const mode = normalizeSourceMode(raw.mode);
  const editorDoc = normalizeEditorDoc(raw.editorDoc);
  const sourceDoc = normalizeEditorDoc(raw.sourceDoc);
  const segmentDrafts = normalizeSegmentDrafts(raw.segmentDrafts);
  const compositionLayoutHints = normalizeCompositionLayoutHints(
    raw.compositionLayoutHints ?? null,
  );

  if (
    mode === null ||
    editorDoc === null ||
    sourceDoc === null ||
    segmentDrafts === null ||
    compositionLayoutHints === null && raw.compositionLayoutHints !== null ||
    typeof raw.effectiveText !== "string" ||
    typeof raw.updatedAt !== "string"
  ) {
    return null;
  }

  return {
    schemaVersion: WORKSPACE_DRAFT_SCHEMA_VERSION,
    documentId: raw.documentId,
    documentVersion: raw.documentVersion,
    segmentIds: [...raw.segmentIds],
    mode,
    editorDoc,
    sourceDoc,
    segmentDrafts,
    effectiveText: raw.effectiveText,
    compositionLayoutHints,
    updatedAt: raw.updatedAt,
  };
}

export function isWorkspaceDraftCompatible(
  snapshot: WorkspaceDraftSnapshot,
  input: WorkspaceDraftCompatibilityInput,
): boolean {
  if (snapshot.documentId !== input.documentId) {
    return false;
  }

  if (snapshot.documentVersion !== input.documentVersion) {
    return false;
  }

  if (snapshot.segmentIds.length !== input.segmentIds.length) {
    return false;
  }

  return snapshot.segmentIds.every(
    (segmentId, index) => segmentId === input.segmentIds[index],
  );
}
