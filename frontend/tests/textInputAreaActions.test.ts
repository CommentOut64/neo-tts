import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const textInputAreaSource = readFileSync(
  resolve(
    dirname(fileURLToPath(import.meta.url)),
    "../src/components/text-input/TextInputArea.vue",
  ),
  "utf8",
);

describe("text input area actions", () => {
  it("输入页会提供恢复最初版本入口", () => {
    expect(textInputAreaSource).toContain("恢复最初版本");
  });

  it("清空输入稿前会提示这会同时清空输入框和当前会话", () => {
    expect(textInputAreaSource).toContain("这会同时清空输入框和当前会话，请先导出音频后再清空");
    expect(textInputAreaSource).not.toContain("仅清空输入文本");
    expect(textInputAreaSource).not.toContain("保留会话正文");
    expect(textInputAreaSource).not.toContain("同步清理会话正文");
  });
});
