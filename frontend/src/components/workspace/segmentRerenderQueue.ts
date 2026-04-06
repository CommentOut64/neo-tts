import { ref } from "vue";

export type SegmentRerenderTerminalStatus =
  | "completed"
  | "failed"
  | "paused"
  | "cancelled_partial";

export interface SegmentRerenderJobHandle {
  jobId: string;
  waitForTerminal: () => Promise<SegmentRerenderTerminalStatus>;
  cancel: () => Promise<void>;
}

interface CreateSegmentRerenderQueueOptions {
  getDraftText: (segmentId: string) => string | undefined;
  submitSegmentUpdate: (
    segmentId: string,
    text: string,
  ) => Promise<SegmentRerenderJobHandle>;
  clearDraft: (segmentId: string) => void;
  refreshSession: () => Promise<void>;
  setLockedSegments?: (segmentIds: string[]) => void;
  onError?: (error: unknown, segmentId: string | null) => void;
}

export function createSegmentRerenderQueue(
  options: CreateSegmentRerenderQueueOptions,
) {
  const isProcessing = ref(false);
  const isCancelling = ref(false);
  const totalJobs = ref(0);
  const currentJobIndex = ref(0);

  let activeJob: SegmentRerenderJobHandle | null = null;
  let cancelRequested = false;

  async function run(segmentIds: string[]) {
    if (isProcessing.value || segmentIds.length === 0) {
      return;
    }

    isProcessing.value = true;
    isCancelling.value = false;
    totalJobs.value = segmentIds.length;
    currentJobIndex.value = 0;
    cancelRequested = false;

    let completedAny = false;

    try {
      for (let index = 0; index < segmentIds.length; index += 1) {
        if (cancelRequested) {
          break;
        }

        currentJobIndex.value = index;
        const segmentId = segmentIds[index];
        const draftText = options.getDraftText(segmentId);

        if (draftText === undefined) {
          continue;
        }

        options.setLockedSegments?.([segmentId]);

        try {
          activeJob = await options.submitSegmentUpdate(segmentId, draftText);
          const status = await activeJob.waitForTerminal();

          if (status === "completed") {
            options.clearDraft(segmentId);
            completedAny = true;
            continue;
          }

          if (status === "paused" || status === "cancelled_partial") {
            cancelRequested = true;
          }

          break;
        } catch (error) {
          options.onError?.(error, segmentId);
          break;
        } finally {
          activeJob = null;
          options.setLockedSegments?.([]);
        }
      }

      if (completedAny) {
        await options.refreshSession();
      }
    } finally {
      activeJob = null;
      cancelRequested = false;
      isProcessing.value = false;
      isCancelling.value = false;
      options.setLockedSegments?.([]);
    }
  }

  async function requestCancel() {
    if (!isProcessing.value || isCancelling.value) {
      return;
    }

    cancelRequested = true;
    isCancelling.value = true;

    if (!activeJob) {
      return;
    }

    try {
      await activeJob.cancel();
    } catch (error) {
      options.onError?.(error, null);
    }
  }

  return {
    isProcessing,
    isCancelling,
    totalJobs,
    currentJobIndex,
    run,
    requestCancel,
  };
}
