<script setup lang="ts">
import { ref, computed, onMounted, watch, nextTick } from 'vue'
import { ElMessage } from 'element-plus'
import { useEditSession } from '@/composables/useEditSession'
import { useInputDraft } from '@/composables/useInputDraft'
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
import type { VoiceProfile } from '@/types/tts'
import { useRuntimeState } from '@/composables/useRuntimeState'
import { resolveInitializeReferenceAudioPath } from '@/utils/referenceAudioSelection'

const { sessionStatus, discoverSession, initialize, clearSession, sourceDraftRevision } = useEditSession()
const { text, draftRevision, markSentToSession } = useInputDraft()
const { currentRenderJob } = useRuntimeState()
const voices = ref<VoiceProfile[]>([])
const selectedVoice = computed(() => voices.value.find((voice) => voice.name === initParams.value.voice_id) ?? null)

// Parameter structure updated with reference audio options and initialized to match old behavior
const initParams = ref({
  voice_id: '',
  speed: 1.0,
  temperature: 1.0,
  top_p: 1.0,
  top_k: 15,
  pause_length: 0.3,
  chunk_length: 24,
  text_lang: 'auto',
  text_split_method: 'cut3',
  ref_source: 'preset' as 'preset' | 'custom',
  custom_ref_file: null as File | null,
  custom_ref_path: null as string | null,
  ref_text: '',
  ref_lang: 'auto'
})

const { restoreCache, persistCacheWhenIdle, persistCacheNow } = useInferenceParamsCache()
const isRestoring = ref(false)

function buildCachePayload(): Record<string, unknown> {
  return {
    ...initParams.value,
    custom_ref_file: null,
    voice: initParams.value.voice_id,
    refText: initParams.value.ref_text,
    refLang: initParams.value.ref_lang
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

onMounted(async () => {
  discoverSession()
  try {
    voices.value = await fetchVoices()
    if (voices.value.length === 0) return

    isRestoring.value = true
    const cached = await restoreCache()
    const p = cached?.payload

    if (p && typeof p.voice === 'string' && voices.value.some(v => v.name === p.voice)) {
      initParams.value.voice_id = p.voice as string
    } else {
      initParams.value.voice_id = voices.value[0].name
    }

    // Assign defaults from selected voice before applying cache
    const voiceInfo = voices.value.find(v => v.name === initParams.value.voice_id)
    if (voiceInfo && voiceInfo.defaults) {
      initParams.value.speed = voiceInfo.defaults.speed
      initParams.value.temperature = voiceInfo.defaults.temperature
      initParams.value.top_p = voiceInfo.defaults.top_p
      initParams.value.top_k = voiceInfo.defaults.top_k
      initParams.value.pause_length = voiceInfo.defaults.pause_length
      initParams.value.ref_text = voiceInfo.ref_text || ''
      initParams.value.ref_lang = voiceInfo.ref_lang || 'auto'
    }

    if (p) {
      if (typeof p.speed === 'number') initParams.value.speed = p.speed
      if (typeof p.temperature === 'number') initParams.value.temperature = p.temperature
      if (typeof p.top_p === 'number') initParams.value.top_p = p.top_p
      if (typeof p.top_k === 'number') initParams.value.top_k = p.top_k
      if (typeof p.pause_length === 'number') initParams.value.pause_length = p.pause_length
      if (typeof p.text_lang === 'string') initParams.value.text_lang = p.text_lang
      if (typeof p.text_split_method === 'string') initParams.value.text_split_method = p.text_split_method
      if (typeof p.chunk_length === 'number') initParams.value.chunk_length = p.chunk_length
      if (typeof p.refText === 'string') initParams.value.ref_text = p.refText
      if (typeof p.refLang === 'string') initParams.value.ref_lang = p.refLang
      if (typeof p.custom_ref_path === 'string') initParams.value.custom_ref_path = p.custom_ref_path
      
      if (typeof p.ref_source === 'string' && (p.ref_source === 'preset' || p.ref_source === 'custom')) {
        initParams.value.ref_source = p.ref_source
      }
    }

    await nextTick()
    isRestoring.value = false
  } catch (err) {
    isRestoring.value = false
    console.error('Failed to fill init params', err)
  }
})

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
  try {
    customReferenceAudioPath = await resolveInitializeReferenceAudioPath({
      refSource: initParams.value.ref_source,
      presetReferenceAudioPath: selectedVoice.value?.ref_audio,
      customReferenceAudioPath: initParams.value.custom_ref_path,
      customReferenceAudioFile: initParams.value.custom_ref_file,
      upload: uploadEditSessionReferenceAudio,
    })
  } catch (err) {
    ElMessage.error(`参考音频上传失败: ${(err as Error).message}`)
    return
  }

  if (initParams.value.ref_source === 'custom') {
    initParams.value.custom_ref_path = customReferenceAudioPath ?? null
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
    textSplitMethod: initParams.value.text_split_method,
    refSource: initParams.value.ref_source,
    refText: initParams.value.ref_text,
    refLang: initParams.value.ref_lang,
    customRefFile: initParams.value.custom_ref_file,
    customRefPath: customReferenceAudioPath ?? null,
  }, selectedVoice.value ? { refAudio: selectedVoice.value.ref_audio } : undefined))

  if (accepted) {
    sourceDraftRevision.value = draftRevision.value
    markSentToSession(draftRevision.value)
  }
}

const handleUploadCustomRef = async (file: File) => {
  try {
    const response = await uploadEditSessionReferenceAudio(file)
    initParams.value.custom_ref_path = response.reference_audio_path
    ElMessage.success(`参考音频已上传：${response.filename}`)
  } catch (err) {
    initParams.value.custom_ref_path = null
    ElMessage.error(`参考音频上传失败: ${(err as Error).message}`)
  }
}

const handleResetParams = () => {
  const v = voices.value.find((v) => v.name === initParams.value.voice_id)
  if (v && v.defaults) {
    initParams.value.speed = v.defaults.speed
    initParams.value.temperature = v.defaults.temperature
    initParams.value.top_p = v.defaults.top_p
    initParams.value.top_k = v.defaults.top_k
    initParams.value.pause_length = v.defaults.pause_length
    initParams.value.ref_text = v.ref_text || ''
    initParams.value.ref_lang = v.ref_lang || 'auto'
    initParams.value.ref_source = 'preset'
    initParams.value.custom_ref_file = null
    initParams.value.custom_ref_path = null
  }
}

const handleSaveParams = async () => {
  try {
    await persistCacheNow(buildCachePayload())
    ElMessage.success('配置已保存')
  } catch (err: unknown) {
    ElMessage.error(`保存失败: ${(err as Error).message}`)
  }
}
</script>

<template>
  <div class="max-w-[1440px] mx-auto px-4 lg:px-8 py-6 h-[calc(100vh-3.5rem)] flex flex-col md:flex-row gap-6">
    <!-- Left panel: parameters -->
    <aside class="w-full md:w-[35%] lg:w-[30%] md:max-h-[calc(100vh-8rem)] md:overflow-y-auto space-y-5 scrollbar-thin scrollbar-thumb-border scrollbar-track-transparent pr-1">
      <ParameterPanelHost
        v-if="sessionStatus === 'ready'"
        :voices="voices"
      />
      <WorkspaceInitForm
        v-else
        v-model="initParams"
        :voices="voices"
        @upload-custom-ref="handleUploadCustomRef"
        @reset="handleResetParams"
        @save-now="handleSaveParams"
      />
    </aside>
    
    <!-- Right Panel: State Management -->
    <main class="w-full md:w-[65%] lg:w-[70%] flex flex-col min-w-0 min-h-0 overflow-hidden relative">
      <WorkspaceEmptyState 
        v-if="sessionStatus === 'empty'" 
        :text="text || '默认文段供测试'" 
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
</template>
