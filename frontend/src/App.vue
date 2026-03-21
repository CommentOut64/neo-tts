<script setup lang="ts">
import AppNavbar from '@/components/AppNavbar.vue'
import { useHealthCheck } from '@/composables/useHealthCheck'

const { status } = useHealthCheck()
</script>

<template>
  <div class="min-h-screen bg-background">
    <AppNavbar :status="status" />
    <main class="pt-14">
      <RouterView />
    </main>
  </div>
</template>
