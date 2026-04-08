import { createApp } from 'vue'
import ElementPlus from 'element-plus'
import ui from '@nuxt/ui/vue-plugin'
import 'element-plus/dist/index.css'
import './assets/styles.css'
import App from './App.vue'
import router from './router'

async function bootstrap() {
  const app = createApp(App)
  app.use(ElementPlus)
  app.use(router)
  app.use(ui)

  await router.isReady()
  app.mount('#app')
}

void bootstrap()
