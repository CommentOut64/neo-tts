<script setup lang="ts">
import { computed } from "vue";
import { useRuntimeState } from "@/composables/useRuntimeState";
import { ElProgress, ElButton } from "element-plus";

const { currentRenderJob, pauseJob, cancelJob } = useRuntimeState();

const progressPercent = computed(() => {
  if (!currentRenderJob.value) return 0;
  return Math.round(currentRenderJob.value.progress * 100);
});

const statusMessage = computed(() => {
  if (!currentRenderJob.value) return "等待中...";
  return currentRenderJob.value.message || "正在渲染...";
});

function onPause() {
  if (currentRenderJob.value?.status !== "paused") {
    void pauseJob();
  }
}

function onCancel() {
  void cancelJob();
}
</script>

<template>
  <div
    class="h-16 w-full shrink-0 bg-accent/10 border-accent rounded-card shadow-card px-4 flex items-center gap-4"
  >
    <div class="flex-1 flex flex-col gap-1 pr-6">
      <div
        class="flex justify-between items-center text-sm font-semibold text-accent-fg"
      >
        <span>{{ statusMessage }}</span>
        <span>{{ progressPercent }}%</span>
      </div>
      <el-progress
        :percentage="progressPercent"
        :show-text="false"
        status="success"
        stroke-linecap="round"
        :stroke-width="8"
      />
    </div>

    <!-- Job Controls -->
    <div class="flex items-center gap-2 shrink-0 border-l border-border pl-4">
      <el-button type="warning" plain size="small" @click="onPause"
        >暂停</el-button
      >
      <el-button type="danger" plain size="small" @click="onCancel"
        >取消</el-button
      >
    </div>
  </div>
</template>
