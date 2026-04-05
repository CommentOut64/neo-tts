<script setup lang="ts">
import AppNavbar from '@/components/AppNavbar.vue'
import { useHealthCheck } from '@/composables/useHealthCheck'
import { useInferenceRuntime } from '@/composables/useInferenceRuntime'

const { status } = useHealthCheck()
const { isProgressStreamConnected } = useInferenceRuntime()
</script>

<template>
  <UApp>
    <div class="min-h-screen bg-background">
      <AppNavbar :status="status" :is-progress-stream-connected="isProgressStreamConnected" />
      <main class="pt-14">
        <RouterView />
      </main>
    </div>
  </UApp>
</template>
