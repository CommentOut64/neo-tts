import { describe, expect, it } from "vitest";

import { resolveMainActionButtonState } from "../src/components/workspace/mainActionButtonState";

describe("resolveMainActionButtonState", () => {
  it("空会话且初始化参数齐全时应显示开始生成", () => {
    expect(
      resolveMainActionButtonState({
        sessionStatus: "empty",
        dirtyCount: 0,
        canInitialize: true,
        canMutate: true,
      }),
    ).toEqual({
      mode: "init",
      label: "开始生成",
      disabled: false,
    });
  });

  it("空会话但初始化参数不完整时应禁用开始生成", () => {
    expect(
      resolveMainActionButtonState({
        sessionStatus: "empty",
        dirtyCount: 0,
        canInitialize: false,
        canMutate: true,
      }),
    ).toEqual({
      mode: "init",
      label: "开始生成",
      disabled: true,
    });
  });

  it("ready 态无脏段时应显示禁用的重推理(0)", () => {
    expect(
      resolveMainActionButtonState({
        sessionStatus: "ready",
        dirtyCount: 0,
        canInitialize: true,
        canMutate: true,
      }),
    ).toEqual({
      mode: "rerender",
      label: "重推理(0)",
      disabled: true,
    });
  });

  it("ready 态有脏段时应显示可用的重推理(n)", () => {
    expect(
      resolveMainActionButtonState({
        sessionStatus: "ready",
        dirtyCount: 3,
        canInitialize: true,
        canMutate: true,
      }),
    ).toEqual({
      mode: "rerender",
      label: "重推理(3)",
      disabled: false,
    });
  });

  it("运行中时应保留重推理文案但禁用按钮", () => {
    expect(
      resolveMainActionButtonState({
        sessionStatus: "ready",
        dirtyCount: 2,
        canInitialize: true,
        canMutate: false,
      }),
    ).toEqual({
      mode: "rerender",
      label: "重推理(2)",
      disabled: true,
    });
  });
});
