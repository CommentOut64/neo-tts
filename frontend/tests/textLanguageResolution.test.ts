import { describe, expect, it } from "vitest";

import { buildTextLanguageResolutionDialogModel } from "../src/utils/textLanguageResolution";

describe("text language resolution dialog model", () => {
  it("会为 auto 生成按段自动识别的说明文案", () => {
    const model = buildTextLanguageResolutionDialogModel("zh", "auto");

    expect(model.title).toBe("检测到文本语言设置不一致");
    expect(model.nextOption.actionLabel).toBe("统一按自动检测处理");
    expect(model.nextOption.description).toContain("按段识别 zh / ja / en");
  });

  it("会为韩文保留限制说明，避免误导为完全支持", () => {
    const model = buildTextLanguageResolutionDialogModel("auto", "ko");

    expect(model.nextOption.actionLabel).toBe("统一按韩文设置处理");
    expect(model.nextOption.description).toContain("标准化暂不提供韩文专门规则");
  });
});
