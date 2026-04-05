<script setup lang="ts">
import { Delete } from '@element-plus/icons-vue'
import { ElMessageBox } from 'element-plus'
import { useInputDraft } from '@/composables/useInputDraft'

const draft = useInputDraft()

async function handleClear() {
  if (draft.isEmpty.value) return
  try {
    await ElMessageBox.confirm('确定清空当前内容？', '清空草稿', {
      confirmButtonText: '确定',
      cancelButtonText: '取消',
      type: 'warning'
    })
    draft.setText('')
  } catch {
    // resolved via cancellation - no op needed
  }
}

function handleInput(val: string) {
  draft.setText(val)
}
</script>

<template>
  <div class="relative flex flex-col h-full bg-card rounded-card shadow-card p-4">
    <div class="flex items-center justify-between mb-3">
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
      class="flex-1 w-full text-foreground resize-none"
      :input-style="{ height: '100%', resize: 'none' }"
      placeholder="从这里开始输入要合成的文本..."
      @update:model-value="handleInput"
    />
    <div class="absolute bottom-6 right-6 text-xs text-muted-fg pointer-events-none bg-card px-1">
      {{ draft.text.value.length }} 字
    </div>
  </div>
</template>
