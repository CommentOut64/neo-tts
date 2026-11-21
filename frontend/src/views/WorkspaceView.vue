<script setup lang="ts">
import { ref, computed, onMounted, onBeforeUnmount, watch, nextTick, h } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useRoute } from 'vue-router'
import { useEditSession } from '@/composables/useEditSession'
import { useInputDraft, type InputTextLanguage } from '@/composables/useInputDraft'
import { useInferenceParamsCache } from '@/composables/useInferenceParamsCache'
import { buildInitializeRequest } from '@/api/editSessionContract'
import { uploadEditSessionReferenceAudio } from '@/api/editSession'
import WorkspaceEmptyState from '@/components/workspace/WorkspaceEmptyState.vue'
import WorkspaceFailedState from '@/components/workspace/WorkspaceFailedState.vue'
import WorkspaceInitForm from '@/components/workspace/WorkspaceInitForm.vue'
import ParameterPanelHost from '@/components/workspace/ParameterPanelHost.vue'
import WorkspaceEditorHost from '@/components/workspace/WorkspaceEditorHost.vue'
import MainActionButton from '@/components/workspace/MainActionButton.vue'
import WaveformStrip from '@/components/workspace/WaveformStrip.vue'
import TransportControlBar from '@/components/workspace/TransportControlBar.vue'
import RenderJobProgressBar from '@/components/workspace/RenderJobProgressBar.vue'
import { fetchVoices } from '@/api/voices'
import {
  buildReferenceSelectionEntry,
  resolveReferenceSelectionBySource,
  resolveReferenceSelectionForBinding,
  upsertReferenceSelectionByBinding,
} from '@/features/reference-binding'
import type { ReferenceSelectionByBinding, VoiceProfile } from '@/types/tts'
import { useRuntimeState } from '@/composables/useRuntimeState'
import { resolveInitializeReferenceAudioPath } from '@/utils/referenceAudioSelection'
import { useParameterPanel } from '@/composables/useParameterPanel'
import { useWorkspaceDialogState } from '@/composables/useWorkspaceDialogState'
import ExportDialog from '@/components/workspace/ExportDialog.vue'
import ParameterDraftConfirm from '@/components/workspace/ParameterDraftConfirm.vue'
import { resolveWorkspaceEntryAction } from '@/components/workspace/sessionHandoff'
import { buildTextLanguageResolutionDialogModel } from '@/utils/textLanguageResolution'
import { useProjectLifecycle } from '@/composables/useProjectLifecycle'
import { useWorkspaceDraftPersistence } from '@/composables/useWorkspaceDraftPersistence'
import { chooseNeoProjectFile, chooseNeoProjectSavePath } from '@/platform/projectFileDialog'
import type { ProjectPayload } from '@/types/projects'

const route = useRoute()
const {
  sessionStatus,
  discoverSession,
  initialize,
  clearSession,
  backfillInputDraftFromAppliedText,
  rememberSessionInitialText,
  sourceDraftRevision,
  snapshot,
  timeline,
  documentVersion,
  segments,
  edges,
  groups,
  renderProfiles,
  voiceBindings,
} = useEditSession()
const {
  text,
  textLanguage,
  draftRevision,
  lastSentToSessionRevision,
  source,
  setText,
  setTextLanguage,
} = useInputDraft()
const { currentRenderJob } = useRuntimeState()
const parameterPanel = useParameterPanel()
const workspaceDraftPersistence = useWorkspaceDraftPersistence()
const suppressRebuildPrompt = ref(false)
const restoredProjectSession = ref(false)
const { exportDialogVisible, closeExportDialog } = useWorkspaceDialogState()
const voices = ref<VoiceProfile[]>([])
const selectedVoice = computed(() => voices.value.find((voice) => voice.name === initParams.value.voice_id) ?? null)
const workspaceEntryAction = computed(() =>
  resolveWorkspaceEntryAction({
    sessionStatus: sessionStatus.value,
    hasInputText: text.value.trim().length > 0,
    inputSource: source.value,
    draftRevision: draftRevision.value,
    lastSentToSessionRevision: lastSentToSessionRevision.value,
    sourceDraftRevision: sourceDraftRevision.value,
    suppressRebuildPrompt: suppressRebuildPrompt.value,
  }),
)
const handoffConfirmVisible = ref(false)
const promptedRebuildRevision = ref<number | null>(null)
let pendingGuardedAction: (() => Promise<void>) | null = null

interface WorkspaceInitParams {
  voice_id: string
  speed: number
  temperature: number
  top_p: number
  top_k: number
  noise_scale: number
  pause_length: number
  text_lang: string
  text_split_method: string
  ref_source: 'preset' | 'custom'
  custom_ref_file: File | null
  custom_ref_path: string | null
  ref_text: string
  ref_lang: string
  referenceSelectionsByBinding: ReferenceSelectionByBinding
}

const initParams = ref<WorkspaceInitParams>({
  voice_id: '',
  speed: 1.0,
  temperature: 1.0,
  top_p: 1.0,
  top_k: 15,
  noise_scale: 0.35,
  pause_length: 0.3,
  text_lang: 'auto',
  text_split_method: 'cut5',
  ref_source: 'preset' as 'preset' | 'custom',
  custom_ref_file: null as File | null,
  custom_ref_path: null as string | null,
  ref_text: '',
  ref_lang: 'auto',
  referenceSelectionsByBinding: {},
})

const { restoreCache, persistCacheWhenIdle } = useInferenceParamsCache()
const isRestoring = ref(false)
const isBootstrappingWorkspace = ref(true)

function buildProjectPayload(): ProjectPayload {
  const documentId = snapshot.value?.document_id ?? `workspace-${Date.now()}`
  const version = snapshot.value?.document_version ?? documentVersion.value ?? 0
  const snapshotId = `${documentId}-head-${version}`
  const currentSegments = segments.value.length > 0 ? segments.value : snapshot.value?.segments ?? []
  const currentEdges = edges.value.length > 0 ? edges.value : snapshot.value?.edges ?? []
  const defaultBinding = voiceBindings.value.find(
    (binding) => binding.voice_binding_id === snapshot.value?.default_voice_binding_id,
  ) ?? voiceBindings.value[0]
  const modelIdentity = defaultBinding
    ? {
        model_id: defaultBinding.model_id ?? defaultBinding.model_key,
        model_revision: defaultBinding.model_revision ?? "",
        preset_id: defaultBinding.preset_id ?? defaultBinding.voice_id,
        preset_revision: defaultBinding.preset_revision ?? "",
        path_hint: { gpt: defaultBinding.gpt_path, sovits: defaultBinding.sovits_path },
      }
    : {}
  const assetById = new Map<string, Record<string, unknown>>()
  const assetRefs: Record<string, unknown>[] = []
  const referencesById = new Map<string, Record<string, unknown>>()
  const referenceHashes: Record<string, string> = {}
  for (const segment of currentSegments) {
    if (!segment.render_asset_id) continue
    assetById.set(segment.render_asset_id, {
      asset_id: segment.render_asset_id,
      kind: "formal",
      role: "segment",
      media_type: "audio/wav",
      codec: "pcm_s16le",
      byte_count: 0,
      ready: 0,
      metadata: { format_version: 1 },
    })
    assetRefs.push({ owner_type: "segment", owner_id: segment.segment_id, asset_id: segment.render_asset_id, purpose: "formal" })
  }
  const timelineId = timeline.value?.timeline_manifest_id ?? null
  if (timelineId) {
    assetById.set(timelineId, {
      asset_id: timelineId,
      kind: "timeline",
      media_type: "application/json",
      codec: "json",
      byte_count: 0,
      ready: 0,
      metadata: { format_version: 1 },
    })
    assetRefs.push({ owner_type: "project", owner_id: documentId, asset_id: timelineId, purpose: "timeline" })
  }
  const addSessionReference = (
    bindingKey: string,
    override: Record<string, unknown>,
  ) => {
    const referenceAssetId = typeof override.session_reference_asset_id === "string"
      ? override.session_reference_asset_id
      : ""
    if (!referenceAssetId) return
    const referenceId = `speaker-${referenceAssetId}`
    const audioAssetId = `reference-audio-${referenceAssetId}`
    const audioFingerprint = typeof override.reference_audio_fingerprint === "string"
      ? override.reference_audio_fingerprint
      : ""
    const textFingerprint = typeof override.reference_text_fingerprint === "string"
      ? override.reference_text_fingerprint
      : ""
    const language = typeof override.reference_language === "string"
      ? override.reference_language
      : ""
    const metadata = {
      reference_asset_id: referenceAssetId,
      session_id: documentId,
      binding_key: bindingKey,
      audio_path: typeof override.reference_audio_path === "string"
        ? override.reference_audio_path
        : null,
      reference_identity: typeof override.reference_identity === "string"
        ? override.reference_identity
        : null,
      reference_text: typeof override.reference_text === "string"
        ? override.reference_text
        : "",
      reference_language: language,
      reference_audio_fingerprint: audioFingerprint || null,
      reference_text_fingerprint: textFingerprint || null,
    }
    if (!assetById.has(audioAssetId)) {
      assetById.set(audioAssetId, {
        asset_id: audioAssetId,
        kind: "reference_audio",
        role: "speaker",
        media_type: "audio/wav",
        codec: "raw",
        byte_count: 0,
        ready: 0,
        metadata,
      })
    }
    if (!referencesById.has(referenceId)) {
      referencesById.set(referenceId, {
        reference_id: referenceId,
        role: "speaker",
        audio_asset_id: audioAssetId,
        text_hash: textFingerprint || null,
        language,
        source: "session_override",
        revision: version,
        status: "present",
        metadata: { ...metadata, binding_keys: [bindingKey] },
      })
    } else {
      const reference = referencesById.get(referenceId)!
      const metadataValue = reference.metadata
      const referenceMetadata = metadataValue && typeof metadataValue === "object"
        ? metadataValue as Record<string, unknown>
        : {}
      const bindingKeys = Array.isArray(referenceMetadata.binding_keys)
        ? referenceMetadata.binding_keys.filter((item): item is string => typeof item === "string")
        : []
      if (!bindingKeys.includes(bindingKey)) bindingKeys.push(bindingKey)
      reference.metadata = { ...referenceMetadata, binding_keys: bindingKeys }
    }
    assetRefs.push({ owner_type: "reference", owner_id: referenceId, asset_id: audioAssetId, purpose: "audio" })
    if (audioFingerprint || textFingerprint || language) {
      referenceHashes[bindingKey] = [audioFingerprint, textFingerprint, language].join("|")
    }
  }
  for (const profile of renderProfiles.value) {
    for (const [bindingKey, override] of Object.entries(profile.reference_overrides_by_binding ?? {})) {
      addSessionReference(bindingKey, override as unknown as Record<string, unknown>)
    }
  }
  for (const [bindingKey, selection] of Object.entries(initParams.value.referenceSelectionsByBinding)) {
    if (selection.source !== "custom") continue
    addSessionReference(bindingKey, {
      session_reference_asset_id: selection.session_reference_asset_id,
      reference_audio_path: selection.custom_ref_path,
      reference_text: selection.ref_text,
      reference_language: selection.ref_lang,
      reference_audio_fingerprint: selection.reference_audio_fingerprint,
      reference_text_fingerprint: selection.reference_text_fingerprint,
    })
  }
  const draftEnvelope = workspaceDraftPersistence.captureEnvelope({
    documentId,
    baseSnapshotId: snapshotId,
    inputRevision: draftRevision.value,
    parameterPatch: parameterPanel.draftPatch.value as Record<string, unknown>,
    inputDraft: {
      text: text.value,
      draftRevision: draftRevision.value,
      source: source.value,
      referenceDraft: {
        voice_id: initParams.value.voice_id,
        ref_source: initParams.value.ref_source,
        ref_text: initParams.value.ref_text,
        ref_lang: initParams.value.ref_lang,
      },
    },
  })
  return {
    project: {
      project_id: documentId,
      workspace_id: null,
      head_snapshot_id: snapshotId,
      timeline_manifest_id: timelineId,
      head_revision: version,
      baseline_revision: 0,
      timeline_revision: timeline.value?.timeline_version ?? 0,
      checkpoint_partial_revision: 0,
      checkpoint_working_revision: 0,
      input_revision: draftRevision.value,
      draft_revision: draftRevision.value,
      draft_payload: draftEnvelope,
      reference_hashes: referenceHashes,
      model_identity: modelIdentity,
      model_resolution_status: "exact",
    },
    snapshots: [{
      snapshot_id: snapshotId,
      kind: "head",
      revision: version,
      config: {
        default_render_profile_id: snapshot.value?.default_render_profile_id ?? null,
        default_voice_binding_id: snapshot.value?.default_voice_binding_id ?? null,
        render_profiles: renderProfiles.value,
        voice_bindings: voiceBindings.value,
        groups: groups.value,
      },
      segments: currentSegments.map((segment, position) => ({
        segment_id: segment.segment_id,
        position,
        group_id: segment.group_id,
        text: {
          stem: segment.stem,
          terminal_raw: segment.terminal_raw ?? "",
          terminal_closer_suffix: segment.terminal_closer_suffix ?? "",
          terminal_source: segment.terminal_source ?? "synthetic",
          text_language: segment.text_language,
        },
        binding: voiceBindings.value.find((binding) => binding.voice_binding_id === segment.voice_binding_id) ?? {},
        parameters: segment.inference_override,
        status: {
          render_status: segment.render_status,
          render_version: segment.render_version,
          segment_revision: segment.segment_revision,
        },
        formal_asset_id: segment.render_asset_id,
      })),
      edges: currentEdges.map((edge, position) => ({
        edge_id: edge.edge_id,
        position,
        from_segment_id: edge.left_segment_id,
        to_segment_id: edge.right_segment_id,
        policy: {
          pause_duration_seconds: edge.pause_duration_seconds,
          boundary_strategy: edge.boundary_strategy,
          effective_boundary_strategy: edge.effective_boundary_strategy,
        },
        status: { edge_status: edge.edge_status, edge_version: edge.edge_version },
      })),
      groups: groups.value.map((group, position) => ({
        group_id: group.group_id,
        position,
        binding: { voice_binding_id: group.voice_binding_id },
        parameters: { render_profile_id: group.render_profile_id },
      })),
    }],
    assets: [...assetById.values()],
    references: [...referencesById.values()],
    asset_refs: Array.from(
      new Map(
        assetRefs.map((item) => [
          [item.owner_type, item.owner_id, item.asset_id, item.purpose].join("\u0000"),
          item,
        ]),
      ).values(),
    ),
    blobs: [],
  }
}

const projectLifecycle = useProjectLifecycle({
  capture: buildProjectPayload,
  flushDraft: async () => {
    if (parameterPanel.hasDirty.value) {
      await parameterPanel.submitDraft()
    }
  },
  restore: async (project) => {
    suppressRebuildPrompt.value = true
    restoredProjectSession.value = Boolean(
      project && typeof project === "object" && (
        typeof project.head_snapshot_id === "string" ||
        typeof project.baseline_snapshot_id === "string"
      ),
    )
    const rawDraft = project && typeof project.draft_payload === "object"
      ? project.draft_payload
      : null
    const restoredEnvelope = workspaceDraftPersistence.restoreEnvelope(rawDraft)
    // Keep an existing local draft on conflict.  A server-captured draft is
    // only adopted when the input surface is empty, then formal state loads.
    try {
      if (restoredEnvelope) {
        setText(restoredEnvelope.inputDraft.text)
      }
      await discoverSession()
      if (!restoredEnvelope && appliedText.value) {
        backfillInputDraftFromAppliedText(appliedText.value)
      }
    } finally {
      promptedRebuildRevision.value = draftRevision.value
      suppressRebuildPrompt.value = false
    }
  },
})
const projectError = computed(() => projectLifecycle.lastError.value)
const projectFileId = projectLifecycle.projectId
const projectFileRevision = projectLifecycle.saveRevision
const projectFileDirty = projectLifecycle.dirty
const projectFileReadOnly = projectLifecycle.readOnly
const projectFileBusy = projectLifecycle.isBusy

async function handleProjectNew() {
  if (projectLifecycle.dirty.value) {
    try {
      await ElMessageBox.confirm("当前项目有未保存修改，确认新建项目并放弃这些修改吗？", "新建项目", {
        confirmButtonText: "新建",
        cancelButtonText: "取消",
        type: "warning",
      })
    } catch {
      return
    }
  }
  if (sessionStatus.value !== "empty") await clearSession()
  restoredProjectSession.value = false
  const response = await projectLifecycle.createNew()
  if (response) ElMessage.success("已创建新项目工作区")
}

async function handleProjectOpen() {
  const path = await chooseNeoProjectFile()
  if (!path) return
  const response = await projectLifecycle.open(path)
  if (response) ElMessage.success("项目已打开")
}

async function handleProjectSave() {
  const response = await projectLifecycle.save()
  if (response) ElMessage.success(response.dirty ? "项目已保存，但捕获后仍有新修改" : "项目已保存")
}

async function handleProjectSaveAs() {
  const path = await chooseNeoProjectSavePath(undefined, `${projectLifecycle.projectId.value ?? "project"}.neo`)
  if (!path) return
  const response = await projectLifecycle.saveAs(path)
  if (response) ElMessage.success("项目已另存为")
}

async function handleProjectClose() {
  if (projectLifecycle.dirty.value) {
    try {
      await ElMessageBox.confirm("当前项目有未保存修改，确认关闭并放弃这些修改吗？", "关闭项目", {
        confirmButtonText: "关闭",
        cancelButtonText: "取消",
        type: "warning",
      })
    } catch {
      return
    }
  }
  if (sessionStatus.value !== "empty") await clearSession()
  restoredProjectSession.value = false
  projectLifecycle.close()
}

watch(
  [draftRevision, () => parameterPanel.hasDirty.value, sessionStatus],
  () => {
    if (!isBootstrappingWorkspace.value && sessionStatus.value !== "empty") projectLifecycle.markDirty(true)
  },
)

function applyVoiceDefaults(params: WorkspaceInitParams, voice: VoiceProfile | null): WorkspaceInitParams {
  if (!voice?.defaults) {
    return params
  }

  return {
    ...params,
    speed: voice.defaults.speed,
    temperature: voice.defaults.temperature,
    top_p: voice.defaults.top_p,
    top_k: voice.defaults.top_k,
    noise_scale: voice.defaults.noise_scale ?? 0.35,
    pause_length: voice.defaults.pause_length,
  }
}

function applyReferenceSelectionForVoice(
  params: WorkspaceInitParams,
  voiceId: string,
): WorkspaceInitParams {
  const { selection } = resolveReferenceSelectionForBinding({
    voiceId,
    voices: voices.value,
    selections: params.referenceSelectionsByBinding,
  })

  return {
    ...params,
    voice_id: voiceId,
    ref_source: selection.source,
    custom_ref_path: selection.custom_ref_path,
    ref_text: selection.ref_text,
    ref_lang: selection.ref_lang,
  }
}

function syncReferenceSelectionForCurrentVoice(
  params: WorkspaceInitParams,
): WorkspaceInitParams {
  if (!params.voice_id) {
    return params
  }

  const currentSelection = Object.entries(params.referenceSelectionsByBinding).find(
    ([key]) => key.startsWith(`${params.voice_id}:`),
  )?.[1]

  return {
    ...params,
    referenceSelectionsByBinding: upsertReferenceSelectionByBinding({
      selections: params.referenceSelectionsByBinding,
      voiceId: params.voice_id,
      entry: buildReferenceSelectionEntry({
        source: params.ref_source,
        sessionReferenceAssetId: params.ref_source === 'custom'
          ? currentSelection?.session_reference_asset_id ?? null
          : null,
        referenceAudioFingerprint: params.ref_source === 'custom'
          ? currentSelection?.reference_audio_fingerprint ?? null
          : null,
        referenceTextFingerprint: params.ref_source === 'custom'
          ? currentSelection?.reference_text_fingerprint ?? null
          : null,
        customRefPath: params.custom_ref_path,
        refText: params.ref_text,
        refLang: params.ref_lang,
      }),
    }),
  }
}

function buildCachePayload(): Record<string, unknown> {
  const syncedParams = syncReferenceSelectionForCurrentVoice({
    ...initParams.value,
    custom_ref_file: null,
  })

  return {
    voice_id: syncedParams.voice_id,
    speed: syncedParams.speed,
    temperature: syncedParams.temperature,
    top_p: syncedParams.top_p,
    top_k: syncedParams.top_k,
    noise_scale: syncedParams.noise_scale,
    pause_length: syncedParams.pause_length,
    text_lang: syncedParams.text_lang,
    text_split_method: syncedParams.text_split_method,
    referenceSelectionsByBinding: syncedParams.referenceSelectionsByBinding,
  }
}

watch(
  initParams,
  () => {
    if (isRestoring.value) return
    persistCacheWhenIdle(buildCachePayload())
  },
  { deep: true }
)

watch(
  textLanguage,
  (nextLanguage) => {
    if (initParams.value.text_lang !== nextLanguage) {
      initParams.value.text_lang = nextLanguage
    }
  },
)

async function hydrateWorkspaceRoute() {
  try {
    const [, loadedVoices] = await Promise.all([discoverSession(), fetchVoices()])
    voices.value = loadedVoices
    parameterPanel.setVoices(loadedVoices)
    if (voices.value.length === 0) return

    isRestoring.value = true
    const cached = await restoreCache()
    const p = cached?.payload

    const cachedVoiceId = p && typeof p.voice_id === 'string'
      ? p.voice_id
      : p && typeof p.voice === 'string'
        ? p.voice
        : null
    const initialVoiceId = cachedVoiceId && voices.value.some(v => v.name === cachedVoiceId)
      ? cachedVoiceId
      : voices.value[0].name

    let nextParams: WorkspaceInitParams = {
      ...initParams.value,
      voice_id: initialVoiceId,
      referenceSelectionsByBinding:
        p && typeof p.referenceSelectionsByBinding === 'object' && p.referenceSelectionsByBinding
          ? (p.referenceSelectionsByBinding as ReferenceSelectionByBinding)
          : {},
    }

    nextParams = applyVoiceDefaults(
      nextParams,
      voices.value.find(v => v.name === initialVoiceId) ?? null,
    )

    if (p) {
      if (typeof p.speed === 'number') nextParams.speed = p.speed
      if (typeof p.temperature === 'number') nextParams.temperature = p.temperature
      if (typeof p.top_p === 'number') nextParams.top_p = p.top_p
      if (typeof p.top_k === 'number') nextParams.top_k = p.top_k
      if (typeof p.noise_scale === 'number') nextParams.noise_scale = p.noise_scale
      if (typeof p.pause_length === 'number') nextParams.pause_length = p.pause_length
      if (typeof p.text_split_method === 'string') nextParams.text_split_method = p.text_split_method
      if (typeof p.text_lang === 'string') nextParams.text_lang = p.text_lang
    }

    nextParams.text_lang = textLanguage.value
    initParams.value = applyReferenceSelectionForVoice(nextParams, initialVoiceId)

    await nextTick()
    isRestoring.value = false
  } catch (err) {
    isRestoring.value = false
    console.error('Failed to fill init params', err)
  } finally {
    await nextTick()
    isBootstrappingWorkspace.value = false
  }
}

function handleInitParamsChange(nextParams: WorkspaceInitParams) {
  initParams.value = syncReferenceSelectionForCurrentVoice({
    ...nextParams,
    text_lang: textLanguage.value,
  })
}

async function handleRequestTextLanguageChange(nextLanguage: InputTextLanguage) {
  const currentLanguage = textLanguage.value
  if (nextLanguage === currentLanguage) {
    return
  }

  const dialogModel = buildTextLanguageResolutionDialogModel(currentLanguage, nextLanguage)

  try {
    await ElMessageBox.confirm(
      h('div', { class: 'space-y-3 leading-6' }, [
        h('p', { class: 'text-sm text-foreground' }, dialogModel.intro),
        h('div', { class: 'rounded-md border border-border bg-muted/30 p-3' }, [
          h('p', { class: 'text-xs font-semibold text-foreground' }, dialogModel.currentOption.actionLabel),
          h('p', { class: 'mt-1 text-xs text-muted-fg' }, dialogModel.currentOption.description),
        ]),
        h('div', { class: 'rounded-md border border-accent/30 bg-accent/5 p-3' }, [
          h('p', { class: 'text-xs font-semibold text-foreground' }, dialogModel.nextOption.actionLabel),
          h('p', { class: 'mt-1 text-xs text-muted-fg' }, dialogModel.nextOption.description),
        ]),
      ]),
      dialogModel.title,
      {
        confirmButtonText: dialogModel.nextOption.actionLabel,
        cancelButtonText: dialogModel.currentOption.actionLabel,
        distinguishCancelAndClose: true,
        closeOnClickModal: false,
        closeOnPressEscape: false,
        lockScroll: false,
      },
    )
  } catch {
    return
  }

  setTextLanguage(nextLanguage)
}

onMounted(() => {
  void hydrateWorkspaceRoute()
})

onBeforeUnmount(() => {
  closeExportDialog()
})

watch(
  () => route.path,
  (path) => {
    if (path !== '/workspace') {
      closeExportDialog()
    }
  },
)

async function requestParameterDraftResolution(action: () => Promise<void>) {
  if (!parameterPanel.hasDirty.value) {
    await action()
    return
  }

  pendingGuardedAction = action
  handoffConfirmVisible.value = true
}

function clearPendingGuardedAction() {
  pendingGuardedAction = null
  handoffConfirmVisible.value = false
}

async function runPendingGuardedAction() {
  const action = pendingGuardedAction
  clearPendingGuardedAction()
  if (action) {
    await action()
  }
}

async function handleDiscardDraftAndContinue() {
  parameterPanel.discardDraft()
  await runPendingGuardedAction()
}

async function handleSubmitDraftAndContinue() {
  await parameterPanel.submitDraft()
  await runPendingGuardedAction()
}

const handleInit = async () => {
  if (!initParams.value.voice_id || !text.value) return
  if (projectFileReadOnly.value) {
    ElMessage.error("当前导入项目处于只读降级状态，不能重新初始化会话")
    return
  }
  // A restored project must use its installed active session.  If hydration
  // raced with the initial route probe, retry discovery instead of posting a
  // new initialize request against the imported project.
  if (restoredProjectSession.value && sessionStatus.value !== "ready") {
    await discoverSession()
    if (sessionStatus.value !== "ready") {
      ElMessage.error("项目会话尚未恢复，已取消重新初始化")
      return
    }
  }
  if (sessionStatus.value === 'ready') {
    try {
      await clearSession()
    } catch (err) {
      ElMessage.error(`清理旧会话失败: ${(err as Error).message}`)
      return
    }
  }

  let customReferenceAudioPath: string | undefined
  const effectiveReferenceSelection =
    initParams.value.ref_source === 'preset'
      ? resolveReferenceSelectionBySource({
          voiceId: initParams.value.voice_id,
          source: 'preset',
          voices: voices.value,
          selections: initParams.value.referenceSelectionsByBinding,
        }).selection
      : buildReferenceSelectionEntry({
          source: 'custom',
          customRefPath: initParams.value.custom_ref_path,
          refText: initParams.value.ref_text,
          refLang: initParams.value.ref_lang,
        })

  try {
    customReferenceAudioPath = await resolveInitializeReferenceAudioPath({
      refSource: effectiveReferenceSelection.source,
      presetReferenceAudioPath: selectedVoice.value?.ref_audio,
      customReferenceAudioPath: effectiveReferenceSelection.custom_ref_path,
      customReferenceAudioFile: initParams.value.custom_ref_file,
      upload: uploadEditSessionReferenceAudio,
      onUploaded: (response) => {
        initParams.value = syncReferenceSelectionForCurrentVoice({
          ...initParams.value,
          custom_ref_path: response.reference_audio_path,
          referenceSelectionsByBinding: upsertReferenceSelectionByBinding({
            selections: initParams.value.referenceSelectionsByBinding,
            voiceId: initParams.value.voice_id,
            entry: buildReferenceSelectionEntry({
              source: "custom",
              sessionReferenceAssetId: response.reference_asset_id,
              customRefPath: response.reference_audio_path,
              refText: initParams.value.ref_text,
              refLang: initParams.value.ref_lang,
              referenceAudioFingerprint: response.reference_audio_fingerprint,
              referenceTextFingerprint: response.reference_text_fingerprint,
            }),
          }),
        })
      },
    })
  } catch (err) {
    ElMessage.error(`参考音频上传失败: ${(err as Error).message}`)
    return
  }

  if (effectiveReferenceSelection.source === 'custom') {
    initParams.value = syncReferenceSelectionForCurrentVoice({
      ...initParams.value,
      custom_ref_path: customReferenceAudioPath ?? null,
    })
  } else {
    initParams.value = syncReferenceSelectionForCurrentVoice({
      ...initParams.value,
      ref_source: effectiveReferenceSelection.source,
      custom_ref_path: effectiveReferenceSelection.custom_ref_path,
      ref_text: effectiveReferenceSelection.ref_text,
      ref_lang: effectiveReferenceSelection.ref_lang,
      custom_ref_file: null,
    })
  }

  const accepted = await initialize(buildInitializeRequest({
    text: text.value,
    voiceId: initParams.value.voice_id,
    textLang: initParams.value.text_lang,
    speed: initParams.value.speed,
    temperature: initParams.value.temperature,
    topP: initParams.value.top_p,
    topK: initParams.value.top_k,
    noiseScale: initParams.value.noise_scale,
    pauseLength: initParams.value.pause_length,
    refSource: effectiveReferenceSelection.source,
    refText: effectiveReferenceSelection.ref_text,
    refLang: effectiveReferenceSelection.ref_lang,
    customRefFile: initParams.value.custom_ref_file,
    customRefPath: customReferenceAudioPath ?? null,
  }, selectedVoice.value ? { refAudio: selectedVoice.value.ref_audio } : undefined))

  if (accepted) {
    rememberSessionInitialText(text.value)
    backfillInputDraftFromAppliedText(text.value)
  }
}

async function promptWorkspaceRebuild(currentRevision: number) {
  promptedRebuildRevision.value = currentRevision

  await requestParameterDraftResolution(async () => {
    try {
      await ElMessageBox.confirm(
        '检测到文本输入页已有更新稿，是否用当前输入稿重建语音合成会话？',
        '用当前输入稿重建会话',
        {
          confirmButtonText: '重建会话',
          cancelButtonText: '暂不重建',
          type: 'warning',
          closeOnClickModal: false,
          closeOnPressEscape: false,
          lockScroll: false,
        },
      )
    } catch {
      return
    }

    await handleInit()
  })
}

const handleUploadCustomRef = async (file: File) => {
  try {
    const response = await uploadEditSessionReferenceAudio(file)
    initParams.value = syncReferenceSelectionForCurrentVoice({
      ...initParams.value,
      custom_ref_path: response.reference_audio_path,
      referenceSelectionsByBinding: upsertReferenceSelectionByBinding({
        selections: initParams.value.referenceSelectionsByBinding,
        voiceId: initParams.value.voice_id,
        entry: buildReferenceSelectionEntry({
          source: "custom",
          sessionReferenceAssetId: response.reference_asset_id,
          customRefPath: response.reference_audio_path,
          refText: initParams.value.ref_text,
          refLang: initParams.value.ref_lang,
          referenceAudioFingerprint: response.reference_audio_fingerprint,
          referenceTextFingerprint: response.reference_text_fingerprint,
        }),
      }),
    })
    ElMessage.success(`参考音频已上传：${response.filename}`)
  } catch (err) {
    initParams.value = syncReferenceSelectionForCurrentVoice({
      ...initParams.value,
      custom_ref_path: null,
    })
    ElMessage.error(`参考音频上传失败: ${(err as Error).message}`)
  }
}

const handleResetParams = () => {
  const v = voices.value.find((v) => v.name === initParams.value.voice_id)
  if (v && v.defaults) {
    initParams.value = syncReferenceSelectionForCurrentVoice({
      ...applyVoiceDefaults(initParams.value, v),
      ref_source: 'preset',
      custom_ref_path: null,
      ref_text: v.ref_text || '',
      ref_lang: v.ref_lang || 'auto',
    })
  }
}

watch(
  () => ({
    action: workspaceEntryAction.value,
    status: sessionStatus.value,
    revision: draftRevision.value,
  }),
  async ({ action, status, revision }) => {
    if (isBootstrappingWorkspace.value) {
      return
    }
    if (status !== 'ready' || action !== 'rebuild') {
      return
    }
    if (promptedRebuildRevision.value === revision) {
      return
    }

    await promptWorkspaceRebuild(revision)
  },
  { immediate: true },
)

</script>

<template>
  <div class="max-w-[1440px] mx-auto px-4 lg:px-8 py-6 h-[calc(100vh-3.5rem)] flex flex-col md:flex-row gap-6">
    <div class="fixed top-14 left-4 right-4 z-20 flex items-center gap-2 rounded-md border border-border bg-background/95 px-3 py-2 shadow-sm backdrop-blur">
      <button class="rounded border border-border px-2 py-1 text-xs" :disabled="projectFileBusy" @click="handleProjectNew">新建</button>
      <button class="rounded border border-border px-2 py-1 text-xs" :disabled="projectFileBusy" @click="handleProjectOpen">打开</button>
      <button class="rounded border border-border px-2 py-1 text-xs" :disabled="projectFileBusy || projectFileReadOnly" @click="handleProjectSave">保存</button>
      <button class="rounded border border-border px-2 py-1 text-xs" :disabled="projectFileBusy || projectFileReadOnly" @click="handleProjectSaveAs">另存为</button>
      <button class="rounded border border-border px-2 py-1 text-xs" :disabled="projectFileBusy" @click="handleProjectClose">关闭</button>
      <span class="ml-2 text-xs text-muted-fg">
        {{ projectFileId || '未命名项目' }} · rev {{ projectFileRevision }}
        <span v-if="projectFileDirty" class="text-amber-600">· 未保存</span>
        <span v-if="projectFileReadOnly" class="text-red-600">· 只读降级</span>
      </span>
      <span v-if="projectError" class="ml-auto max-w-[40%] truncate text-xs text-red-600" :title="projectError.message">
        {{ projectError.code }}: {{ projectError.message }}
      </span>
    </div>
    <!-- Left panel: parameters -->
    <aside class="w-full md:w-[35%] lg:w-[30%] md:max-h-[calc(100vh-8rem)] md:overflow-y-auto space-y-5 scrollbar-thin scrollbar-thumb-border scrollbar-track-transparent pr-1">
      <div v-if="isBootstrappingWorkspace"></div>
      <ParameterPanelHost
        v-else-if="sessionStatus === 'ready'"
        :voices="voices"
      />
      <WorkspaceInitForm
        v-else
        :model-value="initParams"
        :voices="voices"
        @update:model-value="handleInitParamsChange"
        @request-text-language-change="handleRequestTextLanguageChange"
        @upload-custom-ref="handleUploadCustomRef"
        @reset="handleResetParams"
      />
    </aside>
    
    <!-- Right Panel: State Management -->
    <main class="w-full md:w-[65%] lg:w-[70%] flex flex-col min-w-0 min-h-0 overflow-hidden relative">
      <div v-if="isBootstrappingWorkspace" class="h-full"></div>
      <WorkspaceEmptyState 
        v-else-if="sessionStatus === 'empty'" 
        :text="text" 
        :can-submit="!!initParams.voice_id && !!text"
        @submit="handleInit" 
      />
      <WorkspaceFailedState v-else-if="sessionStatus === 'failed'" />
      
      <div v-else-if="sessionStatus === 'ready' || sessionStatus === 'initializing'" class="w-full h-full flex flex-col pt-2 gap-3">
        <!-- 主画布：统一 Editor -->
        <WorkspaceEditorHost />

        <!-- 波形可视化 -->
        <WaveformStrip />

        <!-- 底部传输控制 + 主按钮 -->
        <div class="shrink-0 mb-4 flex items-center gap-3">
          <MainActionButton :session-status="sessionStatus" />

          <!-- 右侧进度/播放控制区域（去除了原本的外层包装 div） -->
          <div class="flex-1 min-w-0 flex">
            <RenderJobProgressBar v-if="currentRenderJob && !['completed', 'failed', 'cancelled_partial'].includes(currentRenderJob.status)" />
            <TransportControlBar v-else />
          </div>
        </div>
      </div>
    </main>
  </div>

  <ExportDialog v-model:visible="exportDialogVisible" />
  <ParameterDraftConfirm
    :visible="handoffConfirmVisible"
    @cancel="clearPendingGuardedAction"
    @discard="handleDiscardDraftAndContinue"
    @submit="handleSubmitDraftAndContinue"
  />
</template>
