<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { QuestionFilled } from "@element-plus/icons-vue";
import { useParameterPanel } from "@/composables/useParameterPanel";

const props = defineProps<{
  scope: "session" | "segment" | "batch" | "edge";
  hasDirty: boolean;
  isSubmitting: boolean;
}>();

const emit = defineEmits<{
  submit: [];
  discard: [];
}>();

const submitLabel = computed(() => "提交参数");

const title = computed(() => {
  switch (props.scope) {
    case "session":
      return "会话参数";
    case "segment":
      return "段级参数";
    case "batch":
      return "批量参数";
    case "edge":
      return "边界参数";
    default:
      return "参数设置";
  }
});

const hint = computed(() => {
  switch (props.scope) {
    case "session":
      return "当前编辑会话的默认运行期参数。提交后会创建新的配置 patch job。";
    case "segment":
      return "当前选中段的运行期参数。提交后仅持久化配置，后续推理会继承这些值。";
    case "batch":
      return "当前选中多段的统一运行期参数。多个值时会以“多个值”展示。";
    case "edge":
      return "调整段间停顿与边界策略。提交后仅持久化配置，不立即触发重推理。";
    default:
      return "";
  }
});

const panel = useParameterPanel();
const isFlashing = ref(false);
let flashTimeout: ReturnType<typeof setTimeout> | null = null;

watch(
  () => panel.flashPulse.value,
  () => {
    if (panel.flashPulse.value > 0) {
      isFlashing.value = true;
      if (flashTimeout) {
        clearTimeout(flashTimeout);
      }
      flashTimeout = setTimeout(() => {
        isFlashing.value = false;
      }, 600); // 快速闪烁时长 (600ms 足以做几次关键帧变化)
    }
  }
);
</script>

<style scoped>
@keyframes flash-draft-alert {
  0%, 100% {
    border-color: rgba(245, 158, 11, 0.6);
    box-shadow: none;
    background-color: var(--color-card);
  }
  50% {
    border-color: rgba(245, 158, 11, 1);
    /* box-shadow: inset 0 0 0 2px rgba(245, 158, 11, 1), 0 0 16px rgba(245, 158, 11, 0.6); */
    background-color: rgba(245, 158, 11, 0.05);
  }
}
.animate-flash-alert {
  animation: flash-draft-alert 0.3s ease-in-out 2;
}
</style>

<template>
  <section
    class="bg-card rounded-card p-4 shadow-card transition-all duration-500 relative border border-border dark:border-transparent animate-fall"
    :class="[
      hasDirty ? '!border-amber-500/60 shadow-[0_0_0_1px_rgba(245,158,11,0.6)]' : '',
      isFlashing ? 'animate-flash-alert !border-amber-500 shadow-[0_0_0_1px_rgba(245,158,11,1)]' : ''
    ]"
  >
    <div class="flex items-center justify-between gap-3">
      <div class="flex items-center shrink-0 h-6">
        <h3 class="text-sm font-semibold text-foreground">
          {{ title }}<span v-if="hasDirty" class="text-red-500 font-bold ml-1 mr-1.5">*</span><span v-else class="mr-1.5"></span>
        </h3>
        <el-tooltip :content="hint" placement="top" effect="dark">
          <el-icon class="text-muted-fg/70 cursor-help outline-none text-[15px]"><QuestionFilled /></el-icon>
        </el-tooltip>
      </div>
      <div class="flex items-center gap-2">
        <button 
          class="px-3 py-1 text-xs font-medium rounded text-muted-fg hover:bg-secondary/50 transition-colors disabled:opacity-50 disabled:cursor-not-allowed" 
          :disabled="!hasDirty || isSubmitting" 
          @click="emit('discard')"
        >
          放弃
        </button>
        <button 
          class="hover-state-layer px-3 py-1 text-xs font-medium rounded transition-colors shadow-sm disabled:opacity-50 disabled:cursor-not-allowed bg-blue-500 text-white"
          :disabled="!hasDirty || isSubmitting" 
          @click="emit('submit')"
        >
          {{ isSubmitting ? "提交中..." : submitLabel }}
        </button>
      </div>
    </div>
  </section>
</template>
