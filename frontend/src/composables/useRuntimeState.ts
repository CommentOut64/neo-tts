import { ref, computed } from 'vue'
import type { 
  RenderJob, 
  RenderJobEventType, 
  ProgressiveSegment, 
  SegmentsInitializedPayload, 
  SegmentCompletedPayload
} from '@/types/editSession'
import {
  subscribeRenderJobEvents,
  getRenderJob,
  pauseRenderJob,
  cancelRenderJob,
} from "@/api/editSession";

export type SseConnectionState = 'connected' | 'disconnected' | 'polling'

const currentRenderJob = ref<RenderJob | null>(null)
const currentExportJob = ref<any | null>(null)
const sseConnectionState = ref<SseConnectionState>('disconnected')
const progressiveSegments = ref<ProgressiveSegment[]>([])
const isInitialRendering = ref<boolean>(false)
const lockedSegmentIds = ref<Set<string>>(new Set())

let unsubscribeSse: (() => void) | null = null
let pollingIntervalId: ReturnType<typeof setInterval> | null = null
let finishPromise: Promise<void> | null = null

export function useRuntimeState() {
  const canMutate = computed(() => {
    return currentRenderJob.value === null || 
      ['completed', 'failed', 'cancelled_partial'].includes(currentRenderJob.value.status)
  })

  function trackJob(jobId: string) {
    if (unsubscribeSse) unsubscribeSse()
    if (pollingIntervalId) {
      clearInterval(pollingIntervalId)
      pollingIntervalId = null
    }

    finishPromise = null
    currentRenderJob.value = null
    progressiveSegments.value = []
    isInitialRendering.value = true
    sseConnectionState.value = 'connected'

    unsubscribeSse = subscribeRenderJobEvents(jobId, {
      onEvent: (type: RenderJobEventType, payload: any) => {
        if (type === 'job_state_changed') {
          currentRenderJob.value = payload as RenderJob
          if (['completed', 'failed', 'cancelled_partial'].includes(currentRenderJob.value.status)) {
            finishInitialRendering()
          }
        } else if (type === 'segments_initialized') {
          const initPayload = payload as SegmentsInitializedPayload
          progressiveSegments.value = initPayload.segments.map((seg: any) => ({
            segmentId: seg.segment_id,
            orderKey: seg.order_key,
            rawText: seg.raw_text,
            renderStatus: seg.render_status,
            renderAssetId: null
          })).sort((a: any, b: any) => a.orderKey - b.orderKey)
        } else if (type === 'segment_completed') {
          const compPayload = payload as SegmentCompletedPayload
          const seg = progressiveSegments.value.find(s => s.segmentId === compPayload.segment_id)
          if (seg) {
            seg.renderStatus = 'completed'
            seg.renderAssetId = compPayload.render_asset_id
          }
        } else if (type === 'job_completed' || type === 'job_failed' || type === 'job_cancelled_partial') {
          void finishInitialRendering()
        }
      },
      onError: (err: any) => {
        console.warn('SSE disconnected, falling back to polling', err)
        sseConnectionState.value = 'polling'
        if (unsubscribeSse) unsubscribeSse()
        unsubscribeSse = null
        startPolling(jobId)
      }
    })
  }

  function startPolling(jobId: string) {
    if (pollingIntervalId) {
      clearInterval(pollingIntervalId)
    }

    pollingIntervalId = setInterval(async () => {
      try {
        const job = await getRenderJob(jobId)
        currentRenderJob.value = job
        if (['completed', 'failed', 'cancelled_partial'].includes(job.status)) {
          if (pollingIntervalId) {
            clearInterval(pollingIntervalId)
            pollingIntervalId = null
          }
          void finishInitialRendering()
        }
      } catch (err) {
        console.error('Polling error', err)
      }
    }, 2000)
  }

  async function finishInitialRendering() {
    if (finishPromise) {
      await finishPromise
      return
    }

    finishPromise = (async () => {
      if (unsubscribeSse) {
        unsubscribeSse()
        unsubscribeSse = null
      }
      if (pollingIntervalId) {
        clearInterval(pollingIntervalId)
        pollingIntervalId = null
      }

      try {
        const module = await import('./useEditSession')
        const editSession = module.useEditSession()
        await editSession.refreshSnapshot()
        if (editSession.sessionStatus.value === 'ready') {
          await editSession.refreshTimeline()
        }
      } catch (err) {
        console.error('Failed to refresh edit session after render job settled', err)
      } finally {
        progressiveSegments.value = []
        isInitialRendering.value = false
        sseConnectionState.value = 'disconnected'
      }
    })()

    try {
      await finishPromise
    } finally {
      finishPromise = null
    }
  }

  async function pauseJob() {
    if (currentRenderJob.value) {
      await pauseRenderJob(currentRenderJob.value.job_id);
    }
  }

  async function cancelJob() {
    if (currentRenderJob.value) {
      await cancelRenderJob(currentRenderJob.value.job_id);
    }
  }

  return {
    currentRenderJob,
    currentExportJob,
    sseConnectionState,
    progressiveSegments,
    isInitialRendering,
    lockedSegmentIds,
    canMutate,
    trackJob,
    pauseJob,
    cancelJob,
  };
}
