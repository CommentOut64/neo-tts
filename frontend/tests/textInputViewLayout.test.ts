import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const textInputViewSource = readFileSync(
  resolve(
    dirname(fileURLToPath(import.meta.url)),
    "../src/views/TextInputView.vue",
  ),
  "utf8",
);

describe("text input view layout", () => {
  it("输入页左栏会显示统计信息和参数调整两个 card", () => {
    expect(textInputViewSource).toContain("文本统计");
    expect(textInputViewSource).toContain("参数调整");
    expect(textInputViewSource).toContain("总字符数");
    expect(textInputViewSource).toContain("非标点字符");
    expect(textInputViewSource).toContain("总段数");
    expect(textInputViewSource).toContain("文本语言");
  });

  it("切分预览会复用父层 preview 状态，而不是组件内自发请求", () => {
    expect(textInputViewSource).toContain(":segments=\"segments\"");
    expect(textInputViewSource).toContain(":total-segments=\"totalSegments\"");
  });
});
