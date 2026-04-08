import { describe, expect, it, vi } from "vitest";

import { resolveInitializeReferenceAudioPath } from "../src/utils/referenceAudioSelection";

describe("resolveInitializeReferenceAudioPath", () => {
  it("预设模式直接返回音色预设路径", async () => {
    const upload = vi.fn();

    await expect(
      resolveInitializeReferenceAudioPath({
        refSource: "preset",
        presetReferenceAudioPath: "voices/demo.wav",
        customReferenceAudioPath: null,
        customReferenceAudioFile: null,
        upload,
      }),
    ).resolves.toBe("voices/demo.wav");

    expect(upload).not.toHaveBeenCalled();
  });

  it("自定义模式优先复用已上传路径", async () => {
    const upload = vi.fn();

    await expect(
      resolveInitializeReferenceAudioPath({
        refSource: "custom",
        presetReferenceAudioPath: "voices/demo.wav",
        customReferenceAudioPath: "managed_voices/_temp_refs/custom/custom.wav",
        customReferenceAudioFile: new File(["RIFF"], "custom.wav", { type: "audio/wav" }),
        upload,
      }),
    ).resolves.toBe("managed_voices/_temp_refs/custom/custom.wav");

    expect(upload).not.toHaveBeenCalled();
  });

  it("自定义模式在没有已上传路径时会先上传文件", async () => {
    const upload = vi.fn().mockResolvedValue({
      reference_audio_path: "managed_voices/_temp_refs/new/custom.wav",
      filename: "custom.wav",
    });

    const file = new File(["RIFF"], "custom.wav", { type: "audio/wav" });

    await expect(
      resolveInitializeReferenceAudioPath({
        refSource: "custom",
        presetReferenceAudioPath: "voices/demo.wav",
        customReferenceAudioPath: null,
        customReferenceAudioFile: file,
        upload,
      }),
    ).resolves.toBe("managed_voices/_temp_refs/new/custom.wav");

    expect(upload).toHaveBeenCalledWith(file);
  });
});
