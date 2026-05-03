<script setup lang="ts">
import type { RegistryBindingOption } from "@/types/ttsRegistry";

import SharedParameterScopePanel from "./parameter-panel/SharedParameterScopePanel.vue";

defineProps<{
  bindings: RegistryBindingOption[];
}>();
</script>

<template>
  <SharedParameterScopePanel
    :bindings="bindings"
    title="批量参数"
    hint="当前选中多段的统一运行期参数。多个值时会以“多个值”展示。"
  />
</template>
