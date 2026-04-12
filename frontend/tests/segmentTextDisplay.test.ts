import { describe, expect, it } from "vitest";

import { buildSegmentDisplayText } from "../src/utils/segmentTextDisplay";

describe("segmentTextDisplay", () => {
  it("raw_text 已包含句尾簇时不会重复拼接闭合引号", () => {
    expect(
      buildSegmentDisplayText({
        raw_text: "“等那边准备好了，我就过来接你们。”",
        terminal_raw: "。",
        terminal_closer_suffix: "”",
        terminal_source: "original",
        detected_language: "zh",
      }),
    ).toBe("“等那边准备好了，我就过来接你们。”");
  });

  it("保留原始句尾簇与尾随闭合符", () => {
    expect(
      buildSegmentDisplayText({
        raw_text: "真的吗。",
        terminal_raw: "？！",
        terminal_closer_suffix: "”",
        terminal_source: "original",
        detected_language: "zh",
      }),
    ).toBe("真的吗？！”");
  });

  it("英文 synthetic period 显示为 ASCII 句号", () => {
    expect(
      buildSegmentDisplayText({
        raw_text: "Hello world。",
        terminal_raw: "",
        terminal_closer_suffix: "",
        terminal_source: "synthetic",
        detected_language: "en",
      }),
    ).toBe("Hello world.");
  });

  it("缺少句尾胶囊字段时回退到 raw_text", () => {
    expect(
      buildSegmentDisplayText({
        raw_text: "第一句。",
      }),
    ).toBe("第一句。");
  });
});
