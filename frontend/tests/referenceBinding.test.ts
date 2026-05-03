import { describe, expect, it } from "vitest";

import {
  resolveBindingReferenceState,
  resolveReferenceSelectionBySource,
  resolveReferenceSelectionForBinding,
  buildReferenceBindingKey,
} from "../src/features/reference-binding";
import type { RegistryBindingOption } from "../src/types/ttsRegistry";

const bindingRef = {
  workspace_id: "ws_gpt_sovits",
  main_model_id: "voice-a",
  submodel_id: "default",
  preset_id: "default",
} as const;

const bindingOptions: RegistryBindingOption[] = [
  {
    bindingKey: "ws_gpt_sovits:voice-a:default:default",
    bindingRef,
    workspaceId: "ws_gpt_sovits",
    workspaceDisplayName: "GPT-SoVITS",
    familyId: "gpt_sovits_local",
    familyRouteSlug: "gpt-sovits-local",
    familyDisplayName: "GPT-SoVITS Local",
    adapterId: "gpt_sovits_local",
    mainModelId: "voice-a",
    mainModelDisplayName: "voice-a",
    submodelId: "default",
    submodelDisplayName: "default",
    presetId: "default",
    presetDisplayName: "default",
    label: "GPT-SoVITS / voice-a",
    status: "ready",
    referenceAudioPath: "voices/a.wav",
    referenceText: "voice-a-preset",
    referenceLanguage: "zh",
    defaults: {},
    fixedFields: {},
  },
];

describe("reference-binding", () => {
  it("正式 binding_key 改为 workspace/main/submodel/preset 四元组", () => {
    expect(
      buildReferenceBindingKey({
        bindingRef: {
          workspace_id: "ws_gpt_sovits",
          main_model_id: "voice-a",
          submodel_id: "default",
          preset_id: "default",
        },
      }),
    ).toBe("ws_gpt_sovits:voice-a:default:default");
  });

  it("preset 模式会回到当前音色预设文本和语言，而不是继续沿用旧 custom 缓存", () => {
    expect(
      resolveReferenceSelectionBySource({
        bindingRef,
        source: "preset",
        bindingOptions,
        selections: {
          "ws_gpt_sovits:voice-a:default:default": {
            source: "custom",
            custom_ref_path: "managed/_temp_refs/custom.wav",
            ref_text: "old-custom-text",
            ref_lang: "ja",
          },
        },
      }),
    ).toEqual({
      bindingKey: "ws_gpt_sovits:voice-a:default:default",
      selection: {
        source: "preset",
        session_reference_asset_id: null,
        custom_ref_path: null,
        ref_text: "voice-a-preset",
        ref_lang: "zh",
      },
    });
  });

  it("binding 已缓存 custom 时，切换回该音色仍恢复 custom 选择", () => {
    expect(
      resolveReferenceSelectionForBinding({
        bindingRef,
        bindingOptions,
        selections: {
          "ws_gpt_sovits:voice-a:default:default": {
            source: "custom",
            custom_ref_path: "managed/_temp_refs/custom.wav",
            ref_text: "old-custom-text",
            ref_lang: "ja",
          },
        },
      }),
    ).toEqual({
      bindingKey: "ws_gpt_sovits:voice-a:default:default",
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
        bindingRef,
        bindingOptions,
        selections: {
          "ws_gpt_sovits:voice-a:default:default": {
            source: "preset",
            custom_ref_path: "managed/_temp_refs/should-not-survive.wav",
            ref_text: "stale-text",
            ref_lang: "ja",
          },
        },
      }),
    ).toEqual({
      bindingKey: "ws_gpt_sovits:voice-a:default:default",
      selection: {
        source: "preset",
        session_reference_asset_id: null,
        custom_ref_path: null,
        ref_text: "voice-a-preset",
        ref_lang: "zh",
      },
    });
  });

  it("binding 级 custom override 会保留会话临时参考资产身份，避免与 preset 混淆", () => {
    expect(
      resolveBindingReferenceState({
        binding: {
          binding_ref: bindingRef,
        },
        profile: {
          reference_overrides_by_binding: {
            "ws_gpt_sovits:voice-a:default:default": {
              session_reference_asset_id: "session-ref-1",
              reference_identity: "doc-1:session-ref-1",
              reference_audio_fingerprint: "audio-fp-1",
              reference_audio_path: "storage/edit_session/assets/references/doc-1/session-ref-1/audio.wav",
              reference_text: "session-custom",
              reference_text_fingerprint: "text-fp-1",
              reference_language: "ja",
            },
          },
        },
        bindingOptions,
      }),
    ).toEqual({
      source: "custom",
      reference_scope: "session_override",
      binding_key: "ws_gpt_sovits:voice-a:default:default",
      reference_identity: "doc-1:session-ref-1",
      session_reference_asset_id: "session-ref-1",
      reference_audio_fingerprint: "audio-fp-1",
      reference_audio_path: "storage/edit_session/assets/references/doc-1/session-ref-1/audio.wav",
      reference_text: "session-custom",
      reference_text_fingerprint: "text-fp-1",
      reference_language: "ja",
      preset_audio_path: "voices/a.wav",
      preset_text: "voice-a-preset",
      preset_language: "zh",
    });
  });
});
