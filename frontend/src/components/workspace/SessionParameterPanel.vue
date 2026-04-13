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
    title="会话参数"
    hint="当前编辑会话的默认运行期参数。提交后会创建新的配置。"
  />
</template>
