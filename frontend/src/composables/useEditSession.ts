import { ref } from 'vue'
import { getSnapshot, getTimeline, initializeSession, listSegments } from '@/api/editSession'
import type { EditSessionSnapshot, TimelineManifest, RenderJobSummary, InitializeRequest, RenderJobResponse, EditableSegment } from '@/types/editSession'
import { useRuntimeState } from './useRuntimeState'
import { extractStatusCode } from '@/api/requestSupport'
import { useTimeline } from "./useTimeline";
export type SessionStatus = 'empty' | 'initializing' | 'ready' | 'failed'

const sessionStatus = ref<SessionStatus>('empty')
const snapshot = ref<EditSessionSnapshot | null>(null)
const timeline = ref<TimelineManifest | null>(null)
const documentVersion = ref<number | null>(null)
const activeJob = ref<RenderJobSummary | null>(null)
const sourceDraftRevision = ref<number | null>(null)
const lastInitParams = ref<InitializeRequest | null>(null)
const segments = ref<EditableSegment[]>([])
const segmentsLoaded = ref(false)

export function useEditSession() {
  const runtimeState = useRuntimeState()

  async function discoverSession() {
    try {
      const data = await getSnapshot()
      snapshot.value = data
      sessionStatus.value = data.session_status || 'empty'
      documentVersion.value = data.document_version
      activeJob.value = data.active_job
      
      if (data.session_status === 'initializing' && activeJob.value) {
        runtimeState.trackJob(activeJob.value.job_id)
      } else if (data.session_status === 'ready') {
        await refreshTimeline()
      } else {
        segments.value = []
        segmentsLoaded.value = false
      }
    } catch (err) {
      if (extractStatusCode(err) === 404) {
        sessionStatus.value = 'empty'
        segments.value = []
        segmentsLoaded.value = false
      } else {
        sessionStatus.value = 'failed'
      }
    }
  }

  async function initialize(params: InitializeRequest): Promise<RenderJobResponse | null> {
    try {
      lastInitParams.value = params
      sessionStatus.value = 'initializing'
      const response = await initializeSession(params)
      runtimeState.trackJob(response.job_id)
      return response
    } catch (err) {
      sessionStatus.value = 'failed'
      console.error(err)
      return null
    }
  }

  async function refreshSnapshot() {
    const data = await getSnapshot()
    snapshot.value = data
    sessionStatus.value = data.session_status || 'empty'
    documentVersion.value = data.document_version
    activeJob.value = data.active_job
    if (sessionStatus.value !== 'ready') {
      segments.value = []
      segmentsLoaded.value = false
    }
  }

  async function refreshTimeline() {
    const { setTimeline } = useTimeline();
    const data = await getTimeline()
    timeline.value = data
    setTimeline(data);
    await loadAllSegments()
  }

  async function loadAllSegments() {
    if (sessionStatus.value !== 'ready') {
      segments.value = []
      segmentsLoaded.value = false
      return
    }

    const allSegments: EditableSegment[] = []
    let cursor: number | null = null

    while (true) {
      const page = await listSegments(1000, cursor)
      allSegments.push(...page.items)
      if (page.next_cursor === null) {
        break
      }
      cursor = page.next_cursor
    }

    segments.value = allSegments
    segmentsLoaded.value = true
  }

  return {
    sessionStatus,
    snapshot,
    timeline,
    documentVersion,
    activeJob,
    sourceDraftRevision,
    lastInitParams,
    segments,
    segmentsLoaded,

    discoverSession,
    initialize,
    refreshSnapshot,
    refreshTimeline,
    loadAllSegments,
  }
}
