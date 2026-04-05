<script setup lang="ts">
import { computed } from "vue";
import { useRuntimeState } from "@/composables/useRuntimeState";
import { Loading, Warning } from "@element-plus/icons-vue";

const runtimeState = useRuntimeState();

const sseConnectionState = computed(
  () => runtimeState.sseConnectionState.value,
);
const progressiveSegments = computed(
  () => runtimeState.progressiveSegments.value,
);
const isPolling = computed(() => sseConnectionState.value === "polling");

const completedSegments = computed(() =>
  progressiveSegments.value.filter((seg) => seg.renderStatus === "completed"),
);
</script>

<template>
  <div
    class="h-full flex flex-col px-8 py-6 overflow-hidden bg-card rounded-card shadow-card"
  >
    <div class="flex-none mb-6">
      <h2
        class="text-xl font-bold text-foreground mb-2 flex items-center gap-3"
      >
        <el-icon class="is-loading text-primary"><Loading /></el-icon>
        正在初始化时间线...
      </h2>
      <p class="text-muted-fg text-sm">
        <span v-if="!isPolling">正在通过流式连接接收生成的语音分段</span>
        <span v-else class="text-warning flex items-center gap-1">
          <el-icon><Warning /></el-icon>
          服务器流式连接中断，已降级为轮询模式查询状态...
        </span>
      </p>
    </div>

    <div
      class="flex-1 overflow-y-auto scrollbar-thin flex flex-col gap-3 pb-8 pr-2 relative"
      id="segments-container"
    >
      <TransitionGroup name="segment-fade" tag="div" class="space-y-3">
        <div
          v-for="seg in completedSegments"
          :key="seg.segmentId"
          class="bg-muted/20 border border-border w-full rounded-card p-4"
        >
          <p class="text-[14px] leading-relaxed text-foreground select-text">
            {{ seg.rawText }}
          </p>
        </div>
      </TransitionGroup>

      <div
        v-if="isPolling && completedSegments.length > 0"
        class="py-4 text-center text-muted-fg text-sm"
      >
        <el-icon class="is-loading"><Loading /></el-icon> 等待服务端生成完成...
      </div>

      <div
        v-if="progressiveSegments.length === 0"
        class="flex flex-col items-center justify-center p-12 text-muted-fg border border-dashed border-border rounded-card mt-8"
      >
        <el-icon class="is-loading text-3xl mb-4"><Loading /></el-icon>
        <p class="text-sm">正在打断句...稍后将送入发音队列</p>
      </div>
    </div>
  </div>
</template>

<style scoped>
.segment-fade-enter-active,
.segment-fade-leave-active {
  transition:
    opacity 0.5s ease,
    transform 0.5s ease;
}
.segment-fade-enter-from {
  opacity: 0;
  transform: translateY(10px);
}
.segment-fade-leave-to {
  opacity: 0;
  transform: translateY(-10px);
}
</style>
