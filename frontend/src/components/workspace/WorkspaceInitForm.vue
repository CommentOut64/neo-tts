<script setup lang="ts">
import { computed } from "vue";
import {
  resolveReferenceSelectionBySource,
  resolveReferenceSelectionForBinding,
} from "@/features/reference-binding";
import BindingSelector from "@/components/workspace/BindingSelector.vue";
import type { RegistryBindingOption } from "@/types/ttsRegistry";
import InferenceSettingsPanel from "@/components/InferenceSettingsPanel.vue";
import type { InputTextLanguage } from "@/composables/useInputDraft";
import type { BindingReference } from "@/types/editSession";

const props = defineProps<{
  modelValue: {
    binding_key: string;
    binding_ref: BindingReference | null;
    speed: number;
    temperature: number;
    top_p: number;
    top_k: number;
    noise_scale: number;
    pause_length: number;
    text_lang: string;
    text_split_method: string;
    ref_source: "preset" | "custom";
    custom_ref_file: File | null;
    custom_ref_path: string | null;
    ref_text: string;
    ref_lang: string;
    referenceSelectionsByBinding: Record<
      string,
      {
        source: "preset" | "custom";
        custom_ref_path: string | null;
        ref_text: string;
        ref_lang: string;
      }
    >;
  };
  bindings: RegistryBindingOption[];
}>();

const emit = defineEmits<{
  "update:modelValue": [value: any];
  "request-text-language-change": [value: InputTextLanguage];
  reset: [];
}>();

const selectedBinding = computed(() => {
  return props.bindings.find((binding) => binding.bindingKey === props.modelValue.binding_key) ?? null;
});

function update(key: string, value: any) {
  emit("update:modelValue", { ...props.modelValue, [key]: value });
}

function handleBindingChange(bindingKey: string) {
  const binding = props.bindings.find((item) => item.bindingKey === bindingKey);
  if (!binding) {
    return;
  }
  const newParams = {
    ...props.modelValue,
    binding_key: binding.bindingKey,
    binding_ref: binding.bindingRef,
    speed: typeof binding.defaults.speed === "number" ? binding.defaults.speed : props.modelValue.speed,
    temperature:
      typeof binding.defaults.temperature === "number"
        ? binding.defaults.temperature
        : props.modelValue.temperature,
    top_p: typeof binding.defaults.top_p === "number" ? binding.defaults.top_p : props.modelValue.top_p,
    top_k: typeof binding.defaults.top_k === "number" ? binding.defaults.top_k : props.modelValue.top_k,
    noise_scale:
      typeof binding.defaults.noise_scale === "number"
        ? binding.defaults.noise_scale
        : props.modelValue.noise_scale,
    pause_length:
      typeof binding.defaults.pause_length === "number"
        ? binding.defaults.pause_length
        : props.modelValue.pause_length,
  };

  const { selection } = resolveReferenceSelectionForBinding({
    bindingRef: binding.bindingRef,
    bindingOptions: props.bindings,
    selections: props.modelValue.referenceSelectionsByBinding,
  });
  newParams.ref_source = selection.source;
  newParams.custom_ref_path = selection.custom_ref_path;
  newParams.ref_text = selection.ref_text;
  newParams.ref_lang = selection.ref_lang;
  newParams.custom_ref_file = null;

  emit("update:modelValue", newParams);
}

function handleReferenceSourceChange(source: "preset" | "custom") {
  if (!props.modelValue.binding_ref) {
    update("ref_source", source);
    return;
  }

  const { selection } = resolveReferenceSelectionBySource({
    bindingRef: props.modelValue.binding_ref,
    source,
    bindingOptions: props.bindings,
    selections: props.modelValue.referenceSelectionsByBinding,
  });

  emit("update:modelValue", {
    ...props.modelValue,
    ref_source: selection.source,
    custom_ref_path: selection.custom_ref_path,
    ref_text: selection.ref_text,
    ref_lang: selection.ref_lang,
    custom_ref_file: source === "custom" ? props.modelValue.custom_ref_file : null,
  });
}

function handleInferenceParamsUpdate(nextParams: typeof props.modelValue) {
  if (nextParams.text_lang !== props.modelValue.text_lang) {
    emit("request-text-language-change", nextParams.text_lang as InputTextLanguage);
    return;
  }

  emit("update:modelValue", nextParams);
}
</script>

<template>
  <div
    class="space-y-5 w-full h-full overflow-y-auto scrollbar-thin scrollbar-thumb-border scrollbar-track-transparent"
  >
    <section class="bg-card rounded-card p-4 shadow-card border border-border dark:border-transparent animate-fall">
      <div class="flex items-center justify-between gap-3">
        <h3 class="text-sm font-semibold text-foreground flex items-center shrink-0 h-6">
          全局参数
        </h3>
      </div>
    </section>

    <section class="bg-card rounded-card p-4 shadow-card border border-border dark:border-transparent animate-fall">
      <h3 class="text-[13px] font-semibold text-foreground mb-3">目标模型</h3>
      <BindingSelector
        :model-value="modelValue.binding_key"
        :bindings="bindings"
        @update:model-value="handleBindingChange"
      />
      <p v-if="selectedBinding" class="text-[12px] text-muted-fg mt-2">
        {{ selectedBinding.label }}
      </p>
    </section>

    <section class="bg-card rounded-card p-4 shadow-card border border-border dark:border-transparent animate-fall">
      <h3 class="text-[13px] font-semibold text-foreground mb-3">参考音频</h3>
      <el-radio-group
        :model-value="modelValue.ref_source"
        @update:model-value="handleReferenceSourceChange"
        class="mb-3"
      >
        <el-radio value="preset">模型预设</el-radio>
        <el-radio value="custom">自定义上传</el-radio>
      </el-radio-group>

      <div
        v-if="modelValue.ref_source === 'preset' && selectedBinding?.referenceAudioPath"
        class="text-xs text-muted-fg"
      >
        {{ selectedBinding.referenceAudioPath.split("/").pop() }}
      </div>

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
          <el-option value="en" label="英文" />
          <el-option value="ja" label="日文" />
          <el-option value="ko" label="韩文" />
        </el-select>
      </div>
    </section>

    <section class="bg-card rounded-card overflow-hidden shadow-card border border-border dark:border-transparent animate-fall">
      <InferenceSettingsPanel
        :params="modelValue"
        :show-noise-scale="true"
        :show-chunk-length="false"
        :show-text-split-method="false"
        @update:params="handleInferenceParamsUpdate"
        @reset="emit('reset')"
      />
    </section>
  </div>
</template>
