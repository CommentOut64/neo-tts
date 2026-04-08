import { describe, expect, it } from "vitest";

import {
  EDGE_BOUNDARY_STRATEGY_OPTIONS,
  formatEdgeBoundaryStrategyLabel,
  formatPauseDurationSeconds,
} from "../src/components/workspace/edgeDisplay";

describe("edgeDisplay", () => {
  it("边界策略文案统一输出中文加英文", () => {
    expect(EDGE_BOUNDARY_STRATEGY_OPTIONS).toEqual([
      {
        value: "latent_overlap_then_equal_power_crossfade",
        label: "智能交叉淡化（Adaptive Crossfade）",
      },
      {
        value: "crossfade",
        label: "简单交叉淡化（Simple Crossfade）",
      },
      {
        value: "hard_cut",
        label: "直接硬切（Hard Cut）",
      },
    ]);

    expect(formatEdgeBoundaryStrategyLabel("crossfade_only")).toBe(
      "兼容交叉淡化（Fallback Crossfade）",
    );
    expect(formatEdgeBoundaryStrategyLabel("custom_mode")).toBe(
      "自定义策略（custom_mode）",
    );
  });

  it("停顿显示默认保留两位小数且不带单位后缀", () => {
    expect(formatPauseDurationSeconds(0.3)).toBe("0.30");
    expect(formatPauseDurationSeconds(0.01)).toBe("0.01");
    expect(formatPauseDurationSeconds(null)).toBe("停顿");
  });
});
