import { describe, expect, it } from "vitest";

import {
  resolveParameterScope,
  type ParameterPanelScopeContext,
} from "../src/components/workspace/parameter-panel/resolveParameterScope";

function expectScope(
  actual: ParameterPanelScopeContext,
  expected: ParameterPanelScopeContext,
) {
  expect(actual).toEqual(expected);
}

describe("resolveParameterScope", () => {
  it("无选择时进入会话态", () => {
    expectScope(
      resolveParameterScope({
        selectedSegmentIds: new Set(),
        selectedEdgeId: null,
      }),
      {
        scope: "session",
        segmentIds: [],
        edgeId: null,
      },
    );
  });

  it("单段选择时进入段态", () => {
    expectScope(
      resolveParameterScope({
        selectedSegmentIds: new Set(["seg-1"]),
        selectedEdgeId: null,
      }),
      {
        scope: "segment",
        segmentIds: ["seg-1"],
        edgeId: null,
      },
    );
  });

  it("多段选择时进入批量态", () => {
    expectScope(
      resolveParameterScope({
        selectedSegmentIds: new Set(["seg-1", "seg-2"]),
        selectedEdgeId: null,
      }),
      {
        scope: "batch",
        segmentIds: ["seg-1", "seg-2"],
        edgeId: null,
      },
    );
  });

  it("edge 选择优先于段选择", () => {
    expectScope(
      resolveParameterScope({
        selectedSegmentIds: new Set(["seg-1"]),
        selectedEdgeId: "edge-1",
      }),
      {
        scope: "edge",
        segmentIds: [],
        edgeId: "edge-1",
      },
    );
  });
});
