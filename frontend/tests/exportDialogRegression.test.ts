import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

function readSource(relativePath: string) {
  return readFileSync(new URL(relativePath, import.meta.url), "utf-8");
}

describe("ExportDialog regressions", () => {
  it("事件流失败时会回退到导出 job 轮询，而不是立刻判定导出失败", () => {
    const source = readSource("../src/components/workspace/ExportDialog.vue");

    expect(source.includes("getExportJob")).toBe(true);
    expect(source.includes("事件流断开，正在改用轮询继续跟踪")).toBe(true);
    expect(source.includes("setInterval(() => {")).toBe(true);
    expect(source.includes("statusMessage.value = \"导出出错: \" + String(err);")).toBe(false);
  });

  it("导出类型单选使用 Element Plus value API", () => {
    const source = readSource("../src/components/workspace/ExportDialog.vue");

    expect(source.includes('<el-radio-button value="composition">')).toBe(true);
    expect(source.includes('<el-radio-button value="segments">')).toBe(true);
    expect(source.includes('label="composition"')).toBe(false);
    expect(source.includes('label="segments"')).toBe(false);
  });

  it("导出目录文案明确为导出根目录，并说明两种导出的自动命名规则", () => {
    const source = readSource("../src/components/workspace/ExportDialog.vue");

    expect(source.includes("导出根目录（绝对路径）")).toBe(true);
    expect(source.includes("neo-tts-export-时间戳.wav")).toBe(true);
    expect(source.includes("segments-N.wav")).toBe(true);
  });
});
