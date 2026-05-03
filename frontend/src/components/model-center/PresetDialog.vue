<script setup lang="ts">
import { ref, watch } from "vue";

import ModelSchemaForm from "@/components/model-center/ModelSchemaForm.vue";
import { buildSchemaFormModel } from "@/features/model-center/schemaForm";
import type { TtsRegistryFieldSchema } from "@/types/ttsRegistry";

const props = withDefaults(defineProps<{
  visible: boolean;
  title: string;
  schema: TtsRegistryFieldSchema[];
  modelValue?: Record<string, unknown> | null;
  loading?: boolean;
  disabled?: boolean;
  showAdvanced?: boolean;
  submitText?: string;
}>(), {
  modelValue: null,
  loading: false,
  disabled: false,
  showAdvanced: true,
  submitText: "保存",
});

const emit = defineEmits<{
  "update:visible": [value: boolean];
  submit: [value: Record<string, unknown>];
  cancel: [];
}>();

const draft = ref<Record<string, unknown>>({});

watch(
  () => [props.visible, props.schema, props.modelValue] as const,
  () => {
    draft.value = buildSchemaFormModel(props.schema, props.modelValue);
  },
  { immediate: true, deep: true },
);

function handleCancel() {
  emit("update:visible", false);
  emit("cancel");
}

function handleSubmit() {
  emit("submit", draft.value);
}
</script>

<template>
  <el-dialog
    :model-value="visible"
    width="680px"
    :title="title"
    :close-on-click-modal="!loading"
    :close-on-press-escape="!loading"
    :show-close="!loading"
    destroy-on-close
    @update:model-value="value => value ? emit('update:visible', value) : handleCancel()"
  >
    <div class="space-y-4 py-2">
      <ModelSchemaForm
        v-model="draft"
        :schema="schema"
        :disabled="disabled || loading"
        :show-advanced="showAdvanced"
      />
    </div>

    <template #footer>
      <div class="flex justify-end gap-2">
        <el-button :disabled="loading" @click="handleCancel">取消</el-button>
        <el-button type="primary" :loading="loading" :disabled="loading" @click="handleSubmit">
          {{ submitText }}
        </el-button>
      </div>
    </template>
  </el-dialog>
</template>
