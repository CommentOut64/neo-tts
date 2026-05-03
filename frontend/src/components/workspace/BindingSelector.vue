<script setup lang="ts">
import { computed } from "vue";

import type { RegistryBindingOption } from "@/types/ttsRegistry";

const props = defineProps<{
  modelValue: string;
  bindings: RegistryBindingOption[];
  disabled?: boolean;
  placeholder?: string;
}>();

const emit = defineEmits<{
  "update:model-value": [value: string];
}>();

const groupedBindings = computed(() => {
  const groups = new Map<string, RegistryBindingOption[]>();
  for (const binding of props.bindings) {
    const key = `${binding.workspaceId}:${binding.mainModelId}`;
    const list = groups.get(key) ?? [];
    list.push(binding);
    groups.set(key, list);
  }
  return Array.from(groups.values());
});
</script>

<template>
  <el-select
    :model-value="modelValue"
    :placeholder="placeholder ?? '选择模型绑定'"
    :disabled="disabled"
    size="default"
    class="!w-full"
    @update:model-value="emit('update:model-value', $event)"
  >
    <el-option-group
      v-for="group in groupedBindings"
      :key="`${group[0].workspaceId}:${group[0].mainModelId}`"
      :label="`${group[0].workspaceDisplayName} / ${group[0].mainModelDisplayName}`"
    >
      <el-option
        v-for="binding in group"
        :key="binding.bindingKey"
        :value="binding.bindingKey"
        :label="binding.label"
      />
    </el-option-group>
  </el-select>
</template>
