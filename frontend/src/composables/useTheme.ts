import { ref, computed, watch } from 'vue'

export type Theme = 'light' | 'dark'

const STORAGE_KEY = 'gpt-sovits-theme'

// 全局单例状态
const currentTheme = ref<Theme>(
  (localStorage.getItem(STORAGE_KEY) as Theme) || 'dark'
)

function applyTheme(theme: Theme) {
  const root = document.documentElement
  if (theme === 'dark') {
    root.classList.add('dark')
  } else {
    root.classList.remove('dark')
  }
}

// 初始化时立即应用
applyTheme(currentTheme.value)

// 模块级 watcher（单例，避免多组件调用 useTheme 时重复注册）
watch(currentTheme, (theme) => {
  applyTheme(theme)
  localStorage.setItem(STORAGE_KEY, theme)
})

const isDark = computed(() => currentTheme.value === 'dark')

export function useTheme() {
  function toggleTheme() {
    currentTheme.value = currentTheme.value === 'dark' ? 'light' : 'dark'
  }

  /**
   * 带 clip-path 圆形扩散动画的主题切换
   * 从点击位置向外扩展覆盖全屏，不兼容 View Transition API 的浏览器降级为瞬切
   */
  function toggleThemeWithTransition(event: MouseEvent) {
    const doc = document as Document & {
      startViewTransition?: (cb: () => void) => { ready: Promise<void> }
    }

    // 不支持 View Transition API 时直接切换
    if (!doc.startViewTransition) {
      toggleTheme()
      return
    }

    // 获取点击坐标
    const x = event.clientX
    const y = event.clientY

    // 计算到视口最远角的距离，作为圆形扩散的最终半径
    const endRadius = Math.hypot(
      Math.max(x, window.innerWidth - x),
      Math.max(y, window.innerHeight - y),
    )

    const transition = doc.startViewTransition(() => {
      toggleTheme()
    })

    transition.ready.then(() => {
      document.documentElement.animate(
        {
          clipPath: [
            `circle(0px at ${x}px ${y}px)`,
            `circle(${endRadius}px at ${x}px ${y}px)`,
          ],
        },
        {
          duration: 400,
          easing: 'ease-out',
          pseudoElement: '::view-transition-new(root)',
        },
      )
    })
  }

  function setTheme(theme: Theme) {
    currentTheme.value = theme
  }

  return { currentTheme, isDark, toggleTheme, toggleThemeWithTransition, setTheme }
}
