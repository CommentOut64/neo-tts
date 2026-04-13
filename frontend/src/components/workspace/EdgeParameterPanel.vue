<script setup lang="ts">
import { computed } from "vue";

import ParameterSlider from "@/components/ParameterSlider.vue";
import { useParameterPanel } from "@/composables/useParameterPanel";
import {
  EDGE_BOUNDARY_STRATEGY_OPTIONS,
  formatEdgeBoundaryStrategyLabel,
} from "@/components/workspace/edgeDisplay";

const panel = useParameterPanel();

const edgeValues = computed(() => panel.displayValues.value.edge);
const isBoundaryStrategyLocked = computed(
  () => Boolean(edgeValues.value?.boundary_strategy_locked),
);
</script>

<template>
  <section class="bg-card rounded-card p-4 shadow-card border border-border dark:border-transparent animate-fall">
    <h3 class="text-[13px] font-semibold text-foreground mb-3">停顿与拼接</h3>

    <div class="space-y-4">
      <ParameterSlider
        :model-value="edgeValues?.pause_duration_seconds ?? 0.3"
        label="停顿时长"
        :min="0"
        :max="2"
        :slider-max="2"
        :input-max="10"
        :step="0.01"
        unit="s"
        tooltip="控制两段之间的静音时长"
        hint="滑杆支持 0 到 2 秒；超过 2 秒请在右侧输入框中输入，最大 10 秒。"
        :is-dirty="panel.dirtyFields.value.has('edge.pause_duration_seconds')"
        @update:model-value="panel.updateEdgeField('pause_duration_seconds', $event)"
      />

      <div class="flex flex-col gap-1.5 self-start">
        <label class="text-[13px] font-semibold text-foreground flex items-center">边界策略<span v-if="panel.dirtyFields.value.has('edge.boundary_strategy')" class="text-red-500 font-bold ml-0.5">*</span></label>
        <el-input
          v-if="isBoundaryStrategyLocked"
          :model-value="formatEdgeBoundaryStrategyLabel(edgeValues?.boundary_strategy)"
          readonly
          size="small"
          style="min-width: 220px"
        />
        <el-select
          v-else
          :model-value="edgeValues?.boundary_strategy ?? ''"
          size="small"
          class="!w-min"
          style="min-width: 220px"
          @update:model-value="panel.updateEdgeField('boundary_strategy', $event)"
        >
          <el-option
            v-for="option in EDGE_BOUNDARY_STRATEGY_OPTIONS"
            :key="option.value"
            :value="option.value"
            :label="option.label"
          />
        </el-select>
        <p v-if="isBoundaryStrategyLocked" class="text-[12px] text-muted-fg">
          该停顿由重排新建，边界策略固定为简单交叉淡化。
        </p>
        <p v-if="edgeValues?.effective_boundary_strategy" class="text-[12px] text-muted-fg">
          当前生效：{{ formatEdgeBoundaryStrategyLabel(edgeValues.effective_boundary_strategy) }}
        </p>
      </div>
    </div>
  </section>
</template>
