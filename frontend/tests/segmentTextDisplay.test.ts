import { describe, expect, it } from "vitest";

import {
  buildSegmentDisplayText,
  splitSegmentTerminalCapsule,
} from "../src/utils/segmentTextDisplay";

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

  it("synthetic closer suffix 场景仍会从 raw_text 回推 stem", () => {
    expect(
      buildSegmentDisplayText({
        raw_text: "你好。”",
        terminal_raw: "",
        terminal_closer_suffix: "”",
        terminal_source: "synthetic",
        detected_language: "zh",
      }),
    ).toBe("你好。”");
  });

  it("缺少句尾胶囊字段时回退到 raw_text", () => {
    expect(
      buildSegmentDisplayText({
        raw_text: "第一句。",
      }),
    ).toBe("第一句。");
  });

  it("能拆出原始句尾簇和尾随闭合符", () => {
    expect(splitSegmentTerminalCapsule("真的吗？！」")).toEqual({
      stem: "真的吗",
      terminal: "？！",
      closerSuffix: "」",
      capsule: "？！」",
    });
  });

  it("能识别英文句号作为句尾终止符", () => {
    expect(splitSegmentTerminalCapsule("Hello world.")).toEqual({
      stem: "Hello world",
      terminal: ".",
      closerSuffix: "",
      capsule: ".",
    });
  });

  it("没有句尾终止符时返回空 capsule", () => {
    expect(splitSegmentTerminalCapsule("没有句号")).toEqual({
      stem: "没有句号",
      terminal: "",
      closerSuffix: "",
      capsule: "",
    });
  });
});
