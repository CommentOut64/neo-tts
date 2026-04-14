import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

function resolveFromTests(relativePath: string) {
  return resolve(dirname(fileURLToPath(import.meta.url)), relativePath);
}

const edgeParameterPanelSource = readFileSync(
  resolveFromTests("../src/components/workspace/EdgeParameterPanel.vue"),
  "utf8",
);
const parameterSliderSource = readFileSync(
  resolveFromTests("../src/components/ParameterSlider.vue"),
  "utf8",
);

describe("edge parameter panel", () => {
  it("停顿时长输入框可放宽到 10 秒，但滑杆仍只覆盖 0 到 2 秒", () => {
    expect(edgeParameterPanelSource).toContain(':slider-max="2"');
    expect(edgeParameterPanelSource).toContain(':input-max="10"');
    expect(edgeParameterPanelSource).toContain("滑杆支持 0 到 2 秒");
  });

  it("超过输入上限时会标红且不直接写回参数值", () => {
    expect(parameterSliderSource).toContain("parameter-slider-input-invalid");
    expect(parameterSliderSource).toContain("parsedInputValue.value > inputMax.value");
    expect(parameterSliderSource).toContain("emit('update:modelValue', parsed)");
  });
});
