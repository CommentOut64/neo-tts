<script setup lang="ts">
import { ref } from 'vue'
import { ElMessage } from 'element-plus'
import { useEditSession } from '@/composables/useEditSession'
import { useRuntimeState } from '@/composables/useRuntimeState'

defineProps<{
  visible: boolean
}>()

const emit = defineEmits<{
  (e: 'update:visible', value: boolean): void
  (e: 'success'): void
}>()

const editSession = useEditSession()
const runtimeState = useRuntimeState()
const isResetting = ref(false)

async function handleConfirm() {
  try {
    if (!runtimeState.canMutate.value) {
      ElMessage.warning('当前有正在运行的作业，无法清空会话')
      return
    }
    isResetting.value = true
    await editSession.clearSession()
    ElMessage.success('会话已清空')
    emit('update:visible', false)
    emit('success')
  } catch (error: any) {
    ElMessage.error(error.message || '清空失败')
  } finally {
    isResetting.value = false
  }
}
</script>

<template>
  <el-dialog
    :lock-scroll="false"
    :model-value="visible"
    @update:model-value="emit('update:visible', $event)"
    title="清空会话"
    width="420px"
    :close-on-click-modal="false"
  >
    <div class="py-4 text-foreground/80">
      确定要清空当前语音合成会话吗？<br>
      此操作将丢弃当前会话中的进度、参数和未保存草稿，但不会清空文本输入页里的输入稿。
    </div>
    <template #footer>
      <div class="flex justify-end gap-2">
        <el-button @click="emit('update:visible', false)" :disabled="isResetting">取消</el-button>
        <el-button type="danger" @click="handleConfirm" :loading="isResetting">确认清空</el-button>
      </div>
    </template>
  </el-dialog>
</template>
