<script setup lang="ts">
import AppNavbar from '@/components/AppNavbar.vue'
import { useHealthCheck } from '@/composables/useHealthCheck'
import { useInferenceRuntime } from '@/composables/useInferenceRuntime'

const { status } = useHealthCheck()
const { isProgressStreamConnected } = useInferenceRuntime('App')
</script>

<template>
  <UApp>
    <div class="app-shell min-h-screen">
      <div aria-hidden="true" class="app-shell__backdrop"></div>
      <AppNavbar :status="status" :is-progress-stream-connected="isProgressStreamConnected" />
      <main class="app-shell__main pt-14">
        <RouterView />
      </main>
    </div>
  </UApp>
</template>

<style scoped>
.app-shell {
  position: relative;
  isolation: isolate;
  background-color: var(--color-background);
}

.app-shell__backdrop {
  position: fixed;
  inset: 0;
  z-index: 0;
  pointer-events: none;
  background-color: var(--color-background);
  background-image: var(--app-shell-bg);
  background-repeat: no-repeat;
  background-size: cover;
}

.app-shell__main {
  position: relative;
  z-index: 1;
}
</style>
