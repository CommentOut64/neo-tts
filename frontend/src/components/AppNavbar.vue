<script setup lang="ts">
import { computed, watch, ref, onMounted, onUnmounted, nextTick } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Icon } from '@iconify/vue'
import { useTheme } from '@/composables/useTheme'
import type { ConnectionStatus } from '@/composables/useHealthCheck'
import { useRuntimeState } from '@/composables/useRuntimeState'
import { useEditSession } from '@/composables/useEditSession'
import { useWorkspaceDialogState } from '@/composables/useWorkspaceDialogState'
import { isExportBlockedByRenderJob } from './workspace/sessionHandoff'
import AboutDialog from './AboutDialog.vue'

defineProps<{
  status: ConnectionStatus
  isProgressStreamConnected?: boolean
}>()

const route = useRoute()
const router = useRouter()
const { isDark, toggleThemeWithTransition } = useTheme()
const { currentRenderJob } = useRuntimeState()
const { snapshot } = useEditSession()
const { exportDialogVisible, openExportDialog, closeExportDialog } = useWorkspaceDialogState()

const aboutDialogVisible = ref(false)

const navItems = [
  { path: '/text-input', label: '文本输入' },
  { path: '/workspace', label: '语音合成' },
  { path: '/voices', label: '模型管理' },
]

const canOpenExport = computed(() =>
  route.path === '/workspace' &&
  snapshot.value?.document_version != null &&
  !isExportBlockedByRenderJob(currentRenderJob.value),
)

function navigateTo(path: string) {
  if (path !== '/workspace') {
    closeExportDialog()
  }
  router.push(path)
}

const navRefs = ref<HTMLElement[]>([])
const indicatorStyle = ref<{ transform: string; width: string; opacity: number }>({
  transform: 'translateX(0)',
  width: '0px',
  opacity: 0,
})

function updateIndicator() {
  const index = navItems.findIndex(item => item.path === route.path)
  if (index === -1) {
    indicatorStyle.value.opacity = 0
    return
  }
  const el = navRefs.value[index]
  if (el) {
    const left = el.offsetLeft + 8
    const width = el.offsetWidth - 16
    indicatorStyle.value = {
      transform: `translateX(${left}px)`,
      width: `${width}px`,
      opacity: 1,
    }
  }
}

onMounted(() => {
  window.addEventListener('resize', updateIndicator)
  setTimeout(() => {
    updateIndicator()
  }, 50)
})

onUnmounted(() => {
  window.removeEventListener('resize', updateIndicator)
})

watch(
  () => route.path,
  async (path) => {
    if (path !== '/workspace' && exportDialogVisible.value) {
      closeExportDialog()
    }
    await nextTick()
    updateIndicator()
  },
  { immediate: true },
)
</script>

<template>
  <nav class="app-navbar fixed top-0 left-0 right-0 z-50 h-14 border-b flex items-center pl-6 pr-3">
    <div 
      class="flex items-center gap-2 mr-8 cursor-pointer hover:opacity-80 transition-opacity select-none"
      @click="aboutDialogVisible = true"
      title="关于"
    >
      <svg
        viewBox="0 0 32 32"
        aria-hidden="true"
        class="w-8 h-8 transition-colors duration-300"
        :class="{
          'text-green-500': status === 'online',
          'text-yellow-500': status === 'reconnecting',
          'text-red-500': status === 'offline'
        }"
      >
        <path
          fill="currentColor"
          d="M13 26h-2c-3.9 0-7-3.1-7-7v-2h2v2c0 2.8 2.2 5 5 5h2zm5-8h10c1.1 0 2 .9 2 2v6c0 1.1-.9 2-2 2h-2.4l-1.7 3l-1.7-1l2.3-4H28v-6H18v6h3v2h-3c-1.1 0-2-.9-2-2v-6c0-1.1.9-2 2-2m10-4h-2v-2c0-2.8-2.2-5-5-5h-4V5h4c3.9 0 7 3.1 7 7zM2 11h6v2H2zm0-4h12v2H2zm0-4h12v2H2z"
        />
      </svg>
      <span class="text-xl font-bold text-foreground">Neo TTS</span>
    </div>
    <div class="relative flex items-center gap-1">
      <button
        v-for="item in navItems"
        :key="item.path"
        ref="navRefs"
        class="relative px-4 py-2 text-sm font-medium transition-colors duration-150 rounded-btn"
        :class="route.path === item.path
          ? 'text-foreground'
          : 'text-muted-fg hover:text-foreground hover:bg-secondary'"
        @click="navigateTo(item.path)"
      >
        {{ item.label }}
      </button>
      <span
        class="absolute bottom-0 h-0.5 bg-accent rounded-full pointer-events-none transition-all duration-300 ease-[cubic-bezier(0.22,1,0.36,1)] will-change-[transform,width]"
        :style="indicatorStyle"
      />
    </div>
    <div class="ml-auto flex items-center gap-1">
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

      <!-- 设置图标按钮 -->
      <button
        class="w-8 h-8 flex items-center justify-center rounded-full transition-colors duration-200 text-muted-fg hover:text-foreground dark:hover:bg-secondary"
        aria-label="设置"
      >
        <Icon icon="uil:setting" width="20" height="20" aria-hidden="true" />
      </button>

      <!-- 主题切换按钮 -->
      <button
        class="w-8 h-8 flex items-center justify-center rounded-full transition-colors duration-200 text-muted-fg hover:text-foreground dark:hover:bg-secondary"
        :aria-label="isDark ? '切换到亮色模式' : '切换到暗色模式'"
        @click="toggleThemeWithTransition($event)"
      >
        <span class="theme-toggle-icon" aria-hidden="true">
          <Transition name="theme-icon">
            <Icon
              :key="isDark ? 'sun' : 'moon'"
              :icon="isDark ? 'boxicons:sun' : 'boxicons:moon-star'"
              width="20"
              height="20"
              class="theme-toggle-icon__glyph"
            />
          </Transition>
        </span>
      </button>

      <!-- 垂直分隔线与间距 -->
      <div class="w-px h-4 bg-border dark:bg-muted-fg/30 mx-3"></div>

      <!-- 导出轮廓按钮 (逻辑保留旧的属性或仅作占位) -->
      <div class="flex items-center gap-1">
        <el-button
          plain
          class="!bg-transparent !transition-all !duration-300 !text-sm !font-medium !px-4 !ml-0 !rounded-md"
          :disabled="!canOpenExport"
          @click="openExportDialog"
        >
          导出
        </el-button>
      </div>
    </div>

    <!-- 关于与自更新窗口 -->
    <AboutDialog v-model:visible="aboutDialogVisible" />
  </nav>
</template>

<style scoped>
.app-navbar {
  background-color: var(--app-shell-navbar-solid-bg);
  border-color: var(--app-shell-navbar-border);
  box-shadow: var(--app-shell-navbar-shadow);
  transition: background-color 0.5s ease, border-color 0.5s ease, box-shadow 0.5s ease;
}

.theme-toggle-icon {
  position: relative;
  width: 20px;
  height: 20px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}

.theme-toggle-icon__glyph {
  position: absolute;
  inset: 0;
  transform-origin: center;
  will-change: transform, opacity;
}

.theme-icon-enter-active,
.theme-icon-leave-active {
  transition:
    opacity 0.22s cubic-bezier(0.22, 1, 0.36, 1),
    transform 0.22s cubic-bezier(0.22, 1, 0.36, 1);
}

.theme-icon-enter-from {
  opacity: 0;
  transform: rotate(-72deg) scale(0.78);
}

.theme-icon-leave-to {
  opacity: 0;
  transform: rotate(72deg) scale(0.78);
}

.theme-icon-enter-to,
.theme-icon-leave-from {
  opacity: 1;
  transform: rotate(0deg) scale(1);
}

@supports ((-webkit-backdrop-filter: blur(0)) or (backdrop-filter: blur(0))) {
  .app-navbar {
    background-color: var(--app-shell-navbar-bg);
    -webkit-backdrop-filter: blur(18px);
    backdrop-filter: blur(18px);
  }
}

@media (prefers-reduced-motion: reduce) {
  .theme-icon-enter-active,
  .theme-icon-leave-active {
    transition: none;
  }

  .theme-icon-enter-from,
  .theme-icon-leave-to,
  .theme-icon-enter-to,
  .theme-icon-leave-from {
    transform: none;
  }
}
</style>
