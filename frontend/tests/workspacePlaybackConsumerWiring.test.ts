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

  it("TransportControlBar 应接入 playbackCursorError 以禁用错误态播放", () => {
    const source = readWorkspaceComponentSource(
      "../src/components/workspace/TransportControlBar.vue",
    );

    expect(source).toContain("playbackCursorError");
    expect(source).toContain("Boolean(playbackCursorError.value)");
  });

  it("WaveformStrip 应接入 playbackCursorError 以禁用错误态拖拽", () => {
    const source = readWorkspaceComponentSource(
      "../src/components/workspace/WaveformStrip.vue",
    );

    expect(source).toContain("playbackCursorError");
    expect(source).toContain("if (playbackCursorError.value) return null");
  });
});
