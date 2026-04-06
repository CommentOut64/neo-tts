<script setup lang="ts">
import { computed } from "vue";

import ParameterSlider from "@/components/ParameterSlider.vue";
import { useParameterPanel } from "@/composables/useParameterPanel";

const panel = useParameterPanel();

const edgeValues = computed(() => panel.displayValues.value.edge);
</script>

<template>
  <section class="bg-card rounded-card p-4 shadow-card">
    <h3 class="text-[13px] font-semibold text-foreground mb-1">Edge 参数</h3>
    <p class="text-[12px] text-muted-fg">
      调整段间停顿与边界策略。提交后仅持久化配置，不立即触发重推理。
    </p>
  </section>

  <section class="bg-card rounded-card p-4 shadow-card">
    <h3 class="text-[13px] font-semibold text-foreground mb-3">停顿与拼接</h3>

    <div class="space-y-4">
      <ParameterSlider
        :model-value="edgeValues?.pause_duration_seconds ?? 0.3"
        label="停顿时长"
        :min="0"
        :max="2"
        :step="0.05"
        unit="s"
        tooltip="控制两段之间的静音时长"
        @update:model-value="panel.updateEdgeField('pause_duration_seconds', $event)"
      />

      <div class="flex flex-col gap-1.5 self-start">
        <label class="text-[13px] font-semibold text-foreground">边界策略</label>
        <el-select
          :model-value="edgeValues?.boundary_strategy ?? ''"
          size="small"
          class="!w-min"
          style="min-width: 220px"
          @update:model-value="panel.updateEdgeField('boundary_strategy', $event)"
        >
          <el-option value="latent_overlap_then_equal_power_crossfade" label="Crossfade" />
          <el-option value="crossfade" label="Simple Crossfade" />
          <el-option value="hard_cut" label="Hard Cut" />
        </el-select>
        <p v-if="edgeValues?.effective_boundary_strategy" class="text-[12px] text-muted-fg">
          当前生效：{{ edgeValues.effective_boundary_strategy }}
        </p>
      </div>
    </div>
  </section>
</template>
