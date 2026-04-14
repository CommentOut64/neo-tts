<script setup lang="ts">
import { Delete, RefreshLeft } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useEditSession } from '@/composables/useEditSession'
import { useInputDraft } from '@/composables/useInputDraft'
import { runClearInputDraftFlow } from './clearInputDraftFlow'

const draft = useInputDraft()
const editSession = useEditSession()

async function handleClear() {
  if (draft.isEmpty.value) return

  try {
    await runClearInputDraftFlow({
      confirmClearDraft: () => ElMessageBox.confirm(
        '这会同时清空输入框和当前会话，请先导出音频后再清空',
        '清空输入与会话',
        {
          confirmButtonText: '确认清空',
          cancelButtonText: '取消',
          type: 'warning',
          closeOnClickModal: false,
          closeOnPressEscape: false,
          lockScroll: false,
        },
      ),
      executeClear: async () => {
        await editSession.endSession({
          nextInputText: '',
          nextInputSource: 'manual',
        })
      },
    })
  } catch (error) {
    const message = error instanceof Error ? error.message : '清理失败，请稍后重试'
    ElMessage.error(message)
  }
}

function handleRestoreInitialText() {
  if (!draft.restoreLastSessionInitialText()) {
    return
  }
  ElMessage.success('已恢复最初版本')
}

function handleInput(val: string) {
  draft.setText(val)
}
</script>

<template>
  <div class="flex flex-col h-full bg-card rounded-card shadow-card p-4 border border-border dark:border-transparent animate-fall">
    <div class="flex items-center justify-between mb-3 shrink-0">
      <h3 class="text-[13px] font-semibold text-foreground">输入文本</h3>
      <div class="flex items-center gap-2">
        <el-button
          v-if="draft.lastSessionInitialText.value"
          text
          size="small"
          :icon="RefreshLeft"
          @click="handleRestoreInitialText"
        >
          恢复最初版本
        </el-button>
        <el-button 
          type="danger" text size="small" :icon="Delete" 
          :disabled="draft.isEmpty.value"
          @click="handleClear"
        >
          清空
        </el-button>
      </div>
    </div>
    <el-input
      :model-value="draft.text.value"
      type="textarea"
      class="flex-1 min-h-[220px] w-full text-input-textarea"
      :input-style="{ resize: 'vertical' }"
      placeholder="在此处输入要合成的文本..."
      @update:model-value="handleInput"
    />
    <div class="mt-2 flex items-center justify-between gap-3 shrink-0 text-xs text-muted-fg">
      <span v-if="draft.lastSessionInitialText.value">
        可随时恢复到本次会话开始时的文字。
      </span>
      <span class="ml-auto">{{ draft.text.value.length }} 字</span>
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
