<script setup lang="ts">
import { ref } from 'vue'
import { UploadFilled } from '@element-plus/icons-vue'
import {
  resolveAbsolutePathForFile,
  selectAbsolutePathForFile,
  supportsNativeFilePathBridge,
} from '@/platform/fileSelection'

type FileUploaderPathSelection = {
  name: string
  absolutePath: string
  size: number
}

const props = withDefaults(defineProps<{
  accept: string
  maxSize?: number
  disabled?: boolean
  placeholder?: string
  hint?: string
  selectionMode?: 'file' | 'path'
}>(), {
  maxSize: 10 * 1024 * 1024,
  placeholder: '拖拽文件到此处，或点击选择',
  selectionMode: 'file',
})

const emit = defineEmits<{
  change: [file: File | null]
  pathChange: [selection: FileUploaderPathSelection | null]
  error: [message: string]
}>()

const isDragOver = ref(false)
const selectedEntry = ref<{
  name: string
  detail: string
} | null>(null)
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

async function handleFile(file: File) {
  if (!validateFile(file)) {
    return
  }
  if (props.selectionMode === 'path') {
    const absolutePath = resolveAbsolutePathForFile(file)
    if (!absolutePath) {
      emit('error', '当前运行环境无法解析本地绝对路径，请使用桌面版并通过拖拽或点击选择文件')
      return
    }
    selectedEntry.value = {
      name: file.name,
      detail: absolutePath,
    }
    emit('pathChange', {
      name: file.name,
      absolutePath,
      size: file.size,
    })
    return
  }
  selectedEntry.value = {
    name: file.name,
    detail: `${(file.size / 1024 / 1024).toFixed(1)} MB`,
  }
  emit('change', file)
}

async function onDrop(e: DragEvent) {
  isDragOver.value = false
  if (props.disabled) return
  const file = e.dataTransfer?.files[0]
  if (props.selectionMode === 'path' && !supportsNativeFilePathBridge()) {
    emit('error', '当前运行环境不支持通过拖拽解析绝对路径，请点击选择文件')
    return
  }
  if (file) await handleFile(file)
}

async function onTriggerSelect() {
  if (props.disabled) {
    return
  }
  if (props.selectionMode === 'path' && !supportsNativeFilePathBridge()) {
    const selection = await selectAbsolutePathForFile({
      accept: props.accept,
    })
    if (selection === null) {
      return
    }
    selectedEntry.value = {
      name: selection.name,
      detail: selection.absolutePath,
    }
    emit('pathChange', {
      name: selection.name,
      absolutePath: selection.absolutePath,
      size: 0,
    })
    return
  }
  fileInput.value?.click()
}

async function onFileInput(e: Event) {
  const input = e.target as HTMLInputElement
  const file = input.files?.[0]
  if (file) await handleFile(file)
  input.value = ''
}

function clear() {
  selectedEntry.value = null
  if (props.selectionMode === 'path') {
    emit('pathChange', null)
    return
  }
  emit('change', null)
}
</script>

<template>
  <div
    v-if="!selectedEntry"
    class="rounded-card border-2 border-dashed flex flex-col items-center justify-center h-[120px] transition-all duration-200 cursor-pointer"
    :class="[
      isDragOver ? 'border-accent bg-accent/10 shadow-glow-accent' : 'border-border bg-muted/30',
      disabled ? 'opacity-50 cursor-not-allowed' : 'hover:border-accent hover:bg-accent/10',
    ]"
    @dragover.prevent="isDragOver = true"
    @dragleave="isDragOver = false"
    @drop.prevent="onDrop"
    @click="onTriggerSelect"
  >
    <el-icon :size="28" class="text-muted-fg mb-2"><UploadFilled /></el-icon>
    <p class="text-sm text-muted-fg">{{ placeholder }}</p>
    <p v-if="hint" class="text-xs text-muted-fg/60 mt-1">{{ hint }}</p>
    <input ref="fileInput" type="file" :accept="accept" class="hidden" @change="onFileInput" />
  </div>
  <div v-else class="rounded-card border border-border bg-muted/30 px-4 py-3 flex items-center justify-between">
    <div>
      <p class="text-sm text-foreground">{{ selectedEntry.name }}</p>
      <p class="text-xs text-muted-fg break-all">{{ selectedEntry.detail }}</p>
    </div>
    <el-button size="small" text type="danger" @click="clear">移除</el-button>
  </div>
</template>
