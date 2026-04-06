<script setup lang="ts">
defineProps<{
  visible: boolean;
}>();

const emit = defineEmits<{
  cancel: [];
  discard: [];
  submit: [];
}>();
</script>

<template>
  <el-dialog
    :model-value="visible"
    title="存在未提交参数"
    width="420px"
    :close-on-click-modal="false"
    :close-on-press-escape="false"
    @close="emit('cancel')"
  >
    <p class="text-sm text-muted-fg leading-6">
      当前参数栏有未提交的草稿。继续切换前，请选择提交、放弃，或取消本次切换。
    </p>

    <template #footer>
      <div class="flex items-center justify-end gap-2">
        <el-button @click="emit('cancel')">取消</el-button>
        <el-button @click="emit('discard')">放弃并继续</el-button>
        <el-button type="primary" @click="emit('submit')">提交并继续</el-button>
      </div>
    </template>
  </el-dialog>
</template>
