import { describe, expect, it } from "vitest";

import { buildUpdateVoiceFormData } from "../src/api/voices";

describe("buildUpdateVoiceFormData", () => {
  it("只序列化有值的编辑字段", () => {
    const form = buildUpdateVoiceFormData({
      description: "updated voice",
      ref_text: "updated reference text",
      ref_lang: "ja",
      gpt_file: new File(["gpt"], "new.ckpt"),
    });

    expect(form.get("description")).toBe("updated voice");
    expect(form.get("ref_text")).toBe("updated reference text");
    expect(form.get("ref_lang")).toBe("ja");
    expect(form.get("gpt_file")).toBeInstanceOf(File);
    expect(form.has("sovits_file")).toBe(false);
    expect(form.has("ref_audio_file")).toBe(false);
  });
});
