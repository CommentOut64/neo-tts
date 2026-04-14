import { describe, expect, it } from "vitest";

import type { StandardizationPreviewSegment } from "../src/types/editSession";
import { buildStandardizationPreviewDisplayText } from "../src/utils/standardizationPreviewDisplay.ts";

function createSegment(
  overrides: Partial<StandardizationPreviewSegment> = {},
): StandardizationPreviewSegment {
  return {
    order_key: 1,
    canonical_text: "第一句。",
    terminal_raw: "。",
    terminal_closer_suffix: "",
    terminal_source: "original",
    detected_language: "zh",
    inference_exclusion_reason: "none",
    warnings: [],
    ...overrides,
  };
}

describe("standardization preview display", () => {
  it("保留原始句尾簇和尾随闭合符", () => {
    const segment = createSegment({
      canonical_text: "真的吗。",
      terminal_raw: "？！",
      terminal_closer_suffix: "”",
    });

    expect(buildStandardizationPreviewDisplayText(segment)).toBe("真的吗？！”");
  });

  it("英文 synthetic period 显示为 ASCII 句号", () => {
    const segment = createSegment({
      canonical_text: "Hello world。",
      terminal_raw: "",
      terminal_source: "synthetic",
      detected_language: "en",
    });

    expect(buildStandardizationPreviewDisplayText(segment)).toBe("Hello world.");
  });
});
