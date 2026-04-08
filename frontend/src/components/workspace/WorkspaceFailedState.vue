<script setup lang="ts">
import { computed } from "vue";
import { useEditSession } from "@/composables/useEditSession";
import { Warning, Refresh, Back } from "@element-plus/icons-vue";

const { initialize, lastInitParams, sessionStatus } = useEditSession();

const canRetry = computed(() => {
  const p = lastInitParams?.value;
  return !!(p && p.raw_text && p.voice_id);
});

async function onRetry() {
  if (!canRetry.value) return;
  await initialize(lastInitParams.value!);
}

function onReset() {
  sessionStatus.value = "empty";
}
</script>

<template>
  <div class="h-full flex flex-col items-center justify-center p-8">
    <div
      class="max-w-md w-full bg-card rounded-card shadow-card p-6 flex flex-col items-center text-center border border-border dark:border-transparent animate-fall"
    >
      <div
        class="w-12 h-12 bg-destructive/10 rounded-full flex items-center justify-center mb-4"
      >
        <el-icon class="text-3xl text-destructive"><Warning /></el-icon>
      </div>

      <h2 class="text-xl font-bold text-foreground mb-3">初始化阶段发生错误</h2>
      <p class="text-muted-fg text-sm mb-6 leading-relaxed">
        后端服务器可能异常，或参数遭到校验拒绝。我们保存了您的参数快照，如校验无误可以尝试静默重发。
      </p>

      <div class="flex items-center gap-3 w-full justify-center">
        <el-button @click="onReset" :icon="Back"> 返回并重配 </el-button>
        <el-button
          v-if="canRetry"
          type="primary"
          :icon="Refresh"
          @click="onRetry"
        >
          校验并静默重试
        </el-button>
      </div>
    </div>
  </div>
</template>
