<script setup lang="ts">
const props = withDefaults(defineProps<{
  visible: boolean;
  title: string;
  message: string;
  loading?: boolean;
  confirmText?: string;
}>(), {
  loading: false,
  confirmText: "确认删除",
});

const emit = defineEmits<{
  "update:visible": [value: boolean];
  submit: [];
  cancel: [];
}>();

function handleCancel() {
  emit("update:visible", false);
  emit("cancel");
}

function handleSubmit() {
  emit("submit");
}
</script>

<template>
  <el-dialog
    :model-value="visible"
    width="480px"
    :title="title"
    :close-on-click-modal="!loading"
    :close-on-press-escape="!loading"
    :show-close="!loading"
    destroy-on-close
    @update:model-value="value => value ? emit('update:visible', value) : handleCancel()"
  >
    <div class="space-y-3 py-2">
      <p class="text-sm text-foreground">{{ message }}</p>
      <p class="text-xs text-muted-fg">删除后将以重新拉取 workspaceTree 的结果为准。</p>
    </div>

    <template #footer>
      <div class="flex justify-end gap-2">
        <el-button :disabled="loading" @click="handleCancel">取消</el-button>
        <el-button type="danger" :loading="loading" :disabled="loading" @click="handleSubmit">
          {{ confirmText }}
        </el-button>
      </div>
    </template>
  </el-dialog>
</template>
