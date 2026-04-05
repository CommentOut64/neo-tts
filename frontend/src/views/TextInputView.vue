<script setup lang="ts">
import TextInputArea from '@/components/text-input/TextInputArea.vue'
import FileImportZone from '@/components/text-input/FileImportZone.vue'
import SegmentPreviewList from '@/components/text-input/SegmentPreviewList.vue'
import SendToWorkspaceBar from '@/components/text-input/SendToWorkspaceBar.vue'
import { Document } from '@element-plus/icons-vue'
</script>

<template>
  <div class="flex h-[calc(100vh-3.5rem)] bg-background">
    <!-- 左侧占位 -->
    <div class="w-6 md:w-48 lg:w-64 border-r border-border shrink-0 bg-card/30 hidden md:block"></div>

    <!-- 右侧主内容：输入区 + 预览区 -->
    <main class="flex-1 flex flex-col p-4 md:p-6 lg:p-8 gap-5 min-w-0 min-h-0 bg-background/50 overflow-y-auto md:overflow-hidden">
      <div class="flex-1 flex flex-col lg:grid lg:grid-rows-2 gap-5 min-h-0">
        <!-- 上半区：文本输入与导入 -->
        <div class="lg:row-span-1 min-h-0 flex flex-col xl:flex-row gap-5">
          <TextInputArea class="flex-1 h-[300px] lg:h-auto min-h-0" />
          <div class="w-full xl:w-[280px] shrink-0">
            <FileImportZone />
          </div>
        </div>
        
        <!-- 下半区：切分预览 -->
        <SegmentPreviewList class="lg:row-span-1 h-[300px] lg:h-auto min-h-0" />
      </div>

      <!-- 底部动作条 -->
      <SendToWorkspaceBar class="shrink-0" />
    </main>
  </div>
</template>
