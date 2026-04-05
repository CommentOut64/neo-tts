<script setup lang="ts">
import { ref, computed, watch, nextTick } from 'vue'
import { ElMessage } from 'element-plus'
import type { VoiceProfile, AudioHistoryItem } from '@/types/tts'
import { synthesizeSpeechWithMeta, deleteSynthesisResult } from '@/api/tts'
import { fetchVoices } from '@/api/voices'
import { useAudioQueue } from '@/composables/useAudioQueue'
import VoiceSelect from '@/components/VoiceSelect.vue'
import InferenceSettingsPanel from '@/components/InferenceSettingsPanel.vue'
import TtsForm from '@/components/TtsForm.vue'
import AudioResultPanel from '@/components/AudioResultPanel.vue'
import { useInferenceRuntime } from '@/composables/useInferenceRuntime'
import { useInferenceParamsCache } from '@/composables/useInferenceParamsCache'
import InferenceControlBar from '@/components/InferenceControlBar.vue'

// Models
const voices = ref<VoiceProfile[]>([])
const selectedVoiceName = ref('')
const selectedVoice = computed(() =>
  voices.value.find(v => v.name === selectedVoiceName.value) ?? null
)

// Reference audio
const refSource = ref<'preset' | 'custom'>('preset')
const customRefFile = ref<File | null>(null)
const refText = ref('')
const refLang = ref('auto')

// Inference params
const params = ref({
  speed: 1.0,
  temperature: 1.0,
  top_p: 1.0,
  top_k: 15,
  pause_length: 0.3,
  text_lang: 'auto',
  text_split_method: 'cut5',
  chunk_length: 24,
})

// Text + state
const inputText = ref('')
const isInferring = ref(false)

// Audio queue
const { history: audioHistory, pushPending, markDone, markError, remove: removeFromQueue } = useAudioQueue()

// 推理运行时（单例）
const {
  progress,
  isProgressStreamConnected,
  runtimeError,
  connectProgressStream,
  requestForcePause,
  requestCleanupResiduals,
  clearRuntimeError,
} = useInferenceRuntime()

// 参数缓存
const {
  cacheError,
  restoreCache,
  persistCacheWhenIdle,
  persistCacheNow,
} = useInferenceParamsCache()

// 缓存恢复守卫
const isRestoring = ref(false)

// Sync params when voice changes
watch(selectedVoice, (voice) => {
  if (!voice) return
  params.value = {
    speed: voice.defaults.speed,
    temperature: voice.defaults.temperature,
    top_p: voice.defaults.top_p,
    top_k: voice.defaults.top_k,
    pause_length: voice.defaults.pause_length,
    text_lang: 'auto',
    text_split_method: 'cut5',
    chunk_length: 24,
  }
  refText.value = voice.ref_text
  refLang.value = voice.ref_lang
  refSource.value = 'preset'
  customRefFile.value = null
})

function buildCachePayload(): Record<string, unknown> {
  return {
    ...params.value,
    voice: selectedVoiceName.value,
    refText: refText.value,
    refLang: refLang.value,
  }
}

// 参数变更自动缓存（isRestoring 守卫防止恢复期间触发无效回写）
watch(
  [params, selectedVoiceName, refText, refLang],
  () => {
    if (isRestoring.value) return
    persistCacheWhenIdle(buildCachePayload())
  },
  { deep: true },
)

// Inference
async function handleInference() {
  if (!inputText.value.trim() || !selectedVoiceName.value || isInferring.value) return
  isInferring.value = true
  const pending = pushPending(inputText.value)

  try {
    const synthesis = await synthesizeSpeechWithMeta({
      input: inputText.value,
      voice: selectedVoiceName.value,
      ...params.value,
      ...(refSource.value === 'custom' && customRefFile.value
        ? { ref_audio_file: customRefFile.value, ref_text: refText.value, ref_lang: refLang.value }
        : {}),
    })

    const blobUrl = URL.createObjectURL(synthesis.blob)
    const audio = new Audio(blobUrl)
    await new Promise<void>((resolve) => {
      audio.addEventListener('loadedmetadata', () => resolve(), { once: true })
      audio.addEventListener('error', () => resolve(), { once: true })
    })
    markDone(pending, blobUrl, audio.duration || null, {
      taskId: synthesis.taskId,
      resultId: synthesis.resultId,
    })
  } catch (err: unknown) {
    const axiosErr = err as { response?: { status?: number } }
    if (axiosErr.response?.status === 409) {
      ElMessage.warning('当前已有推理任务，请先暂停或等待完成')
      removeFromQueue(pending)
    } else {
      markError(pending, (err as Error).message)
      ElMessage.error(`推理失败: ${(err as Error).message}`)
    }
  } finally {
    isInferring.value = false
  }
}

// Reset params
function resetParams() {
  const voice = selectedVoice.value
  if (!voice) return
  params.value = {
    speed: voice.defaults.speed,
    temperature: voice.defaults.temperature,
    top_p: voice.defaults.top_p,
    top_k: voice.defaults.top_k,
    pause_length: voice.defaults.pause_length,
    text_lang: 'auto',
    text_split_method: 'cut5',
    chunk_length: 24,
  }
}

// Download
function handleDownload(item: AudioHistoryItem) {
  if (!item.blobUrl) return
  const a = document.createElement('a')
  a.href = item.blobUrl
  a.download = `tts_${item.id}.wav`
  a.click()
}

// 强制暂停
async function handleForcePause() {
  try {
    await requestForcePause()
    ElMessage.success('已发送暂停请求')
  } catch (err: unknown) {
    ElMessage.error(`暂停失败: ${(err as Error).message}`)
  }
}

// 清理残留
async function handleCleanup() {
  try {
    const result = await requestCleanupResiduals()
    const count = result.removed_temp_ref_dirs + result.removed_result_files
    ElMessage.success(`已清理 ${count} 项残留资源`)
  } catch (err: unknown) {
    ElMessage.error(`清理失败: ${(err as Error).message}`)
  }
}

// 单条删除
async function handleDeleteResult(item: AudioHistoryItem) {
  try {
    if (item.resultId) {
      await deleteSynthesisResult(item.resultId)
    }
  } catch {
    // 后端清理失败时静默降级，仍执行本地移除
  }
  removeFromQueue(item)
}

// 手动保存配置
async function handleSaveNow() {
  try {
    await persistCacheNow(buildCachePayload())
    ElMessage.success('配置已保存')
  } catch (err: unknown) {
    ElMessage.error(`保存失败: ${(err as Error).message}`)
  }
}

// Init
async function init() {
  try {
    voices.value = await fetchVoices()
    if (voices.value.length === 0) return

    // 恢复缓存
    isRestoring.value = true
    const cached = await restoreCache()
    const p = cached?.payload

    // 先选 voice — 触发 selectedVoice watcher 设置 voice defaults
    if (p && typeof p.voice === 'string' && voices.value.some(v => v.name === p.voice)) {
      selectedVoiceName.value = p.voice as string
    } else {
      selectedVoiceName.value = voices.value[0].name
    }

    // 让 selectedVoice watcher 完成 defaults 填充
    await nextTick()

    // 用缓存值覆盖 voice defaults（必须在 watcher 触发之后）
    if (p) {
      if (typeof p.speed === 'number') params.value.speed = p.speed
      if (typeof p.temperature === 'number') params.value.temperature = p.temperature
      if (typeof p.top_p === 'number') params.value.top_p = p.top_p
      if (typeof p.top_k === 'number') params.value.top_k = p.top_k
      if (typeof p.pause_length === 'number') params.value.pause_length = p.pause_length
      if (typeof p.text_lang === 'string') params.value.text_lang = p.text_lang
      if (typeof p.text_split_method === 'string') params.value.text_split_method = p.text_split_method
      if (typeof p.chunk_length === 'number') params.value.chunk_length = p.chunk_length
      if (typeof p.refText === 'string') refText.value = p.refText
      if (typeof p.refLang === 'string') refLang.value = p.refLang
    }

    // 等 params watcher 被调度后再关闭守卫（此时 isRestoring 仍为 true，watcher 被拦截）
    await nextTick()
    isRestoring.value = false

    // 建立 SSE 连接
    connectProgressStream()
  } catch (err: unknown) {
    isRestoring.value = false
    ElMessage.error(`初始化失败: ${(err as Error).message}`)
  }
}
init()
</script>

<template>
  <div class="max-w-[1440px] mx-auto px-4 lg:px-8 py-6">
    <div class="flex flex-col md:flex-row gap-6">
      <!-- Left panel: config -->
      <aside class="
        w-full md:w-[35%] lg:w-[30%]
        md:max-h-[calc(100vh-120px)] md:overflow-y-auto md:sticky md:top-20
        space-y-5 scrollbar-thin scrollbar-thumb-border scrollbar-track-transparent
      ">
        <!-- Voice select -->
        <section class="bg-card rounded-card p-4 shadow-card">
          <h3 class="text-[13px] font-semibold text-foreground mb-3">模型 (Voice)</h3>
          <VoiceSelect v-model="selectedVoiceName" :voices="voices" />
          <p v-if="selectedVoice" class="text-xs text-muted-fg mt-2">
            {{ selectedVoice.description }}
          </p>
        </section>

        <!-- Reference audio -->
        <section class="bg-card rounded-card p-4 shadow-card">
          <h3 class="text-[13px] font-semibold text-foreground mb-3">参考音频</h3>
          <el-radio-group v-model="refSource" class="mb-3">
            <el-radio value="preset">模型预设</el-radio>
            <el-radio value="custom">自定义上传</el-radio>
          </el-radio-group>

          <!-- Preset -->
          <div v-if="refSource === 'preset' && selectedVoice" class="text-xs text-muted-fg">
            {{ selectedVoice.ref_audio.split('/').pop() }}
          </div>

          <!-- Custom -->
          <div v-if="refSource === 'custom'">
            <el-upload
              :auto-upload="false" accept=".wav,.mp3,.flac" :limit="1" drag class="w-full"
              :on-change="(f: any) => customRefFile = f.raw"
            >
              <p class="text-sm text-muted-fg">拖拽或点击上传参考音频</p>
            </el-upload>
          </div>

          <!-- Reference text -->
          <div class="mt-3">
            <label class="text-[13px] font-semibold text-foreground block mb-1.5">参考文本</label>
            <el-input
              v-model="refText" type="textarea" :rows="2"
              :readonly="refSource === 'preset'"
              placeholder="参考音频对应的文本"
            />
          </div>

          <!-- Reference language -->
          <div class="mt-3 flex items-center gap-2">
            <label class="text-[13px] font-semibold text-foreground whitespace-nowrap">语言</label>
            <el-select v-model="refLang" size="small" class="w-24">
              <el-option value="auto" label="自动" />
              <el-option value="zh" label="中文" />
              <el-option value="en" label="English" />
              <el-option value="ja" label="日本語" />
              <el-option value="ko" label="한국어" />
            </el-select>
          </div>
        </section>

        <!-- Inference params -->
        <section class="bg-card rounded-card shadow-card overflow-hidden">
          <InferenceSettingsPanel v-model:params="params" @reset="resetParams" @save-now="handleSaveNow" />
        </section>
      </aside>

      <!-- Right panel: input + results -->
      <main class="w-full md:w-[65%] lg:w-[70%] space-y-5">
        <TtsForm
          v-model:text="inputText"
          :is-inferring="isInferring"
          :disabled="!selectedVoiceName"
          @submit="handleInference"
        />
        <InferenceControlBar
          :progress="progress"
          :runtime-error="runtimeError"
          :cache-error="cacheError"
          :is-connected="isProgressStreamConnected"
          @force-pause="handleForcePause"
          @cleanup="handleCleanup"
          @dismiss-runtime-error="clearRuntimeError"
          @dismiss-cache-error="cacheError = null"
        />
        <AudioResultPanel
          :history="audioHistory"
          :is-inferring="isInferring"
          @download="handleDownload"
          @delete="handleDeleteResult"
        />
      </main>
    </div>
  </div>
</template>
