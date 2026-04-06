<script setup lang="ts">
import { Delete } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { extractStatusCode } from '@/api/requestSupport'
import { useInputDraft } from '@/composables/useInputDraft'
import { useEditSession } from '@/composables/useEditSession'
import { useWorkspaceLightEdit } from '@/composables/useWorkspaceLightEdit'
import { runClearInputDraftFlow } from './clearInputDraftFlow'

const draft = useInputDraft()
const editSession = useEditSession()
const lightEdit = useWorkspaceLightEdit()

async function handleClear() {
  if (draft.isEmpty.value) return

  try {
    await runClearInputDraftFlow({
      confirmClearDraft: () => ElMessageBox.confirm('确定清空当前内容？', '清空草稿', {
        confirmButtonText: '确定',
        cancelButtonText: '取消',
        type: 'warning',
      }),
      loadHasSessionContent: async () => {
        try {
          await editSession.refreshSnapshot()
          return editSession.sessionStatus.value !== 'empty'
        } catch (error) {
          if (extractStatusCode(error) === 404) {
            return false
          }
          throw error
        }
      },
      chooseSessionCleanup: async () => {
        try {
          await ElMessageBox.confirm(
            '检测到语音合成界面还有会话正文，是否同时清理？',
            '同步清理会话正文',
            {
              confirmButtonText: '同时清理',
              cancelButtonText: '保留会话正文',
              type: 'warning',
              closeOnClickModal: false,
              closeOnPressEscape: false,
              showClose: false,
            },
          )
          return true
        } catch {
          return false
        }
      },
      clearDraft: () => {
        draft.setText('')
      },
      clearSession: async () => {
        lightEdit.clearAll()
        await editSession.clearSession()
      },
    })
  } catch (error) {
    const message = error instanceof Error ? error.message : '清理失败，请稍后重试'
    ElMessage.error(message)
  }
}

function handleInput(val: string) {
  draft.setText(val)
}
</script>

<template>
  <div class="flex flex-col h-full bg-card rounded-card shadow-card p-4">
    <div class="flex items-center justify-between mb-3 shrink-0">
      <h3 class="text-[13px] font-semibold text-foreground">输入稿正文</h3>
      <el-button 
        type="danger" text size="small" :icon="Delete" 
        :disabled="draft.isEmpty.value"
        @click="handleClear"
      >
        清空
      </el-button>
    </div>
    <el-input
      :model-value="draft.text.value"
      type="textarea"
      class="flex-1 min-h-[220px] w-full text-input-textarea"
      :input-style="{ resize: 'vertical' }"
      placeholder="从这里开始输入要合成的文本..."
      @update:model-value="handleInput"
    />
    <div class="flex justify-end mt-2 shrink-0 text-xs text-muted-fg">
      {{ draft.text.value.length }} 字
    </div>
  </div>
</template>

<style scoped>
.text-input-textarea :deep(.el-textarea__inner) {
  height: 100%;
  min-height: 100% !important;
  padding: 16px 18px; /* 增加内边距，让文本远离左上角边界 */
  line-height: 1.6;
  scrollbar-width: thin;
  scrollbar-color: var(--color-border) transparent;
  /* limit maximum resize so it doesn't push the bottom bar offscreen */
  max-height: 50vh !important; 
}
.text-input-textarea :deep(.el-textarea__inner)::-webkit-scrollbar {
  width: 8px;
}
.text-input-textarea :deep(.el-textarea__inner)::-webkit-scrollbar-thumb {
  background-color: var(--color-border);
  border-radius: 9999px;
}
.text-input-textarea :deep(.el-textarea__inner)::-webkit-scrollbar-track {
  background: transparent;
}
</style>
