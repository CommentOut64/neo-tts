<script setup lang="ts">
import { useRoute, useRouter } from 'vue-router'
import { Microphone, Setting, Sunny, Moon, EditPen } from '@element-plus/icons-vue'
import StatusIndicator from './StatusIndicator.vue'
import { useTheme } from '@/composables/useTheme'
import type { ConnectionStatus } from '@/composables/useHealthCheck'

defineProps<{
  status: ConnectionStatus
  isProgressStreamConnected?: boolean
}>()

const route = useRoute()
const router = useRouter()
const { isDark, toggleThemeWithTransition } = useTheme()

const navItems = [
  { path: '/text-input', label: '文本输入', icon: EditPen },
  { path: '/workspace', label: '语音合成', icon: Microphone },
  { path: '/voices', label: '模型管理', icon: Setting },
]
</script>

<template>
  <nav class="fixed top-0 left-0 right-0 z-50 h-14 bg-primary border-b border-border flex items-center px-6">
    <div class="flex items-center gap-2 mr-8">
      <el-icon :size="22" class="text-accent"><Microphone /></el-icon>
      <span class="text-base font-semibold text-foreground">Neo TTS</span>
    </div>
    <div class="flex items-center gap-1">
      <button
        v-for="item in navItems"
        :key="item.path"
        class="relative px-4 py-2 text-sm font-medium transition-colors duration-150 rounded-btn"
        :class="route.path === item.path
          ? 'text-foreground'
          : 'text-muted-fg hover:text-foreground hover:bg-secondary'"
        @click="router.push(item.path)"
      >
        {{ item.label }}
        <span
          v-if="route.path === item.path"
          class="absolute bottom-0 left-2 right-2 h-0.5 bg-accent rounded-full"
        />
      </button>
    </div>
    <div class="ml-auto flex items-center gap-3">
      <!-- 预留导出位和运行态提示位 -->
      <div id="runtime-state-placeholder"></div>
      <div id="export-action-placeholder"></div>

      <!-- 进度流状态 -->
      <div v-if="isProgressStreamConnected !== undefined && route.path === '/studio'" class="flex items-center gap-1.5">
        <span
          class="w-1.5 h-1.5 rounded-full"
          :class="isProgressStreamConnected ? 'bg-accent' : 'bg-muted-fg/40'"
        />
        <span class="text-xs text-muted-fg">
          {{ isProgressStreamConnected ? '进度流在线' : '进度流离线' }}
        </span>
      </div>
      <button
        class="w-11 h-11 flex items-center justify-center rounded-full transition-colors duration-200 text-muted-fg hover:text-foreground hover:bg-secondary"
        :aria-label="isDark ? '切换到亮色模式' : '切换到暗色模式'"
        @click="toggleThemeWithTransition($event)"
      >
        <el-icon :size="18">
          <Sunny v-if="isDark" />
          <Moon v-else />
        </el-icon>
      </button>
      <StatusIndicator :status="status" />
    </div>
  </nav>
</template>
