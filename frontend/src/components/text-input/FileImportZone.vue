<script setup lang="ts">
import { UploadFilled } from '@element-plus/icons-vue'
import { ElMessageBox, ElMessage } from 'element-plus'
import type { UploadFile } from 'element-plus'
import { useInputDraft } from '@/composables/useInputDraft'

const draft = useInputDraft()

async function handleChange(file: UploadFile) {
  const rawFile = file.raw
  if (!rawFile) return false
  
  if (rawFile.type !== 'text/plain' && !rawFile.name.endsWith('.txt')) {
    ElMessage.error('只支持导入 .txt 纯文本文件')
    return false
  }

  if (!draft.isEmpty.value) {
    try {
      await ElMessageBox.confirm('导入文件会覆盖当前输入内容，确认继续？', '确认覆盖', {
        confirmButtonText: '覆盖',
        cancelButtonText: '取消',
        type: 'warning'
      })
    } catch {
      return false
    }
  }

  const reader = new FileReader()
  reader.onload = (e) => {
    const content = e.target?.result
    if (typeof content === 'string') {
      draft.setText(content)
    }
  }
  reader.onerror = () => {
    ElMessage.error('读取文件失败')
  }
  reader.readAsText(rawFile)
  return false // Prevent default upload behavior
}
</script>

<template>
  <el-upload
    class="w-full"
    drag
    action=""
    :auto-upload="false"
    accept=".txt"
    :show-file-list="false"
    :on-change="handleChange"
  >
    <el-icon class="el-icon--upload text-muted-fg"><upload-filled /></el-icon>
    <div class="el-upload__text text-muted-fg">
      拖拽 .txt 文件到此处，或 <em>点击上传</em>
    </div>
    <template #tip>
      <div class="el-upload__tip text-muted-fg/70">
        导入文件将替换当前输入稿的内容
      </div>
    </template>
  </el-upload>
</template>
