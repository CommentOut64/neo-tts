import { beforeEach, describe, expect, it, vi } from "vitest";

const apiMocks = vi.hoisted(() => ({
  getInferenceParamsCache: vi.fn(),
  putInferenceParamsCache: vi.fn(),
}));

vi.mock("@/api/tts", () => apiMocks);

function createStorage() {
  const store = new Map<string, string>();

  return {
    getItem(key: string) {
      return store.has(key) ? store.get(key)! : null;
    },
    setItem(key: string, value: string) {
      store.set(key, value);
    },
    removeItem(key: string) {
      store.delete(key);
    },
    clear() {
      store.clear();
    },
  };
}

async function loadModules() {
  vi.resetModules();
  const cacheModule = await import("../src/composables/useInferenceParamsCache");
  const referenceBindingModule = await import("../src/features/reference-binding");
  return {
    ...cacheModule,
    ...referenceBindingModule,
  };
}

describe("useInferenceParamsCache", () => {
  const localStorageMock = createStorage();

  beforeEach(() => {
    localStorageMock.clear();
    apiMocks.getInferenceParamsCache.mockReset();
    apiMocks.putInferenceParamsCache.mockReset();
    vi.stubGlobal("window", {
      localStorage: localStorageMock,
      setTimeout,
      clearTimeout,
    });
  });

  it("restoreCache 会把旧版平面 reference 字段迁移到按 binding 的映射并立刻写回本地缓存", async () => {
    localStorageMock.setItem(
      "gpt-sovits-inference-params-cache",
      JSON.stringify({
        payload: {
          voice_id: "voice-a",
          ref_source: "custom",
          custom_ref_path: "managed_voices/_temp_refs/custom.wav",
          ref_text: "缓存里的自定义参考文本",
          ref_lang: "ja",
        },
        updatedAt: "2026-04-12T00:00:00Z",
      }),
    );

    const {
      useInferenceParamsCache,
      buildReferenceBindingKey,
      DEFAULT_REFERENCE_BINDING_MODEL_KEY,
    } = await loadModules();
    const cache = useInferenceParamsCache();

    const restored = await cache.restoreCache();
    const bindingKey = buildReferenceBindingKey({
      voiceId: "voice-a",
      modelKey: DEFAULT_REFERENCE_BINDING_MODEL_KEY,
    });

    expect(restored?.payload.referenceSelectionsByBinding).toEqual({
      [bindingKey]: {
        source: "custom",
        session_reference_asset_id: null,
        custom_ref_path: "managed_voices/_temp_refs/custom.wav",
        ref_text: "缓存里的自定义参考文本",
        ref_lang: "ja",
      },
    });

    const persisted = JSON.parse(
      localStorageMock.getItem("gpt-sovits-inference-params-cache") ?? "null",
    );
    expect(persisted.payload.referenceSelectionsByBinding).toEqual({
      [bindingKey]: {
        source: "custom",
        session_reference_asset_id: null,
        custom_ref_path: "managed_voices/_temp_refs/custom.wav",
        ref_text: "缓存里的自定义参考文本",
        ref_lang: "ja",
      },
    });
  });

  it("persistCacheNow 会把旧版 workspace payload 升级成包含 referenceSelectionsByBinding 的 V2 结构再写远端", async () => {
    apiMocks.putInferenceParamsCache.mockResolvedValue({
      payload: {},
      updated_at: "2026-04-12T00:00:00Z",
    });

    const {
      useInferenceParamsCache,
      buildReferenceBindingKey,
      DEFAULT_REFERENCE_BINDING_MODEL_KEY,
    } = await loadModules();
    const cache = useInferenceParamsCache();

    await cache.persistCacheNow({
      voice_id: "voice-b",
      ref_source: "preset",
      custom_ref_path: null,
      ref_text: "预设参考文本",
      ref_lang: "zh",
    });

    const bindingKey = buildReferenceBindingKey({
      voiceId: "voice-b",
      modelKey: DEFAULT_REFERENCE_BINDING_MODEL_KEY,
    });

    expect(apiMocks.putInferenceParamsCache).toHaveBeenCalledWith(
      expect.objectContaining({
        referenceSelectionsByBinding: {
          [bindingKey]: {
            source: "preset",
            session_reference_asset_id: null,
            custom_ref_path: null,
            ref_text: "预设参考文本",
            ref_lang: "zh",
          },
        },
      }),
    );
  });
});
