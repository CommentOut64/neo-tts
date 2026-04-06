<script setup lang="ts">
import { computed } from "vue";
import type { VoiceProfile } from "@/types/tts";
import VoiceSelect from "@/components/VoiceSelect.vue";
import InferenceSettingsPanel from "@/components/InferenceSettingsPanel.vue";

const props = defineProps<{
  modelValue: {
    voice_id: string;
    speed: number;
    temperature: number;
    top_p: number;
    top_k: number;
    pause_length: number;
    chunk_length: number;
    text_lang: string;
    text_split_method: string;
    ref_source: "preset" | "custom";
    custom_ref_file: File | null;
    ref_text: string;
    ref_lang: string;
  };
  voices: VoiceProfile[];
}>();

const emit = defineEmits<{
  "update:modelValue": [value: any];
  reset: [];
}>();

const selectedVoice = computed(() => {
  return props.voices.find((v) => v.name === props.modelValue.voice_id) || null;
});

function update(key: string, value: any) {
  emit("update:modelValue", { ...props.modelValue, [key]: value });
}

function handleVoiceChange(val: string) {
  const v = props.voices.find((vo) => vo.name === val);
  const newParams = { ...props.modelValue, voice_id: val };
  if (v && v.defaults) {
    newParams.speed = v.defaults.speed;
    newParams.temperature = v.defaults.temperature;
    newParams.top_p = v.defaults.top_p;
    newParams.top_k = v.defaults.top_k;
    newParams.pause_length = v.defaults.pause_length;
    newParams.ref_text = v.ref_text || "";
    newParams.ref_lang = v.ref_lang || "auto";
    newParams.ref_source = "preset";
    newParams.custom_ref_file = null;
  }
  emit("update:modelValue", newParams);
}
</script>

<template>
  <div
    class="space-y-5 w-full h-full overflow-y-auto scrollbar-thin scrollbar-thumb-border scrollbar-track-transparent"
  >
    <!-- 顶部状态卡片 -->
    <section class="bg-card rounded-card p-4 shadow-card">
      <div class="flex items-center justify-between gap-3">
        <h3 class="text-sm font-semibold text-foreground flex items-center shrink-0 h-6">
          全局参数
        </h3>
      </div>
    </section>

    <!-- 音色卡片 -->
    <section class="bg-card rounded-card p-4 shadow-card">
      <h3 class="text-[13px] font-semibold text-foreground mb-3">目标音色</h3>
      <VoiceSelect
        :model-value="modelValue.voice_id"
        :voices="voices"
        @update:model-value="handleVoiceChange"
      />
      <p v-if="selectedVoice" class="text-[12px] text-muted-fg mt-2">
        {{ selectedVoice.description }}
      </p>
    </section>

    <!-- 参考音频卡片 -->
    <section class="bg-card rounded-card p-4 shadow-card">
      <h3 class="text-[13px] font-semibold text-foreground mb-3">参考音频</h3>
      <el-radio-group
        :model-value="modelValue.ref_source"
        @update:model-value="update('ref_source', $event)"
        class="mb-3"
      >
        <el-radio value="preset">模型预设</el-radio>
        <el-radio value="custom">自定义上传</el-radio>
      </el-radio-group>

      <!-- 模型预设 -->
      <div
        v-if="modelValue.ref_source === 'preset' && selectedVoice"
        class="text-xs text-muted-fg"
      >
        {{ selectedVoice.ref_audio.split("/").pop() }}
      </div>

      <!-- 自定义上传 -->
      <div v-if="modelValue.ref_source === 'custom'">
        <el-upload
          :auto-upload="false"
          accept=".wav,.mp3,.flac"
          :limit="1"
          drag
          class="w-full"
          :on-change="(f: any) => update('custom_ref_file', f.raw)"
        >
          <p class="text-sm text-muted-fg">拖拽或点击上传参考音频</p>
        </el-upload>
      </div>

      <!-- 参考文本 -->
      <div class="mt-3">
        <label class="text-[13px] font-semibold text-foreground block mb-1.5"
          >参考文本</label
        >
        <el-input
          :model-value="modelValue.ref_text"
          @update:model-value="update('ref_text', $event)"
          type="textarea"
          :rows="2"
          :readonly="modelValue.ref_source === 'preset'"
          placeholder="参考音频对应的文本"
        />
      </div>

      <!-- 参考语言 -->
      <div class="mt-3 flex flex-col gap-1.5 self-start">
        <label class="text-[13px] font-semibold text-foreground"
          >参考语言</label
        >
        <el-select
          :model-value="modelValue.ref_lang"
          @update:model-value="update('ref_lang', $event)"
          size="small"
          class="!w-min"
          style="min-width: 90px"
        >
          <el-option value="auto" label="自动" />
          <el-option value="zh" label="中文" />
          <el-option value="en" label="English" />
          <el-option value="ja" label="日本語" />
          <el-option value="ko" label="한국어" />
        </el-select>
      </div>
    </section>

    <!-- 合成参数卡片 -->
    <section class="bg-card rounded-card overflow-hidden shadow-card">
      <InferenceSettingsPanel
        :params="modelValue"
        @update:params="emit('update:modelValue', { ...modelValue, ...$event })"
        @reset="emit('reset')"
      />
    </section>
  </div>
</template>
