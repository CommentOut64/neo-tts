import { describe, expect, it } from "vitest";

import {
  buildDisplayWorkspaceEdges,
  DEFAULT_REORDER_BOUNDARY_STRATEGY,
  DEFAULT_REORDER_PAUSE_DURATION_SECONDS,
} from "../src/components/workspace/workspace-editor/buildDisplayWorkspaceEdges";

describe("buildDisplayWorkspaceEdges", () => {
  it("保持原顺序时复用已有 edge attrs", () => {
    expect(
      buildDisplayWorkspaceEdges({
        orderedSegmentIds: ["seg-1", "seg-2", "seg-3"],
        edges: [
          {
            edgeId: "edge-1",
            leftSegmentId: "seg-1",
            rightSegmentId: "seg-2",
            pauseDurationSeconds: 0.8,
            boundaryStrategy: "hold",
          },
          {
            edgeId: "edge-2",
            leftSegmentId: "seg-2",
            rightSegmentId: "seg-3",
            pauseDurationSeconds: 0.4,
            boundaryStrategy: "crossfade",
          },
        ],
      }),
    ).toEqual([
      {
        edgeId: "edge-1",
        leftSegmentId: "seg-1",
        rightSegmentId: "seg-2",
        pauseDurationSeconds: 0.8,
        boundaryStrategy: "hold",
      },
      {
        edgeId: "edge-2",
        leftSegmentId: "seg-2",
        rightSegmentId: "seg-3",
        pauseDurationSeconds: 0.4,
        boundaryStrategy: "crossfade",
      },
    ]);
  });

  it("重排后优先复用新相邻 pair 对应的已有 edge", () => {
    expect(
      buildDisplayWorkspaceEdges({
        orderedSegmentIds: ["seg-2", "seg-1", "seg-3"],
        edges: [
          {
            edgeId: "edge-1",
            leftSegmentId: "seg-1",
            rightSegmentId: "seg-2",
            pauseDurationSeconds: 0.8,
            boundaryStrategy: "hold",
          },
          {
            edgeId: "edge-2",
            leftSegmentId: "seg-2",
            rightSegmentId: "seg-1",
            pauseDurationSeconds: 0.45,
            boundaryStrategy: "crossfade",
          },
          {
            edgeId: "edge-3",
            leftSegmentId: "seg-1",
            rightSegmentId: "seg-3",
            pauseDurationSeconds: 0.2,
            boundaryStrategy: "latent",
          },
        ],
      }),
    ).toEqual([
      {
        edgeId: "edge-2",
        leftSegmentId: "seg-2",
        rightSegmentId: "seg-1",
        pauseDurationSeconds: 0.45,
        boundaryStrategy: "crossfade",
      },
      {
        edgeId: "edge-3",
        leftSegmentId: "seg-1",
        rightSegmentId: "seg-3",
        pauseDurationSeconds: 0.2,
        boundaryStrategy: "latent",
      },
    ]);
  });

  it("新相邻 pair 不存在时补默认停顿 edge", () => {
    expect(
      buildDisplayWorkspaceEdges({
        orderedSegmentIds: ["seg-3", "seg-1", "seg-2"],
        edges: [
          {
            edgeId: "edge-1",
            leftSegmentId: "seg-1",
            rightSegmentId: "seg-2",
            pauseDurationSeconds: 0.5,
            boundaryStrategy: "hold",
          },
        ],
      }),
    ).toEqual([
      {
        edgeId: null,
        leftSegmentId: "seg-3",
        rightSegmentId: "seg-1",
        pauseDurationSeconds: DEFAULT_REORDER_PAUSE_DURATION_SECONDS,
        boundaryStrategy: DEFAULT_REORDER_BOUNDARY_STRATEGY,
      },
      {
        edgeId: "edge-1",
        leftSegmentId: "seg-1",
        rightSegmentId: "seg-2",
        pauseDurationSeconds: 0.5,
        boundaryStrategy: "hold",
      },
    ]);
  });
});
