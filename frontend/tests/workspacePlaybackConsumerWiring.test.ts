import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

const baseDir = dirname(fileURLToPath(import.meta.url));

function readWorkspaceComponentSource(relativePath: string) {
  return readFileSync(resolve(baseDir, relativePath), "utf8");
}

describe("workspace playback consumer wiring", () => {
  it("SegmentListDisplay 应改为消费 currentCursor，而不是旧 currentSegmentId", () => {
    const source = readWorkspaceComponentSource(
      "../src/components/workspace/SegmentListDisplay.vue",
    );

    expect(source).toContain("currentCursor");
    expect(source).not.toContain("currentSegmentId");
  });

  it("SegmentListDisplay 应接入 workspace 自动播放状态，关闭时不再单击即播", () => {
    const source = readWorkspaceComponentSource(
      "../src/components/workspace/SegmentListDisplay.vue",
    );

    expect(source).toContain("useWorkspaceAutoplay");
    expect(source).toContain("if (!workspaceAutoplay.isAutoPlayEnabled.value)");
  });

  it("SegmentListDisplay 渲染 dirty draft 时必须把语言元数据传给 structured terminal helper", () => {
    const source = readWorkspaceComponentSource(
      "../src/components/workspace/SegmentListDisplay.vue",
    );

    expect(source).toContain("buildWorkspaceSegmentDisplayTextFromDraft({");
    expect(source).toContain("detectedLanguage: sessionSegment?.detected_language ?? null");
    expect(source).toContain("textLanguage: sessionSegment?.text_language ?? null");
  });

  it("TransportControlBar 应接入 playbackCursorError 以禁用错误态播放", () => {
    const source = readWorkspaceComponentSource(
      "../src/components/workspace/TransportControlBar.vue",
    );

    expect(source).toContain("playbackCursorError");
    expect(source).toContain("Boolean(playbackCursorError.value)");
  });

  it("TransportControlBar 在关闭自动播放时应优先从主选中段起播", () => {
    const source = readWorkspaceComponentSource(
      "../src/components/workspace/TransportControlBar.vue",
    );

    expect(source).toContain("useWorkspaceAutoplay");
    expect(source).toContain("useSegmentSelection");
    expect(source).toContain("segmentSelection.primarySelectedSegmentId.value");
    expect(source).toContain("seekToSegment(primarySelectedSegmentId)");
  });

  it("WorkspaceEditorHost 应显示自动播放按钮并接入共享状态", () => {
    const source = readWorkspaceComponentSource(
      "../src/components/workspace/WorkspaceEditorHost.vue",
    );

    expect(source).toContain("useWorkspaceAutoplay");
    expect(source).toContain("自动播放");
    expect(source).toContain(":aria-pressed=\"isAutoPlayEnabled\"");
  });

  it("WaveformStrip 应接入 playbackCursorError 以禁用错误态拖拽", () => {
    const source = readWorkspaceComponentSource(
      "../src/components/workspace/WaveformStrip.vue",
    );

    expect(source).toContain("playbackCursorError");
    expect(source).toContain("if (playbackCursorError.value) return null");
  });
});
