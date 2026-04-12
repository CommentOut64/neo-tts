import { beforeEach, describe, expect, it, vi } from "vitest";

describe("useStandardizationPreview", () => {
  beforeEach(() => {
    vi.resetModules();
    vi.useFakeTimers();
  });

  it("debounces short text preview requests and exposes returned segments", async () => {
    const requestStandardizationPreview = vi.fn().mockResolvedValue({
      analysis_stage: "complete",
      document_char_count: 4,
      total_segments: 1,
      next_cursor: null,
      resolved_document_language: "zh",
      language_detection_source: "auto",
      warnings: [],
      segments: [
        {
          order_key: 1,
          canonical_text: "第一句。",
          terminal_raw: "。",
          terminal_closer_suffix: "",
          terminal_source: "original",
          detected_language: "zh",
          inference_exclusion_reason: "none",
          warnings: [],
        },
      ],
    });

    vi.doMock("../src/api/editSessionPreview.ts", () => ({
      requestStandardizationPreview,
    }));

    const vue = await import("vue");
    const { useStandardizationPreview } = await import("../src/composables/useStandardizationPreview.ts");
    const text = vue.ref("");
    const preview = useStandardizationPreview(text);

    text.value = "第一句。";
    await vue.nextTick();
    vi.advanceTimersByTime(449);
    expect(requestStandardizationPreview).not.toHaveBeenCalled();

    vi.advanceTimersByTime(1);
    await Promise.resolve();
    await Promise.resolve();

    expect(requestStandardizationPreview).toHaveBeenCalledTimes(1);
    expect(requestStandardizationPreview.mock.calls[0]?.[0]?.text_language).toBe("auto");
    expect(preview.totalSegments.value).toBe(1);
    expect(preview.segments.value[0]?.canonical_text).toBe("第一句。");
  });

  it("uses longer debounce for long text and ignores stale responses", async () => {
    let callIndex = 0;
    const requestStandardizationPreview = vi.fn().mockImplementation(async () => {
      callIndex += 1;
      if (callIndex === 1) {
        return new Promise((resolve) => {
          setTimeout(() => {
            resolve({
              analysis_stage: "complete",
              document_char_count: 3000,
              total_segments: 1,
              next_cursor: null,
              resolved_document_language: "zh",
              language_detection_source: "auto",
              warnings: [],
              segments: [
                {
                  order_key: 1,
                  canonical_text: "旧结果。",
                  terminal_raw: "",
                  terminal_closer_suffix: "",
                  terminal_source: "synthetic",
                  detected_language: "zh",
                  inference_exclusion_reason: "none",
                  warnings: [],
                },
              ],
            });
          }, 20);
        });
      }
      return {
        analysis_stage: "complete",
        document_char_count: 3001,
        total_segments: 1,
        next_cursor: null,
        resolved_document_language: "zh",
        language_detection_source: "auto",
        warnings: [],
        segments: [
          {
            order_key: 1,
            canonical_text: "新结果。",
            terminal_raw: "",
            terminal_closer_suffix: "",
            terminal_source: "synthetic",
            detected_language: "zh",
            inference_exclusion_reason: "none",
            warnings: [],
          },
        ],
      };
    });

    vi.doMock("../src/api/editSessionPreview.ts", () => ({
      requestStandardizationPreview,
    }));

    const vue = await import("vue");
    const { useStandardizationPreview } = await import("../src/composables/useStandardizationPreview.ts");
    const text = vue.ref("");
    const preview = useStandardizationPreview(text);

    text.value = "甲".repeat(3000);
    await vue.nextTick();
    vi.advanceTimersByTime(799);
    expect(requestStandardizationPreview).not.toHaveBeenCalled();

    vi.advanceTimersByTime(1);
    await Promise.resolve();

    text.value = "乙".repeat(3001);
    await vue.nextTick();
    vi.advanceTimersByTime(800);
    await Promise.resolve();
    vi.advanceTimersByTime(20);
    await Promise.resolve();
    await Promise.resolve();

    expect(requestStandardizationPreview).toHaveBeenCalledTimes(2);
    expect(preview.segments.value[0]?.canonical_text).toBe("新结果。");
  });

  it("uses light preview first and appends later pages for very large text", async () => {
    const requestStandardizationPreview = vi
      .fn()
      .mockResolvedValueOnce({
        analysis_stage: "light",
        document_char_count: 5000,
        total_segments: 81,
        next_cursor: 80,
        resolved_document_language: null,
        language_detection_source: null,
        warnings: [],
        segments: [
          {
            order_key: 1,
            canonical_text: "首段。",
            terminal_raw: "",
            terminal_closer_suffix: "",
            terminal_source: "synthetic",
            detected_language: null,
            inference_exclusion_reason: null,
            warnings: [],
          },
        ],
      })
      .mockResolvedValueOnce({
        analysis_stage: "light",
        document_char_count: 5000,
        total_segments: 81,
        next_cursor: null,
        resolved_document_language: null,
        language_detection_source: null,
        warnings: [],
        segments: [
          {
            order_key: 81,
            canonical_text: "末段。",
            terminal_raw: "",
            terminal_closer_suffix: "",
            terminal_source: "synthetic",
            detected_language: null,
            inference_exclusion_reason: null,
            warnings: [],
          },
        ],
      });

    vi.doMock("../src/api/editSessionPreview.ts", () => ({
      requestStandardizationPreview,
    }));

    const vue = await import("vue");
    const { useStandardizationPreview } = await import("../src/composables/useStandardizationPreview.ts");
    const text = vue.ref("");
    const preview = useStandardizationPreview(text);

    text.value = "甲".repeat(5000);
    await vue.nextTick();
    vi.advanceTimersByTime(800);
    await Promise.resolve();
    await Promise.resolve();

    expect(requestStandardizationPreview).toHaveBeenCalledTimes(1);
    expect(requestStandardizationPreview.mock.calls[0]?.[0]).toMatchObject({
      raw_text: "甲".repeat(5000),
      segment_limit: 80,
      cursor: null,
      include_language_analysis: false,
    });
    expect(preview.analysisStage.value).toBe("light");
    expect(preview.nextCursor.value).toBe(80);

    await preview.loadMore();
    await Promise.resolve();
    await Promise.resolve();

    expect(requestStandardizationPreview).toHaveBeenCalledTimes(2);
    expect(requestStandardizationPreview.mock.calls[1]?.[0]).toMatchObject({
      raw_text: "甲".repeat(5000),
      segment_limit: 80,
      cursor: 80,
      include_language_analysis: false,
    });
    expect(preview.nextCursor.value).toBeNull();
    expect(preview.segments.value.map((segment) => segment.order_key)).toEqual([1, 81]);
  });

  it("会把支持的显式语言传给 preview 请求", async () => {
    const requestStandardizationPreview = vi.fn().mockResolvedValue({
      analysis_stage: "complete",
      document_char_count: 5,
      total_segments: 1,
      next_cursor: null,
      resolved_document_language: "ja",
      language_detection_source: "explicit",
      warnings: [],
      segments: [],
    });

    vi.doMock("../src/api/editSessionPreview.ts", () => ({
      requestStandardizationPreview,
    }));

    const vue = await import("vue");
    const { useStandardizationPreview } = await import("../src/composables/useStandardizationPreview.ts");
    const text = vue.ref("");
    const textLanguage = vue.ref("ja");
    useStandardizationPreview(text, textLanguage);

    text.value = "こんにちは。";
    await vue.nextTick();
    vi.advanceTimersByTime(450);
    await Promise.resolve();
    await Promise.resolve();

    expect(requestStandardizationPreview.mock.calls[0]?.[0]?.text_language).toBe("ja");
  });

  it("ko 会保守回退为 auto，避免 preview 请求携带不支持的显式语言", async () => {
    const requestStandardizationPreview = vi.fn().mockResolvedValue({
      analysis_stage: "complete",
      document_char_count: 2,
      total_segments: 1,
      next_cursor: null,
      resolved_document_language: null,
      language_detection_source: "auto",
      warnings: [],
      segments: [],
    });

    vi.doMock("../src/api/editSessionPreview.ts", () => ({
      requestStandardizationPreview,
    }));

    const vue = await import("vue");
    const { useStandardizationPreview } = await import("../src/composables/useStandardizationPreview.ts");
    const text = vue.ref("");
    const textLanguage = vue.ref("ko");
    useStandardizationPreview(text, textLanguage);

    text.value = "안녕";
    await vue.nextTick();
    vi.advanceTimersByTime(450);
    await Promise.resolve();
    await Promise.resolve();

    expect(requestStandardizationPreview.mock.calls[0]?.[0]?.text_language).toBe("auto");
  });
});
