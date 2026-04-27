<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { ElMessage } from "element-plus";

import { uploadEditSessionReferenceAudio } from "@/api/editSession";
import VoiceSelect from "@/components/VoiceSelect.vue";
import { useParameterPanel } from "@/composables/useParameterPanel";
import { DEFAULT_REFERENCE_BINDING_MODEL_KEY } from "@/features/reference-binding";
import type { VoiceProfile } from "@/types/tts";

import RuntimeInferenceSettingsPanel from "./RuntimeInferenceSettingsPanel.vue";
import { MIXED_VALUE } from "./resolveEffectiveParameters";

const props = defineProps<{
  voices: VoiceProfile[];
  title: string;
  hint: string;
}>();

const panel = useParameterPanel();
const isUploadingReferenceAudio = ref(false);
const inputsDisabled = computed(
  () => panel.isSubmitting.value || panel.resolvedStatus.value !== "ready",
);
const scopeStatusMessage = computed(() => {
  if (panel.resolvedStatus.value === "resolving") {
    return "正在同步当前作用域的正式参数，暂时不可编辑。";
  }
  if (panel.resolvedStatus.value === "unresolved") {
    return "当前作用域的正式参数引用暂不可解析，请稍后重试或重新选择范围。";
  }
  return null;
});

watch(
  () => props.voices,
  (nextVoices) => {
    panel.setVoices(nextVoices);
  },
  { immediate: true, deep: true },
);

function isMixed(value: unknown): value is typeof MIXED_VALUE {
  return value === MIXED_VALUE;
}

function asString(
  value: string | typeof MIXED_VALUE | null | undefined,
): string {
  if (value === null || value === undefined || isMixed(value)) {
    return "";
  }
  return value;
}

const selectedVoiceId = computed(() => {
  return asString(panel.displayValues.value.voiceBinding.voice_id);
});

const selectedVoice = computed(() => {
  return (
    props.voices.find((voice) => voice.name === selectedVoiceId.value) ?? null
  );
});

const referenceState = computed(() => panel.displayValues.value.reference);
const refSource = computed<"preset" | "custom">({
  get() {
    return referenceState.value.source === "custom" ? "custom" : "preset";
  },
  set(value) {
    panel.updateReferenceSource(value);
  },
});

function updateVoice(voiceId: string) {
  const isOriginalVoice = voiceId === panel.resolvedValues.value.voiceBinding.voice_id;
  const voice = props.voices.find((item) => item.name === voiceId);

  panel.updateVoiceBindingField("voice_id", voiceId);

  if (isOriginalVoice) {
    const originalModelKey = panel.resolvedValues.value.voiceBinding.model_key as string | null;
    if (originalModelKey !== MIXED_VALUE) {
      panel.updateVoiceBindingField("model_key", originalModelKey);
    }
  } else {
    panel.updateVoiceBindingField("model_key", DEFAULT_REFERENCE_BINDING_MODEL_KEY);
  }

  if (isOriginalVoice) {
    const origGpt = panel.resolvedValues.value.voiceBinding.gpt_path as string | null;
    if (origGpt !== MIXED_VALUE) {
      panel.updateVoiceBindingField("gpt_path", origGpt);
    }
    const origSovits = panel.resolvedValues.value.voiceBinding.sovits_path as string | null;
    if (origSovits !== MIXED_VALUE) {
      panel.updateVoiceBindingField("sovits_path", origSovits);
    }
  } else if (voice) {
    panel.updateVoiceBindingField("gpt_path", voice.gpt_path);
    panel.updateVoiceBindingField("sovits_path", voice.sovits_path);
  }
}

function handleRuntimeUpdate(
  field: "speed" | "top_k" | "top_p" | "temperature" | "noise_scale",
  value: number,
) {
  panel.updateRenderProfileField(field, value);
}

async function handleReferenceAudioUpload(file: { raw?: File }) {
  if (inputsDisabled.value) {
    return;
  }
  if (!(file.raw instanceof File)) {
    return;
  }

  isUploadingReferenceAudio.value = true;
  try {
    const response = await uploadEditSessionReferenceAudio(file.raw);
    panel.applyUploadedReferenceAudio(response);
    ElMessage.success(`参考音频已上传：${response.filename}`);
  } catch (error) {
    ElMessage.error(
      error instanceof Error
        ? `参考音频上传失败: ${error.message}`
        : "参考音频上传失败",
    );
  } finally {
    isUploadingReferenceAudio.value = false;
  }
}
</script>

<template>
  <p
    v-if="scopeStatusMessage"
    class="mb-3 rounded-card border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs text-muted-fg"
  >
    {{ scopeStatusMessage }}
  </p>

  <section class="bg-card rounded-card p-4 shadow-card border border-border dark:border-transparent animate-fall">
    <h3 class="text-[13px] font-semibold text-foreground mb-3 flex items-center">
      目标音色<span v-if="panel.dirtyFields.value.has('voiceBinding.voice_id')" class="text-red-500 font-bold ml-0.5">*</span>
    </h3>
    <VoiceSelect
      :model-value="selectedVoiceId"
      :voices="voices"
      :disabled="inputsDisabled"
      :placeholder="
        isMixed(panel.displayValues.value.voiceBinding.voice_id)
          ? '多个音色'
          : '选择模型'
      "
      @update:model-value="updateVoice"
    />
    <p v-if="selectedVoice" class="text-[12px] text-muted-fg mt-2">
      {{ selectedVoice.description }}
    </p>
    <p
      v-else-if="isMixed(panel.displayValues.value.voiceBinding.voice_id)"
      class="text-[12px] text-muted-fg mt-2"
    >
      当前选择包含多个音色，修改后将统一覆盖为同一音色。
    </p>
  </section>

  <section class="bg-card rounded-card p-4 shadow-card border border-border dark:border-transparent animate-fall">
    <h3 class="text-[13px] font-semibold text-foreground mb-3 flex items-center">
      参考音频<span v-if="panel.dirtyFields.value.has('reference.source') || panel.dirtyFields.value.has('reference.reference_audio_path') || panel.dirtyFields.value.has('reference.reference_text') || panel.dirtyFields.value.has('reference.reference_language')" class="text-red-500 font-bold ml-0.5">*</span>
    </h3>
    <el-radio-group v-model="refSource" class="mb-3" :disabled="inputsDisabled">
      <el-radio value="preset">模型预设</el-radio>
      <el-radio value="custom">自定义上传</el-radio>
    </el-radio-group>

    <div
      v-if="refSource === 'preset' && referenceState.preset_audio_path"
      class="text-xs text-muted-fg"
    >
      {{ asString(referenceState.preset_audio_path).split("/").pop() }}
    </div>

    <div v-if="refSource === 'custom'" class="mb-3">
      <el-upload
        :auto-upload="false"
        accept=".wav,.mp3,.flac"
        :limit="1"
        drag
        class="w-full"
        :show-file-list="false"
        :on-change="handleReferenceAudioUpload"
        :disabled="inputsDisabled || isUploadingReferenceAudio"
      >
        <p class="text-sm text-muted-fg">
          {{
            isUploadingReferenceAudio
              ? "正在上传参考音频..."
              : "拖拽或点击上传参考音频"
          }}
        </p>
      </el-upload>

      <div class="mt-3">
        <label class="text-[13px] font-semibold text-foreground block mb-1.5 flex items-center"
          >参考音频路径<span v-if="panel.dirtyFields.value.has('reference.reference_audio_path')" class="text-red-500 font-bold ml-0.5">*</span></label
        >
        <el-input
          :model-value="asString(referenceState.reference_audio_path)"
          :readonly="true"
          :disabled="inputsDisabled"
          :placeholder="
            isMixed(referenceState.reference_audio_path)
              ? '多个值'
              : '例如：voices/demo.wav'
          "
        />
      </div>
    </div>

    <div class="mt-3 space-y-3">
      <div>
        <label class="text-[13px] font-semibold text-foreground block mb-1.5 flex items-center"
          >参考文本<span v-if="panel.dirtyFields.value.has('reference.reference_text')" class="text-red-500 font-bold ml-0.5">*</span></label
        >
        <el-input
          :model-value="asString(referenceState.reference_text)"
          type="textarea"
          :rows="2"
          :readonly="refSource === 'preset' || inputsDisabled"
          :disabled="inputsDisabled"
          :placeholder="
            isMixed(referenceState.reference_text)
              ? '多个值'
              : '参考音频对应的文本'
          "
          @update:model-value="
            panel.updateReferenceField('reference_text', $event || null)
          "
        />
      </div>

      <div class="flex flex-col gap-1.5 self-start">
        <label class="text-[13px] font-semibold text-foreground flex items-center"
          >参考语言<span v-if="panel.dirtyFields.value.has('reference.reference_language')" class="text-red-500 font-bold ml-0.5">*</span></label
        >
        <el-select
          :model-value="asString(referenceState.reference_language)"
          :disabled="inputsDisabled"
          size="small"
          class="!w-min"
          style="min-width: 90px"
          :placeholder="
            isMixed(referenceState.reference_language)
              ? '多个值'
              : '选择语言'
          "
          @update:model-value="
            panel.updateReferenceField('reference_language', $event || null)
          "
        >
          <el-option value="auto" label="自动" />
          <el-option value="zh" label="中文" />
          <el-option value="en" label="英文" />
          <el-option value="ja" label="日文" />
          <el-option value="ko" label="韩文" />
        </el-select>
      </div>
    </div>
  </section>

  <RuntimeInferenceSettingsPanel
    :values="panel.displayValues.value.renderProfile"
    :status="panel.resolvedStatus.value"
    :disabled="inputsDisabled"
    :dirty-fields="new Set(panel.dirtyFields.value)"
    @update="handleRuntimeUpdate"
  />
</template>
