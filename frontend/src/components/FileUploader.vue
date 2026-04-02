<script setup lang="ts">
import { ref } from 'vue'
import { UploadFilled } from '@element-plus/icons-vue'

const props = withDefaults(defineProps<{
  accept: string
  maxSize?: number
  disabled?: boolean
  placeholder?: string
  hint?: string
}>(), {
  maxSize: 10 * 1024 * 1024,
  placeholder: '拖拽文件到此处，或点击选择',
})

const emit = defineEmits<{
  change: [file: File | null]
  error: [message: string]
}>()

const isDragOver = ref(false)
const selectedFile = ref<File | null>(null)
const fileInput = ref<HTMLInputElement | null>(null)

function validateFile(file: File): boolean {
  const extensions = props.accept.split(',').map(e => e.trim().toLowerCase())
  const ext = '.' + file.name.split('.').pop()?.toLowerCase()
  if (!extensions.includes(ext)) {
    emit('error', `不支持的文件格式: ${ext}，允许: ${props.accept}`)
    return false
  }
  if (file.size > props.maxSize) {
    const maxMB = (props.maxSize / 1024 / 1024).toFixed(0)
    emit('error', `文件过大: ${(file.size / 1024 / 1024).toFixed(1)}MB，上限: ${maxMB}MB`)
    return false
  }
  return true
}

function handleFile(file: File) {
  if (validateFile(file)) {
    selectedFile.value = file
    emit('change', file)
  }
}

function onDrop(e: DragEvent) {
  isDragOver.value = false
  if (props.disabled) return
  const file = e.dataTransfer?.files[0]
  if (file) handleFile(file)
}

function onFileInput(e: Event) {
  const input = e.target as HTMLInputElement
  const file = input.files?.[0]
  if (file) handleFile(file)
  input.value = ''
}

function clear() {
  selectedFile.value = null
  emit('change', null)
}
</script>

<template>
  <div
    v-if="!selectedFile"
    class="rounded-card border-2 border-dashed flex flex-col items-center justify-center h-[120px] transition-all duration-200 cursor-pointer"
    :class="[
      isDragOver ? 'border-accent bg-accent/10 shadow-glow-accent' : 'border-border bg-muted/30',
      disabled ? 'opacity-50 cursor-not-allowed' : 'hover:border-accent hover:bg-accent/10',
    ]"
    @dragover.prevent="isDragOver = true"
    @dragleave="isDragOver = false"
    @drop.prevent="onDrop"
    @click="!disabled && fileInput?.click()"
  >
    <el-icon :size="28" class="text-muted-fg mb-2"><UploadFilled /></el-icon>
    <p class="text-sm text-muted-fg">{{ placeholder }}</p>
    <p v-if="hint" class="text-xs text-muted-fg/60 mt-1">{{ hint }}</p>
    <input ref="fileInput" type="file" :accept="accept" class="hidden" @change="onFileInput" />
  </div>
  <div v-else class="rounded-card border border-border bg-muted/30 px-4 py-3 flex items-center justify-between">
    <div>
      <p class="text-sm text-foreground">{{ selectedFile.name }}</p>
      <p class="text-xs text-muted-fg">{{ (selectedFile.size / 1024 / 1024).toFixed(1) }} MB</p>
    </div>
    <el-button size="small" text type="danger" @click="clear">移除</el-button>
  </div>
</template>
