import { describe, expect, it } from "vitest";

import {
  buildSegmentDisplayText,
  splitSegmentTerminalCapsule,
} from "../src/utils/segmentTextDisplay";

describe("segmentTextDisplay", () => {
  it("结构化段文本会直接保留原始句尾簇与尾随闭合符", () => {
    expect(
      buildSegmentDisplayText({
        stem: "“等那边准备好了，我就过来接你们",
        terminal_raw: "。",
        terminal_closer_suffix: "”",
        terminal_source: "original",
        detected_language: "zh",
      }),
    ).toBe("“等那边准备好了，我就过来接你们。”");
  });

  it("结构化段文本能直接输出复合终止符", () => {
    expect(
      buildSegmentDisplayText({
        stem: "真的吗",
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
        stem: "Hello world",
        terminal_raw: "",
        terminal_closer_suffix: "",
        terminal_source: "synthetic",
        detected_language: "en",
      }),
    ).toBe("Hello world.");
  });

  it("synthetic closer suffix 场景会保留结构化 closer suffix", () => {
    expect(
      buildSegmentDisplayText({
        stem: "你好",
        terminal_raw: "",
        terminal_closer_suffix: "”",
        terminal_source: "synthetic",
        detected_language: "zh",
      }),
    ).toBe("你好。”");
  });

  it("缺少 stem 时返回空串，而不是回退到旧 raw_text", () => {
    expect(
      buildSegmentDisplayText({
        terminal_raw: "。",
      }),
    ).toBe("");
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
