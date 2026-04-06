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
    title="批量参数"
    hint="当前选中多段的统一运行期参数。多个值时会以“多个值”展示。"
  />
</template>
