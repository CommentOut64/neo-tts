<script setup lang="ts">
import { computed, onMounted } from "vue";
import { useInferenceRuntime } from "@/composables/useInferenceRuntime";
import { useRuntimeState } from "@/composables/useRuntimeState";
import { ElProgress, ElButton } from "element-plus";
import {
  getPrimaryRenderActionKind,
  getPrimaryRenderActionLabel,
  resolveWorkspaceProgressState,
} from "./renderJobControls";

const { currentRenderJob, pauseJob, cancelJob, resumeJob } = useRuntimeState();
const { progress, connectProgressStream, refreshProgress } = useInferenceRuntime();

const resolvedProgress = computed(() =>
  resolveWorkspaceProgressState({
    inferenceProgress: progress.value,
    renderJob: currentRenderJob.value,
  }),
);

const progressPercent = computed(() => resolvedProgress.value.percent);
const statusMessage = computed(() => resolvedProgress.value.message);

onMounted(() => {
  connectProgressStream();
  void refreshProgress();
});

function onPause() {
  if (currentRenderJob.value?.status !== "paused") {
    void pauseJob();
  }
}

function onResume() {
  void resumeJob();
}

const primaryActionKind = computed(() =>
  getPrimaryRenderActionKind(currentRenderJob.value?.status),
);

const primaryActionLabel = computed(() =>
  getPrimaryRenderActionLabel(currentRenderJob.value?.status),
);

function onPrimaryAction() {
  if (primaryActionKind.value === "resume") {
    onResume();
    return;
  }

  onPause();
}

function onCancel() {
  void cancelJob();
}
</script>

<template>
  <div
    class="h-16 w-full shrink-0 bg-accent/10 border border-accent rounded-card shadow-card px-4 flex items-center gap-4"
  >
    <div class="flex-1 flex flex-col gap-1 pr-6">
      <div
        class="flex justify-between items-center text-sm font-semibold text-accent-fg"
      >
        <span>{{ statusMessage }}</span>
        <span>{{ progressPercent }}%</span>
      </div>
      <el-progress
        class="render-job-progress"
        :percentage="progressPercent"
        :show-text="false"
        status="success"
        stroke-linecap="round"
        :stroke-width="8"
      />
    </div>

    <!-- Job Controls -->
    <div class="flex items-center gap-2 shrink-0 border-l border-border pl-4">
      <el-button
        :type="primaryActionKind === 'resume' ? 'success' : 'warning'"
        plain
        size="small"
        @click="onPrimaryAction"
      >
        {{ primaryActionLabel }}
      </el-button>
      <el-button type="danger" plain size="small" @click="onCancel"
        >取消</el-button
      >
    </div>
  </div>
</template>

<style scoped>
.render-job-progress :deep(.el-progress-bar__inner) {
  transition: width 0.45s cubic-bezier(0.22, 1, 0.36, 1) !important;
}
</style>
