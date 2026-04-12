import { computed, onScopeDispose, ref, watch, type Ref } from "vue";

import { requestStandardizationPreview } from "@/api/editSessionPreview";
import type {
  StandardizationPreviewResponse,
  StandardizationPreviewRequest,
  StandardizationPreviewSegment,
} from "@/types/editSession";

const PREVIEW_DEBOUNCE_MS_SHORT = 450;
const PREVIEW_DEBOUNCE_MS_LONG = 800;
const LONG_TEXT_THRESHOLD = 2000;
const LARGE_TEXT_THRESHOLD = 5000;
const INITIAL_PREVIEW_SEGMENT_LIMIT = 80;
const SUPPORTED_EXPLICIT_PREVIEW_LANGUAGES = new Set(["zh", "en", "ja"]);

const EMPTY_PREVIEW: StandardizationPreviewResponse = {
  analysis_stage: "complete",
  document_char_count: 0,
  total_segments: 0,
  next_cursor: null,
  resolved_document_language: null,
  language_detection_source: null,
  warnings: [],
  segments: [],
};

function resolveDebounceMs(text: string): number {
  return text.length >= LONG_TEXT_THRESHOLD
    ? PREVIEW_DEBOUNCE_MS_LONG
    : PREVIEW_DEBOUNCE_MS_SHORT;
}

function resolvePreviewTextLanguage(
  textLanguage: string | undefined,
): StandardizationPreviewRequest["text_language"] {
  if (textLanguage && SUPPORTED_EXPLICIT_PREVIEW_LANGUAGES.has(textLanguage)) {
    return textLanguage as StandardizationPreviewRequest["text_language"];
  }
  return "auto";
}

export function useStandardizationPreview(
  text: Ref<string>,
  textLanguage?: Ref<string>,
) {
  const response = ref<StandardizationPreviewResponse>(EMPTY_PREVIEW);
  const isLoading = ref(false);
  const isLoadingMore = ref(false);
  const errorMessage = ref("");

  let timeoutId: number | undefined;
  let requestSequence = 0;
  let activeController: AbortController | null = null;

  function shouldUseLightPreview(rawText: string): boolean {
    return rawText.length >= LARGE_TEXT_THRESHOLD;
  }

  function clearScheduledRequest() {
    if (timeoutId !== undefined) {
      globalThis.clearTimeout(timeoutId);
      timeoutId = undefined;
    }
  }

  function abortActiveRequest() {
    if (activeController) {
      activeController.abort();
      activeController = null;
    }
  }

  function resetPreview() {
    response.value = EMPTY_PREVIEW;
    isLoading.value = false;
    isLoadingMore.value = false;
    errorMessage.value = "";
  }

  function buildPreviewRequest(
    rawText: string,
    cursor: number | null,
  ): StandardizationPreviewRequest {
    return {
      raw_text: rawText,
      text_language: resolvePreviewTextLanguage(textLanguage?.value),
      segment_limit: INITIAL_PREVIEW_SEGMENT_LIMIT,
      cursor,
      include_language_analysis: !shouldUseLightPreview(rawText),
    };
  }

  async function requestPreviewPage(
    rawText: string,
    sequence: number,
    cursor: number | null,
    append: boolean,
  ) {
    const controller = new AbortController();
    activeController = controller;
    if (append) {
      isLoadingMore.value = true;
    } else {
      isLoading.value = true;
      errorMessage.value = "";
    }

    try {
      const next = await requestStandardizationPreview(
        buildPreviewRequest(rawText, cursor),
        { signal: controller.signal },
      );
      if (sequence !== requestSequence) {
        return;
      }
      response.value = append
        ? {
            ...next,
            segments: [...response.value.segments, ...next.segments],
          }
        : next;
      errorMessage.value = "";
    } catch (error) {
      if (sequence !== requestSequence) {
        return;
      }
      const aborted = error instanceof Error && error.name === "CanceledError";
      if (aborted) {
        return;
      }
      errorMessage.value = error instanceof Error ? error.message : "标准化预览失败";
    } finally {
      if (append) {
        if (sequence === requestSequence) {
          isLoadingMore.value = false;
        }
      } else if (sequence === requestSequence) {
        isLoading.value = false;
      }
      if (sequence === requestSequence && activeController === controller) {
        activeController = null;
      }
    }
  }

  async function runPreview(rawText: string, sequence: number) {
    await requestPreviewPage(rawText, sequence, null, false);
  }

  async function loadMore() {
    const cursor = response.value.next_cursor;
    if (cursor === null || isLoading.value || isLoadingMore.value) {
      return;
    }
    await requestPreviewPage(text.value, requestSequence, cursor, true);
  }

  watch(
    [text, textLanguage ?? ref("auto")],
    ([nextText]) => {
      clearScheduledRequest();
      abortActiveRequest();

      const trimmed = nextText.trim();
      requestSequence += 1;
      const currentSequence = requestSequence;
      if (!trimmed) {
        resetPreview();
        return;
      }

      isLoading.value = true;
      isLoadingMore.value = false;
      errorMessage.value = "";
      timeoutId = globalThis.setTimeout(() => {
        void runPreview(nextText, currentSequence);
      }, resolveDebounceMs(nextText));
    },
    { immediate: true },
  );

  onScopeDispose(() => {
    clearScheduledRequest();
    abortActiveRequest();
  });

  return {
    response,
    isLoading,
    errorMessage,
    isLoadingMore,
    loadMore,
    segments: computed<StandardizationPreviewSegment[]>(() => response.value.segments),
    totalSegments: computed(() => response.value.total_segments),
    analysisStage: computed(() => response.value.analysis_stage),
    resolvedDocumentLanguage: computed(() => response.value.resolved_document_language),
    nextCursor: computed(() => response.value.next_cursor),
    hasMore: computed(() => response.value.next_cursor !== null),
  };
}
