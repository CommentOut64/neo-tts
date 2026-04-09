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

  it("停顿节点 class 只保留无固定高度和更窄左右留白，字号交给宿主层控制", () => {
    const inlineBoundaryClass = resolvePauseBoundaryChipClass({
      isCrossBlock: false,
      isDirty: false,
    });
    expect(inlineBoundaryClass).toContain("inline-flex");
    expect(inlineBoundaryClass).not.toContain("h-6");
    expect(inlineBoundaryClass).toContain("px-1.5");
    expect(inlineBoundaryClass).not.toContain("px-2");
    expect(inlineBoundaryClass).not.toContain("text-[11px]");

    const crossBlockClass = resolvePauseBoundaryChipClass({
      isCrossBlock: true,
      isDirty: false,
    });
    expect(crossBlockClass).toContain("inline-flex");
    expect(crossBlockClass).toContain("border-dashed");
    expect(crossBlockClass).not.toContain("h-6");
    expect(crossBlockClass).toContain("px-1.5");
    expect(crossBlockClass).not.toContain("px-2");
    expect(crossBlockClass).not.toContain("text-[11px]");
  });
});
