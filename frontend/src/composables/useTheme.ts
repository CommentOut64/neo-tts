import { computed, ref } from "vue";
import {
  commitTheme,
  getCurrentTheme,
  getNextTheme,
} from "@/theme/themeShared";
import type { Theme } from "@/theme/themeShared";

// 全局单例状态
const currentTheme = ref<Theme>(getCurrentTheme());
const THEME_RIPPLE_DURATION_MS = 640;
const THEME_RIPPLE_EASING = "linear";

const isDark = computed(() => currentTheme.value === "dark");

export function useTheme() {
  function toggleTheme() {
    setTheme(getNextTheme(currentTheme.value));
  }

  /**
   * 带 clip-path 圆形扩散动画的主题切换
   * 从点击位置向外扩展覆盖全屏，不兼容 View Transition API 的浏览器降级为瞬切
   */
  function toggleThemeWithTransition(event: MouseEvent) {
    const doc = document as Document & {
      startViewTransition?: (cb: () => void) => { ready: Promise<void> };
    };

    // 不支持 View Transition API 时直接切换
    if (!doc.startViewTransition) {
      toggleTheme();
      return;
    }

    // 获取点击坐标
    const x = event.clientX;
    const y = event.clientY;

    // 计算到视口最远角的距离，作为圆形扩散的最终半径
    const endRadius = Math.hypot(
      Math.max(x, window.innerWidth - x),
      Math.max(y, window.innerHeight - y),
    );

    const nextTheme = getNextTheme(currentTheme.value);
    const transition = doc.startViewTransition(() => {
      setTheme(nextTheme);
    });

    transition.ready.then(() => {
      document.documentElement.animate(
        {
          clipPath: [
            `circle(0px at ${x}px ${y}px)`,
            `circle(${endRadius * 0.34}px at ${x}px ${y}px)`,
            `circle(${endRadius}px at ${x}px ${y}px)`,
          ],
        },
        {
          duration: THEME_RIPPLE_DURATION_MS,
          easing: THEME_RIPPLE_EASING,
          pseudoElement: "::view-transition-new(root)",
        },
      );
    });
  }

  function setTheme(theme: Theme) {
    currentTheme.value = commitTheme(theme);
  }

  return {
    currentTheme,
    isDark,
    toggleTheme,
    toggleThemeWithTransition,
    setTheme,
  };
}
