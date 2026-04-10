import { computed, ref } from 'vue'
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
import { useInputDraft, type InputDraftSource } from './useInputDraft'
import { useWorkspaceDraftPersistence } from './useWorkspaceDraftPersistence'
import { useWorkspaceLightEdit } from './useWorkspaceLightEdit'
export type SessionStatus = 'empty' | 'initializing' | 'ready' | 'failed'
export type EndSessionInputSource = InputDraftSource | 'manual'
export type FormalStateStatus = 'idle' | 'refreshing' | 'ready' | 'error'

export interface ResolveInputDraftSyncActionInput {
  sessionHeadText: string | null
  inputText: string
  inputSource: InputDraftSource
  isInputEmpty: boolean
  draftRevision: number
  lastSentToSessionRevision: number | null
  sourceDraftRevision: number | null
}

export function resolveInputDraftSyncAction(
  input: ResolveInputDraftSyncActionInput,
): 'backfill' | 'adopt' | 'noop' {
  if (!input.sessionHeadText) {
    return 'noop'
  }

  const isExplicitManualDraft =
    input.inputSource === 'manual' &&
    (
      input.draftRevision > 0 ||
      input.lastSentToSessionRevision !== null ||
      input.sourceDraftRevision !== null
    )

  if (input.isInputEmpty) {
    if (isExplicitManualDraft) {
      return 'noop'
    }
    return 'backfill'
  }

  if (input.inputSource === 'input_handoff') {
    return 'noop'
  }

  if (input.inputText === input.sessionHeadText && input.sourceDraftRevision === null) {
    return 'adopt'
  }

  const isTrackingSessionDraft = input.inputSource === 'applied_text'
    && input.sourceDraftRevision !== null
    && input.draftRevision === input.sourceDraftRevision
    && input.lastSentToSessionRevision === input.draftRevision

  if (isTrackingSessionDraft && input.inputText !== input.sessionHeadText) {
    return 'backfill'
  }

  return 'noop'
}

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
const formalStateStatus = ref<FormalStateStatus>('idle')
const formalStateEpoch = ref(0)

interface FormalSessionBundle {
  snapshot: EditSessionSnapshot
  timeline: TimelineManifest | null
  segments: EditableSegment[]
  edges: EditableEdge[]
  groups: SegmentGroup[]
  renderProfiles: RenderProfile[]
  voiceBindings: VoiceBinding[]
}

export function useEditSession() {
  const runtimeState = useRuntimeState()
  const inputDraft = useInputDraft()
  const workspaceDraftPersistence = useWorkspaceDraftPersistence()
  const lightEdit = useWorkspaceLightEdit()

  function getSnapshotHeadText(data: EditSessionSnapshot | null): string | null {
    if (!data || data.segments.length === 0) {
      return null
    }
    return data.segments.map((segment) => segment.raw_text).join('')
  }

  const sourceText = computed(() => {
    return snapshot.value?.source_text ?? lastInitParams.value?.raw_text ?? null
  })
  const sessionInitialText = computed(() => sourceText.value)
  const appliedText = computed(() => getSnapshotHeadText(snapshot.value))

  function markDraftAsSyncedToSession() {
    sourceDraftRevision.value = inputDraft.draftRevision.value
    inputDraft.markSentToSession(inputDraft.draftRevision.value)
  }

  function backfillInputDraftFromAppliedText(sessionHeadText: string) {
    inputDraft.backfillFromAppliedText(sessionHeadText)
    markDraftAsSyncedToSession()
  }

  function rememberSessionInitialText(nextText: string) {
    inputDraft.rememberLastSessionInitialText(nextText)
  }

  function syncDraftRevisionFromSnapshot(data: EditSessionSnapshot) {
    const sessionHeadText = getSnapshotHeadText(data)
    const action = resolveInputDraftSyncAction({
      sessionHeadText,
      inputText: inputDraft.text.value,
      inputSource: inputDraft.source.value,
      isInputEmpty: inputDraft.isEmpty.value,
      draftRevision: inputDraft.draftRevision.value,
      lastSentToSessionRevision: inputDraft.lastSentToSessionRevision.value,
      sourceDraftRevision: sourceDraftRevision.value,
    })

    if ((action === 'backfill' || action === 'adopt') && sessionHeadText) {
      backfillInputDraftFromAppliedText(sessionHeadText)
    }
  }

  function resetSessionState() {
    const { setTimeline } = useTimeline()
    sessionStatus.value = 'empty'
    snapshot.value = null
    timeline.value = null
    setTimeline(null)
    documentVersion.value = null
    activeJob.value = null
    lastInitParams.value = null
    segments.value = []
    segmentsLoaded.value = false
    edges.value = []
    edgesLoaded.value = false
    groups.value = []
    renderProfiles.value = []
    voiceBindings.value = []
    sessionResourcesLoaded.value = false
    formalStateStatus.value = 'idle'
    sourceDraftRevision.value = null
    lightEdit.clearAll()
  }

  function clearFormalResources() {
    const { setTimeline } = useTimeline()
    timeline.value = null
    setTimeline(null)
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

  function applySnapshotMeta(data: EditSessionSnapshot) {
    snapshot.value = data
    sessionStatus.value = data.session_status || 'empty'
    documentVersion.value = data.document_version
    activeJob.value = data.active_job
  }

  function buildCurrentFormalSessionResult() {
    return {
      snapshot: snapshot.value,
      timeline: timeline.value,
      edges: edges.value,
    }
  }

  function applyFormalSessionBundle(bundle: FormalSessionBundle) {
    const { setTimeline } = useTimeline()

    applySnapshotMeta(bundle.snapshot)
    timeline.value = bundle.timeline
    setTimeline(bundle.timeline)
    segments.value = bundle.segments
    segmentsLoaded.value = true
    edges.value = bundle.edges
    edgesLoaded.value = true
    groups.value = bundle.groups
    renderProfiles.value = bundle.renderProfiles
    voiceBindings.value = bundle.voiceBindings
    sessionResourcesLoaded.value = true
  }

  async function loadAllSegmentsPage() {
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

    return allSegments
  }

  async function loadAllEdgesPage() {
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

    return allEdges
  }

  async function loadFormalSessionBundle(snapshotData: EditSessionSnapshot): Promise<FormalSessionBundle> {
    const [
      timelineData,
      allSegments,
      allEdges,
      groupResponse,
      profileResponse,
      bindingResponse,
    ] = await Promise.all([
      getTimeline(),
      loadAllSegmentsPage(),
      loadAllEdgesPage(),
      getGroups(),
      getRenderProfiles(),
      getVoiceBindings(),
    ])

    return {
      snapshot: snapshotData,
      timeline: timelineData,
      segments: allSegments,
      edges: allEdges,
      groups: groupResponse.items,
      renderProfiles: profileResponse.items,
      voiceBindings: bindingResponse.items,
    }
  }

  async function discoverSession() {
    try {
      const data = await getSnapshot()
      applySnapshotMeta(data)
      
      if (data.session_status === 'initializing' && activeJob.value) {
        formalStateStatus.value = 'idle'
        clearFormalResources()
        runtimeState.trackJob(activeJob.value, { initialRendering: true })
      } else if (data.session_status === 'ready') {
        await refreshFormalSessionState({ snapshotData: data })
      } else {
        formalStateStatus.value = 'idle'
        clearFormalResources()
        if (data.session_status === 'empty') {
          lastInitParams.value = null
        }
      }
    } catch (err) {
      if (extractStatusCode(err) === 404) {
        resetSessionState()
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
    applySnapshotMeta(data)
    if (sessionStatus.value === 'ready') {
      syncDraftRevisionFromSnapshot(data)
      return
    }

    if (sessionStatus.value !== 'ready') {
      if (sessionStatus.value === 'empty') {
        resetSessionState()
      } else {
        formalStateStatus.value = 'idle'
        clearFormalResources()
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

  async function refreshFormalSessionState(options?: { snapshotData?: EditSessionSnapshot }) {
    const requestEpoch = formalStateEpoch.value + 1
    formalStateEpoch.value = requestEpoch
    formalStateStatus.value = 'refreshing'

    try {
      const snapshotData = options?.snapshotData ?? await getSnapshot()
      const nextStatus = snapshotData.session_status || 'empty'

      if (nextStatus !== 'ready') {
        if (requestEpoch !== formalStateEpoch.value) {
          return buildCurrentFormalSessionResult()
        }

        applySnapshotMeta(snapshotData)
        if (nextStatus === 'empty') {
          resetSessionState()
        } else {
          clearFormalResources()
          formalStateStatus.value = 'idle'
        }
        return buildCurrentFormalSessionResult()
      }

      const bundle = await loadFormalSessionBundle(snapshotData)
      if (requestEpoch !== formalStateEpoch.value) {
        return buildCurrentFormalSessionResult()
      }

      applyFormalSessionBundle(bundle)
      syncDraftRevisionFromSnapshot(bundle.snapshot)
      formalStateStatus.value = 'ready'
      return buildCurrentFormalSessionResult()
    } catch (error) {
      if (requestEpoch === formalStateEpoch.value) {
        formalStateStatus.value = 'error'
      }
      throw error
    }
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
    const documentIdToClear = snapshot.value?.document_id ?? segments.value[0]?.document_id ?? null
    if (documentIdToClear) {
      workspaceDraftPersistence.clearSnapshot(documentIdToClear)
    }

    await deleteSession()
    resetSessionState()
  }

  async function endSession(target?: {
    nextInputText: string
    nextInputSource: EndSessionInputSource
  }) {
    await clearSession()

    if (!target) {
      return
    }

    if (target.nextInputSource === 'applied_text') {
      inputDraft.backfillFromAppliedText(target.nextInputText)
      return
    }

    if (target.nextInputSource === 'input_handoff') {
      inputDraft.handoffFromWorkspace(target.nextInputText)
      return
    }

    inputDraft.setText(target.nextInputText)
  }

  return {
    sessionStatus,
    snapshot,
    sourceText,
    sessionInitialText,
    appliedText,
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
    formalStateStatus,
    isFormalStateRefreshing: computed(() => formalStateStatus.value === 'refreshing'),
    formalStateEpoch,

    discoverSession,
    initialize,
    refreshSnapshot,
    refreshTimeline,
    refreshFormalSessionState,
    loadAllSegments,
    loadAllEdges,
    refreshSessionResources,
    backfillInputDraftFromAppliedText,
    rememberSessionInitialText,
    endSession,
    clearSession,
  }
}
