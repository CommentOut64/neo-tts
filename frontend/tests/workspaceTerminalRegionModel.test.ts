import { describe, expect, it } from "vitest";

import {
  projectWorkspaceSegmentDraftToRegions,
  resolveWorkspaceSegmentDraftFromRegions,
  type WorkspaceSegmentTextDraft,
} from "../src/components/workspace/workspace-editor/terminalRegionModel";
import {
  WORKSPACE_DRAFT_SCHEMA_VERSION,
  normalizeWorkspaceDraftSnapshot,
} from "../src/utils/workspaceDraftSnapshot";

function createDraft(
  overrides: Partial<WorkspaceSegmentTextDraft> = {},
): WorkspaceSegmentTextDraft {
  return {
    segmentId: "seg-1",
    stem: "第一句",
    terminal_raw: "",
    terminal_closer_suffix: "",
    terminal_source: "synthetic",
    ...overrides,
  };
}

describe("workspace terminal region model", () => {
  it("会把结构化 draft 投影成 stem region 与 terminal region", () => {
    expect(
      projectWorkspaceSegmentDraftToRegions({
        draft: createDraft({
          stem: "第一句",
          terminal_raw: "？！",
          terminal_closer_suffix: "」",
          terminal_source: "original",
        }),
      }),
    ).toEqual({
      stemText: "第一句",
      terminalText: "？！」",
    });

    expect(
      projectWorkspaceSegmentDraftToRegions({
        draft: createDraft({
          stem: "Hello",
          terminal_raw: "",
          terminal_closer_suffix: "",
          terminal_source: "synthetic",
        }),
        detectedLanguage: "en",
      }),
    ).toEqual({
      stemText: "Hello",
      terminalText: ".",
    });
  });

  it("terminal region 未改动时会保留 synthetic terminal_source", () => {
    expect(
      resolveWorkspaceSegmentDraftFromRegions({
        previousDraft: createDraft({
          stem: "Hello",
          terminal_raw: "",
          terminal_closer_suffix: "",
          terminal_source: "synthetic",
        }),
        stemText: "Hello there",
        terminalRegionText: ".",
        detectedLanguage: "en",
      }),
    ).toEqual({
      segmentId: "seg-1",
      stem: "Hello there",
      terminal_raw: "",
      terminal_closer_suffix: "",
      terminal_source: "synthetic",
    });
  });

  it("terminal region 被用户改动后会直接落成 original draft", () => {
    expect(
      resolveWorkspaceSegmentDraftFromRegions({
        previousDraft: createDraft({
          stem: "第一句",
          terminal_raw: "",
          terminal_closer_suffix: "",
          terminal_source: "synthetic",
        }),
        stemText: "第一句",
        terminalRegionText: "？！」",
      }),
    ).toEqual({
      segmentId: "seg-1",
      stem: "第一句",
      terminal_raw: "？！",
      terminal_closer_suffix: "」",
      terminal_source: "original",
    });
  });

  it("workspace draft snapshot 只接受结构化 segmentDrafts", () => {
    expect(
      normalizeWorkspaceDraftSnapshot({
        schemaVersion: WORKSPACE_DRAFT_SCHEMA_VERSION,
        documentId: "doc-1",
        documentVersion: 2,
        segmentIds: ["seg-1"],
        mode: "editing",
        editorDoc: { type: "doc", content: [] },
        sourceDoc: { type: "doc", content: [] },
        segmentDrafts: {
          "seg-1": createDraft(),
        },
        effectiveText: "第一句。",
        compositionLayoutHints: null,
        updatedAt: "2026-04-18T00:00:00.000Z",
      }),
    ).toMatchObject({
      schemaVersion: WORKSPACE_DRAFT_SCHEMA_VERSION,
      segmentDrafts: {
        "seg-1": createDraft(),
      },
    });

    expect(
      normalizeWorkspaceDraftSnapshot({
        schemaVersion: WORKSPACE_DRAFT_SCHEMA_VERSION,
        documentId: "doc-1",
        documentVersion: 2,
        segmentIds: ["seg-1"],
        mode: "editing",
        editorDoc: { type: "doc", content: [] },
        sourceDoc: { type: "doc", content: [] },
        segmentDrafts: {
          "seg-1": "旧字符串草稿",
        },
        effectiveText: "第一句。",
        compositionLayoutHints: null,
        updatedAt: "2026-04-18T00:00:00.000Z",
      }),
    ).toBeNull();
  });
});
