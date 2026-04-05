<script setup lang="ts">
import { ref, computed, onMounted, watch, nextTick } from 'vue'
import { ElMessage } from 'element-plus'
import { useEditSession } from '@/composables/useEditSession'
import { useInputDraft } from '@/composables/useInputDraft'
import { useInferenceParamsCache } from '@/composables/useInferenceParamsCache'
import { buildInitializeRequest } from '@/api/editSessionContract'
import WorkspaceEmptyState from '@/components/workspace/WorkspaceEmptyState.vue'
import WorkspaceInitProgress from '@/components/workspace/WorkspaceInitProgress.vue'
import WorkspaceFailedState from '@/components/workspace/WorkspaceFailedState.vue'
import WorkspaceInitForm from '@/components/workspace/WorkspaceInitForm.vue'
import WorkspaceDocumentEditor from '@/components/workspace/WorkspaceDocumentEditor.vue'
import WaveformStrip from '@/components/workspace/WaveformStrip.vue'
import TransportControlBar from '@/components/workspace/TransportControlBar.vue'
import RenderJobProgressBar from '@/components/workspace/RenderJobProgressBar.vue'
import { fetchVoices } from '@/api/voices'
import type { VoiceProfile } from '@/types/tts'
import { useRuntimeState } from '@/composables/useRuntimeState'
import { EditPen } from '@element-plus/icons-vue'

const { sessionStatus, discoverSession, initialize, clearSession, sourceDraftRevision } = useEditSession()
const { text, draftRevision, hasUnsent, markSentToSession } = useInputDraft()
const { currentRenderJob } = useRuntimeState()
const voices = ref<VoiceProfile[]>([])
const selectedVoice = computed(() => voices.value.find((voice) => voice.name === initParams.value.voice_id) ?? null)
const isApplyDisabled = computed(() => !text.value.trim() || !hasUnsent.value)

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
  ref_text: '',
  ref_lang: 'auto'
})

const { restoreCache, persistCacheWhenIdle, persistCacheNow } = useInferenceParamsCache()
const isRestoring = ref(false)

function buildCachePayload(): Record<string, unknown> {
  return {
    ...initParams.value,
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
  }, selectedVoice.value ? { refAudio: selectedVoice.value.ref_audio } : undefined))

  if (accepted) {
    sourceDraftRevision.value = draftRevision.value
    markSentToSession(draftRevision.value)
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
      <WorkspaceInitForm v-model="initParams" :voices="voices" @reset="handleResetParams" @save-now="handleSaveParams" />
    </aside>
    
    <!-- Right Panel: State Management -->
    <main class="w-full md:w-[65%] lg:w-[70%] flex flex-col min-w-0 min-h-0 overflow-hidden relative">
      <WorkspaceEmptyState 
        v-if="sessionStatus === 'empty'" 
        :text="text || '默认文段供测试'" 
        :can-submit="!!initParams.voice_id && !!text"
        @submit="handleInit" 
      />
      <WorkspaceInitProgress v-else-if="sessionStatus === 'initializing'" />
      <WorkspaceFailedState v-else-if="sessionStatus === 'failed'" />
      
      <div v-else-if="sessionStatus === 'ready'" class="w-full h-full flex flex-col pt-2 gap-4">
        <!-- Header with action button -->
        <div class="flex items-center justify-between shrink-0 mb-1">
          <h2 class="text-lg font-semibold text-foreground">轨道编辑</h2>
          <el-button
            type="primary"
            :icon="EditPen"
            :disabled="isApplyDisabled"
            @click="handleInit"
          >
            重新生成时间线
          </el-button>
        </div>

        <!-- Full document editor -->
        <WorkspaceDocumentEditor />

        <!-- Waveform visualizer / active segment tracker -->
        <WaveformStrip />

        <!-- Bottom transport control -->
        <div class="shrink-0 mb-4 bg-card rounded-card shadow-card border border-border p-4 flex items-center justify-between">
          <RenderJobProgressBar v-if="currentRenderJob && !['completed', 'failed', 'cancelled_partial'].includes(currentRenderJob.status)" />
          <TransportControlBar v-else />
        </div>
      </div>
    </main>
  </div>
</template>
