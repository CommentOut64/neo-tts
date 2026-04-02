import { createRouter, createWebHistory } from 'vue-router'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', redirect: '/studio' },
    {
      path: '/studio',
      name: 'TtsStudio',
      component: () => import('@/views/TtsStudioView.vue'),
      meta: { title: '语音合成', icon: 'Microphone' },
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
