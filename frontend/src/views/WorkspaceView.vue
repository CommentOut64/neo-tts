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

const route = useRoute()
const {
  sessionStatus,
  discoverSession,
  initialize,
  clearSession,
  backfillInputDraftFromAppliedText,
  rememberSessionInitialText,
  sourceDraftRevision,
} = useEditSession()
const {
  text,
  textLanguage,
  draftRevision,
  lastSentToSessionRevision,
  source,
  setTextLanguage,
} = useInputDraft()
const { currentRenderJob } = useRuntimeState()
const parameterPanel = useParameterPanel()
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
  pause_length: number
  chunk_length: number
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
  pause_length: 0.3,
  chunk_length: 24,
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

  return {
    ...params,
    referenceSelectionsByBinding: upsertReferenceSelectionByBinding({
      selections: params.referenceSelectionsByBinding,
      voiceId: params.voice_id,
      entry: buildReferenceSelectionEntry({
        source: params.ref_source,
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
    pause_length: syncedParams.pause_length,
    chunk_length: syncedParams.chunk_length,
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
      if (typeof p.pause_length === 'number') nextParams.pause_length = p.pause_length
      if (typeof p.chunk_length === 'number') nextParams.chunk_length = p.chunk_length
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
