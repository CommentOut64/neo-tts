import { describe, expect, it } from "vitest";

import {
  resolveReferenceSelectionBySource,
  resolveReferenceSelectionForBinding,
} from "../src/features/reference-binding";
import type { VoiceProfile } from "../src/types/tts";

const voices: VoiceProfile[] = [
  {
    name: "voice-a",
    gpt_path: "voices/a.ckpt",
    sovits_path: "voices/a.pth",
    ref_audio: "voices/a.wav",
    ref_text: "voice-a-preset",
    ref_lang: "zh",
    description: "",
    defaults: {
      speed: 1,
      top_k: 15,
      top_p: 1,
      temperature: 1,
      pause_length: 0.3,
    },
    managed: true,
  },
];

describe("reference-binding", () => {
  it("preset 模式会回到当前音色预设文本和语言，而不是继续沿用旧 custom 缓存", () => {
    expect(
      resolveReferenceSelectionBySource({
        voiceId: "voice-a",
        source: "preset",
        voices,
        selections: {
          "voice-a:gpt-sovits-v2": {
            source: "custom",
            custom_ref_path: "managed/_temp_refs/custom.wav",
            ref_text: "old-custom-text",
            ref_lang: "ja",
          },
        },
      }),
    ).toEqual({
      bindingKey: "voice-a:gpt-sovits-v2",
      selection: {
        source: "preset",
        custom_ref_path: null,
        ref_text: "voice-a-preset",
        ref_lang: "zh",
      },
    });
  });

  it("binding 已缓存 custom 时，切换回该音色仍恢复 custom 选择", () => {
    expect(
      resolveReferenceSelectionForBinding({
        voiceId: "voice-a",
        voices,
        selections: {
          "voice-a:gpt-sovits-v2": {
            source: "custom",
            custom_ref_path: "managed/_temp_refs/custom.wav",
            ref_text: "old-custom-text",
            ref_lang: "ja",
          },
        },
      }),
    ).toEqual({
      bindingKey: "voice-a:gpt-sovits-v2",
      selection: {
        source: "custom",
        custom_ref_path: "managed/_temp_refs/custom.wav",
        ref_text: "old-custom-text",
        ref_lang: "ja",
      },
    });
  });

  it("binding 缓存里即使残留 preset 条目，也会重新对齐到当前音色预设", () => {
    expect(
      resolveReferenceSelectionForBinding({
        voiceId: "voice-a",
        voices,
        selections: {
          "voice-a:gpt-sovits-v2": {
            source: "preset",
            custom_ref_path: "managed/_temp_refs/should-not-survive.wav",
            ref_text: "stale-text",
            ref_lang: "ja",
          },
        },
      }),
    ).toEqual({
      bindingKey: "voice-a:gpt-sovits-v2",
      selection: {
        source: "preset",
        custom_ref_path: null,
        ref_text: "voice-a-preset",
        ref_lang: "zh",
      },
    });
  });
});
