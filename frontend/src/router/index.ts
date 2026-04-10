import { defineComponent } from 'vue'
import { createRouter, createWebHistory } from 'vue-router'
import { resolveAppEntryPath } from './resolveAppEntry'

const AppEntryResolvingView = defineComponent({
  name: 'AppEntryResolvingView',
  render: () => null,
})

// 页面首次加载时启用 fall 动画，动画结束后自动移除
document.documentElement.classList.add('page-entering')
setTimeout(() => document.documentElement.classList.remove('page-entering'), 500)

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/',
      name: 'AppEntry',
      component: AppEntryResolvingView,
      beforeEnter: async () => ({ path: await resolveAppEntryPath(), replace: true }),
    },
    {
      path: '/text-input',
      name: 'TextInput',
      component: () => import('@/views/TextInputView.vue'),
      meta: { title: '文本输入', icon: 'EditPen' },
    },
    {
      path: '/workspace',
      name: 'Workspace',
      component: () => import('@/views/WorkspaceView.vue'),
      meta: { title: '语音合成', icon: 'Microphone' },
    },
    {
      path: '/studio',
      name: 'TtsStudio',
      component: () => import('@/views/TtsStudioView.vue'),
      meta: { title: '旧版合成', icon: 'Microphone' },
    },
    {
      path: '/voices',
      name: 'VoiceAdmin',
      component: () => import('@/views/VoiceAdminView.vue'),
      meta: { title: '模型管理', icon: 'Setting' },
    },
  ],
})

export default router

/**
 * 路由切换时触发 fall 入场动画。
 * afterEach 挂载 page-entering，500ms 后自动移除，
 * 确保只有页面入场瞬间的 card 播放动画，后续局部重渲染不受影响。
 */
let enteringTimer: ReturnType<typeof setTimeout> | undefined
router.afterEach(() => {
  clearTimeout(enteringTimer)
  document.documentElement.classList.add('page-entering')
  enteringTimer = setTimeout(() => document.documentElement.classList.remove('page-entering'), 500)
})
