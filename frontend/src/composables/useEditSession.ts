import { ref } from 'vue'
import { getSnapshot, getTimeline, initializeSession } from '@/api/editSession'
import type { EditSessionSnapshot, TimelineManifest, RenderJobSummary, InitializeRequest, RenderJobResponse } from '@/types/editSession'
import { useRuntimeState } from './useRuntimeState'
import { extractStatusCode } from '@/api/requestSupport'

export type SessionStatus = 'empty' | 'initializing' | 'ready' | 'failed'

const sessionStatus = ref<SessionStatus>('empty')
const snapshot = ref<EditSessionSnapshot | null>(null)
const timeline = ref<TimelineManifest | null>(null)
const documentVersion = ref<number | null>(null)
const activeJob = ref<RenderJobSummary | null>(null)
const sourceDraftRevision = ref<number | null>(null)
const lastInitParams = ref<InitializeRequest | null>(null)

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
      }
    } catch (err) {
      if (extractStatusCode(err) === 404) {
        sessionStatus.value = 'empty'
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
  }

  async function refreshTimeline() {
    const data = await getTimeline()
    timeline.value = data
  }

  return {
    sessionStatus,
    snapshot,
    timeline,
    documentVersion,
    activeJob,
    sourceDraftRevision,
    lastInitParams,

    discoverSession,
    initialize,
    refreshSnapshot,
    refreshTimeline,
  }
}
