<script setup lang="ts">
import type { VoiceProfile } from "@/types/tts";

import SharedParameterScopePanel from "./parameter-panel/SharedParameterScopePanel.vue";

defineProps<{
  voices: VoiceProfile[];
}>();
</script>

<template>
  <SharedParameterScopePanel
    :voices="voices"
    title="全局参数"
    hint="当前会话的全局默认运行期参数。提交后会创建新的配置。"
  />
</template>
