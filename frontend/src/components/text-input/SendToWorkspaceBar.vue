<script setup lang="ts">
import { useRouter } from 'vue-router'
import { Right } from '@element-plus/icons-vue'
import { useInputDraft } from '@/composables/useInputDraft'

const router = useRouter()
const draft = useInputDraft()

function handleHandoff() {
  if (draft.isEmpty.value) return
  draft.sendToWorkspace(router)
}
</script>

<template>
  <div class="flex items-center justify-between bg-card rounded-card shadow-card py-3 px-5 border border-border dark:border-transparent animate-fall">
    <div class="flex flex-col gap-0.5">
      <span class="text-[13px] font-semibold text-foreground">就绪</span>
      <span class="text-xs text-muted-fg">完成文本准备后，送入语音合成并初始化会话</span>
    </div>
    <el-button 
      type="primary" 
      class="min-w-[140px] shadow-sm"
      :disabled="draft.isEmpty.value"
      @click="handleHandoff"
    >
      送入语音合成
      <el-icon class="ml-2"><Right /></el-icon>
    </el-button>
  </div>
</template>
