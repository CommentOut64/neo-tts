<script setup lang="ts">
import { ref, watch } from "vue";

export interface SecretEditorField {
  key: string;
  label: string;
  help_text?: string | null;
}

const props = withDefaults(defineProps<{
  visible: boolean;
  title: string;
  fields: SecretEditorField[];
  modelValue?: Record<string, string> | null;
  loading?: boolean;
  submitText?: string;
}>(), {
  modelValue: null,
  loading: false,
  submitText: "保存",
});

const emit = defineEmits<{
  "update:visible": [value: boolean];
  submit: [value: Record<string, string>];
  cancel: [];
}>();

const draft = ref<Record<string, string>>({});

watch(
  () => [props.visible, props.fields, props.modelValue] as const,
  () => {
    draft.value = Object.fromEntries(
      props.fields.map((field) => [field.key, props.modelValue?.[field.key] ?? ""]),
    );
  },
  { immediate: true, deep: true },
);

function handleCancel() {
  emit("update:visible", false);
  emit("cancel");
}

function handleSubmit() {
  emit("submit", { ...draft.value });
}
</script>

<template>
  <el-dialog
    :model-value="visible"
    width="560px"
    :title="title"
    :close-on-click-modal="!loading"
    :close-on-press-escape="!loading"
    :show-close="!loading"
    destroy-on-close
    @update:model-value="value => value ? emit('update:visible', value) : handleCancel()"
  >
    <div class="space-y-4 py-2">
      <div
        v-for="field in fields"
        :key="field.key"
        class="rounded-card border border-border/60 bg-secondary/10 p-3"
      >
        <div class="mb-2 text-sm font-medium text-foreground">{{ field.label }}</div>
        <p v-if="field.help_text" class="mb-2 text-xs text-muted-fg">{{ field.help_text }}</p>
        <el-input
          v-model="draft[field.key]"
          type="password"
          show-password
          :disabled="loading"
          :placeholder="`请输入${field.label}`"
        />
      </div>
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
