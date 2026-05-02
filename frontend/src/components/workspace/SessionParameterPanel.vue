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
    title="全局参数"
    hint="当前会话的全局默认运行期参数。提交后会创建新的配置。"
  />
</template>
