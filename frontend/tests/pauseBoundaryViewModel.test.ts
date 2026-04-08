import { describe, expect, it } from "vitest";

import {
  resolvePauseBoundaryChipClass,
  shouldHighlightPauseBoundaryAsDirty,
} from "../src/components/workspace/workspace-editor/pauseBoundaryViewModel";

describe("pauseBoundaryViewModel", () => {
  it("只在对应 edge 存在未提交草稿时把停顿节点标记为 dirty", () => {
    expect(
      shouldHighlightPauseBoundaryAsDirty({
        edgeId: "edge-1",
        dirtyEdgeIds: new Set(["edge-1"]),
      }),
    ).toBe(true);

    expect(
      shouldHighlightPauseBoundaryAsDirty({
        edgeId: "edge-1",
        dirtyEdgeIds: new Set(["edge-2"]),
      }),
    ).toBe(false);

    expect(
      shouldHighlightPauseBoundaryAsDirty({
        edgeId: null,
        dirtyEdgeIds: new Set(["edge-1"]),
      }),
    ).toBe(false);
  });

  it("dirty 停顿节点会追加橙色 class，未 dirty 时保持原样", () => {
    const dirtyClass = resolvePauseBoundaryChipClass({
      isCrossBlock: false,
      isDirty: true,
    });
    expect(dirtyClass).toContain("pause-boundary-dirty");

    const normalClass = resolvePauseBoundaryChipClass({
      isCrossBlock: true,
      isDirty: false,
    });
    expect(normalClass).not.toContain("pause-boundary-dirty");
    expect(normalClass).toContain("border-dashed");
  });
});
