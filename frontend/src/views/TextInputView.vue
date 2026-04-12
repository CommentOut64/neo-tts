<script setup lang="ts">
import { computed } from 'vue'

import TextInputArea from '@/components/text-input/TextInputArea.vue'
import FileImportZone from '@/components/text-input/FileImportZone.vue'
import SegmentPreviewList from '@/components/text-input/SegmentPreviewList.vue'
import SendToWorkspaceBar from '@/components/text-input/SendToWorkspaceBar.vue'
import { useInputDraft, type InputTextLanguage } from '@/composables/useInputDraft'
import { useStandardizationPreview } from '@/composables/useStandardizationPreview'
import { countNonPunctuationCharacters } from '@/utils/textStats'

const { text, textLanguage, setTextLanguage } = useInputDraft()
const {
  segments,
  totalSegments,
  isLoading,
  isLoadingMore,
  errorMessage,
  analysisStage,
  hasMore,
  loadMore,
} = useStandardizationPreview(text, textLanguage)

const totalCharacters = computed(() => Array.from(text.value).length)
const nonPunctuationCharacters = computed(() =>
  countNonPunctuationCharacters(text.value),
)

function handleTextLanguageChange(nextLanguage: InputTextLanguage) {
  setTextLanguage(nextLanguage)
}
</script>

<template>
  <div class="max-w-[1440px] mx-auto px-4 lg:px-8 py-6 h-[calc(100vh-3.5rem)] flex flex-col md:flex-row gap-6">
    <aside class="w-full md:w-[35%] lg:w-[30%] shrink-0 flex flex-col gap-5">
      <section class="bg-card rounded-card p-4 shadow-card border border-border dark:border-transparent animate-fall">
        <h3 class="text-[13px] font-semibold text-foreground mb-3">文本统计</h3>
        <div class="space-y-3 text-[13px] text-foreground">
          <div class="flex items-center justify-between gap-4">
            <span class="text-muted-fg">总字符数</span>
            <span>{{ totalCharacters }}</span>
          </div>
          <div class="flex items-center justify-between gap-4">
            <span class="text-muted-fg">非标点字符</span>
            <span>{{ nonPunctuationCharacters }}</span>
          </div>
          <div class="flex items-center justify-between gap-4">
            <span class="text-muted-fg">总段数</span>
            <span v-if="text.trim() && !isLoading">
              {{ totalSegments }}
            </span>
            <span v-else-if="text.trim()" class="text-muted-fg">分析中</span>
            <span v-else class="text-muted-fg">0</span>
          </div>
        </div>
      </section>

      <section class="bg-card rounded-card p-4 shadow-card border border-border dark:border-transparent animate-fall">
        <h3 class="text-[13px] font-semibold text-foreground mb-3">参数调整</h3>
        <div class="flex flex-col gap-1.5">
          <label class="text-[13px] font-semibold text-foreground">文本语言</label>
          <el-select
            :model-value="textLanguage"
            size="small"
            class="!w-min"
            style="min-width: 120px"
            @update:model-value="handleTextLanguageChange"
          >
            <el-option value="auto" label="自动" />
            <el-option value="zh" label="中文" />
            <el-option value="en" label="英文" />
            <el-option value="ja" label="日文" />
            <el-option value="ko" label="韩文" />
          </el-select>
          <p class="text-xs text-muted-fg mt-1">
            该设置会复用到 workspace 初始化请求；标准化预览仅对支持的显式语言生效。
          </p>
        </div>
      </section>
    </aside>

    <!-- 右侧主内容：输入区 + 预览区 -->
    <main class="w-full md:w-[65%] lg:w-[70%] flex flex-col gap-5 min-w-0 min-h-0 overflow-hidden">
      <!-- 上半区：文本输入 + 文件导入 -->
      <div class="flex flex-col xl:flex-row gap-5 shrink-0">
        <TextInputArea class="flex-1 min-w-0" />
        <div class="w-full xl:w-[280px] shrink-0 xl:self-start">
          <FileImportZone />
        </div>
      </div>

      <!-- 下半区：切分预览（完全吸收剩余高度，底部位置锁死） -->
      <SegmentPreviewList
        class="flex-1 min-h-[120px]"
        :text="text"
        :segments="segments"
        :total-segments="totalSegments"
        :is-loading="isLoading"
        :is-loading-more="isLoadingMore"
        :error-message="errorMessage"
        :analysis-stage="analysisStage"
        :has-more="hasMore"
        :load-more="loadMore"
      />

      <!-- 底部动作条（始终固定在底部） -->
      <SendToWorkspaceBar class="shrink-0" />
    </main>
  </div>
</template>
