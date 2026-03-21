<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { ElMessage } from 'element-plus'
import type { VoiceProfile, AudioHistoryItem } from '@/types/tts'
import { fetchVoices, synthesizeSpeech } from '@/api/tts'
import { useAudioQueue } from '@/composables/useAudioQueue'
import VoiceSelect from '@/components/VoiceSelect.vue'
import InferenceSettingsPanel from '@/components/InferenceSettingsPanel.vue'
import TtsForm from '@/components/TtsForm.vue'
import AudioResultPanel from '@/components/AudioResultPanel.vue'

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
  chunk_length: 24,
})

// Text + state
const inputText = ref('')
const isInferring = ref(false)

// Audio queue
const { history: audioHistory, pushPending, markDone, markError } = useAudioQueue()

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
    chunk_length: 24,
  }
  refText.value = voice.ref_text
  refLang.value = voice.ref_lang
  refSource.value = 'preset'
  customRefFile.value = null
})

// Inference
async function handleInference() {
  if (!inputText.value.trim() || !selectedVoiceName.value || isInferring.value) return
  isInferring.value = true
  const pending = pushPending(inputText.value)

  try {
    const blob = await synthesizeSpeech({
      input: inputText.value,
      voice: selectedVoiceName.value,
      ...params.value,
      ...(refSource.value === 'custom' && customRefFile.value
        ? { ref_audio_file: customRefFile.value, ref_text: refText.value, ref_lang: refLang.value }
        : {}),
    })

    const blobUrl = URL.createObjectURL(blob)
    const audio = new Audio(blobUrl)
    await new Promise<void>((resolve) => {
      audio.addEventListener('loadedmetadata', () => resolve(), { once: true })
      audio.addEventListener('error', () => resolve(), { once: true })
    })
    markDone(pending, blobUrl, audio.duration || null)
  } catch (err: unknown) {
    markError(pending, (err as Error).message)
    ElMessage.error(`推理失败: ${(err as Error).message}`)
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

// Init
async function init() {
  try {
    voices.value = await fetchVoices()
    if (voices.value.length > 0) selectedVoiceName.value = voices.value[0].name
  } catch (err: unknown) {
    ElMessage.error(`加载模型列表失败: ${(err as Error).message}`)
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
          <InferenceSettingsPanel v-model:params="params" @reset="resetParams" />
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
        <AudioResultPanel
          :history="audioHistory"
          :is-inferring="isInferring"
          @download="handleDownload"
        />
      </main>
    </div>
  </div>
</template>
