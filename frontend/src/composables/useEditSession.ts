import { ref } from 'vue'
import {
  deleteSession,
  getGroups,
  getRenderProfiles,
  getSnapshot,
  getTimeline,
  getVoiceBindings,
  initializeSession,
  listEdges,
  listSegments,
} from '@/api/editSession'
import type {
  EditSessionSnapshot,
  TimelineManifest,
  RenderJobSummary,
  InitializeRequest,
  RenderJobResponse,
  EditableSegment,
  EditableEdge,
  SegmentGroup,
  RenderProfile,
  VoiceBinding,
} from '@/types/editSession'
import { useRuntimeState } from './useRuntimeState'
import { extractStatusCode } from '@/api/requestSupport'
import { useTimeline } from "./useTimeline";
import { useInputDraft } from './useInputDraft'
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
const edges = ref<EditableEdge[]>([])
const edgesLoaded = ref(false)
const groups = ref<SegmentGroup[]>([])
const renderProfiles = ref<RenderProfile[]>([])
const voiceBindings = ref<VoiceBinding[]>([])
const sessionResourcesLoaded = ref(false)

export function useEditSession() {
  const runtimeState = useRuntimeState()
  const inputDraft = useInputDraft()

  function getSnapshotHeadText(data: EditSessionSnapshot | null): string | null {
    if (!data || data.segments.length === 0) {
      return null
    }
    return data.segments.map((segment) => segment.raw_text).join('')
  }

  function syncDraftRevisionFromSnapshot(data: EditSessionSnapshot) {
    const sessionHeadText = getSnapshotHeadText(data)
    if (!sessionHeadText) {
      return
    }

    if (inputDraft.isEmpty.value) {
      inputDraft.backfillFromSession(sessionHeadText)
      sourceDraftRevision.value = inputDraft.draftRevision.value
      inputDraft.markSentToSession(inputDraft.draftRevision.value)
      return
    }

    if (inputDraft.text.value === sessionHeadText && sourceDraftRevision.value === null) {
      sourceDraftRevision.value = inputDraft.draftRevision.value
      inputDraft.markSentToSession(inputDraft.draftRevision.value)
    }
  }

  async function discoverSession() {
    try {
      const data = await getSnapshot()
      snapshot.value = data
      sessionStatus.value = data.session_status || 'empty'
      documentVersion.value = data.document_version
      activeJob.value = data.active_job
      
      if (data.session_status === 'initializing' && activeJob.value) {
        runtimeState.trackJob(activeJob.value, { initialRendering: true })
      } else if (data.session_status === 'ready') {
        syncDraftRevisionFromSnapshot(data)
        await refreshTimeline()
      } else {
        segments.value = []
        segmentsLoaded.value = false
        edges.value = []
        edgesLoaded.value = false
        groups.value = []
        renderProfiles.value = []
        voiceBindings.value = []
        sessionResourcesLoaded.value = false
        sourceDraftRevision.value = null
      }
    } catch (err) {
      if (extractStatusCode(err) === 404) {
        sessionStatus.value = 'empty'
        segments.value = []
        segmentsLoaded.value = false
        edges.value = []
        edgesLoaded.value = false
        groups.value = []
        renderProfiles.value = []
        voiceBindings.value = []
        sessionResourcesLoaded.value = false
        sourceDraftRevision.value = null
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
      runtimeState.trackJob(response, { initialRendering: true })
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
      edges.value = []
      edgesLoaded.value = false
      groups.value = []
      renderProfiles.value = []
      voiceBindings.value = []
      sessionResourcesLoaded.value = false
      if (sessionStatus.value === 'empty') {
        sourceDraftRevision.value = null
      }
    }
  }

  async function refreshTimeline() {
    const { setTimeline } = useTimeline();
    const data = await getTimeline()
    timeline.value = data
    setTimeline(data);
    console.info('[workspace] timeline refreshed', {
      timelineManifestId: data.timeline_manifest_id,
      documentId: data.document_id,
      documentVersion: data.document_version,
      sampleRate: data.sample_rate,
      playableSampleSpan: data.playable_sample_span,
      blockCount: data.block_entries.length,
      segmentCount: data.segment_entries.length,
      firstBlockAudioUrl: data.block_entries[0]?.audio_url ?? null,
    })
    await Promise.all([loadAllSegments(), loadAllEdges(), refreshSessionResources()])
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

  async function loadAllEdges() {
    if (sessionStatus.value !== 'ready') {
      edges.value = []
      edgesLoaded.value = false
      return
    }

    const allEdges: EditableEdge[] = []
    let cursor: number | null = null

    while (true) {
      const page = await listEdges(1000, cursor)
      allEdges.push(...page.items)
      if (page.next_cursor === null) {
        break
      }
      cursor = page.next_cursor
    }

    edges.value = allEdges
    edgesLoaded.value = true
  }

  async function refreshSessionResources() {
    if (sessionStatus.value !== 'ready') {
      groups.value = []
      renderProfiles.value = []
      voiceBindings.value = []
      sessionResourcesLoaded.value = false
      return
    }

    const [groupResponse, profileResponse, bindingResponse] = await Promise.all([
      getGroups(),
      getRenderProfiles(),
      getVoiceBindings(),
    ])

    groups.value = groupResponse.items
    renderProfiles.value = profileResponse.items
    voiceBindings.value = bindingResponse.items
    sessionResourcesLoaded.value = true
  }

  async function clearSession() {
    await deleteSession()
    sessionStatus.value = 'empty'
    snapshot.value = null
    timeline.value = null
    documentVersion.value = null
    activeJob.value = null
    segments.value = []
    segmentsLoaded.value = false
    edges.value = []
    edgesLoaded.value = false
    groups.value = []
    renderProfiles.value = []
    voiceBindings.value = []
    sessionResourcesLoaded.value = false
    sourceDraftRevision.value = null
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
    edges,
    edgesLoaded,
    groups,
    renderProfiles,
    voiceBindings,
    sessionResourcesLoaded,

    discoverSession,
    initialize,
    refreshSnapshot,
    refreshTimeline,
    loadAllSegments,
    loadAllEdges,
    refreshSessionResources,
    clearSession,
  }
}
