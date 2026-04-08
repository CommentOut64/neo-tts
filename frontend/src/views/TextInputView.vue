<script setup lang="ts">
import TextInputArea from '@/components/text-input/TextInputArea.vue'
import FileImportZone from '@/components/text-input/FileImportZone.vue'
import SegmentPreviewList from '@/components/text-input/SegmentPreviewList.vue'
import SendToWorkspaceBar from '@/components/text-input/SendToWorkspaceBar.vue'
import { Document } from '@element-plus/icons-vue'
</script>

<template>
  <div class="max-w-[1440px] mx-auto px-4 lg:px-8 py-6 h-[calc(100vh-3.5rem)] flex flex-col md:flex-row gap-6">
    <!-- 左侧占位 -->
    <div class="w-full md:w-[35%] lg:w-[30%] hidden md:block"></div>

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
      <SegmentPreviewList class="flex-1 min-h-[120px]" />

      <!-- 底部动作条（始终固定在底部） -->
      <SendToWorkspaceBar class="shrink-0" />
    </main>
  </div>
</template>
