import { createRouter, createWebHistory } from 'vue-router'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', redirect: '/text-input' },
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
