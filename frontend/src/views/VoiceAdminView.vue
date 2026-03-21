<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Refresh, Plus, Microphone } from '@element-plus/icons-vue'
import type { VoiceProfile } from '@/types/tts'
import { deleteVoice, fetchVoices, fetchVoiceDetail, reloadVoices, uploadVoice } from '@/api/tts'
import FileUploader from '@/components/FileUploader.vue'

const voices = ref<VoiceProfile[]>([])
const loading = ref(false)
const reloading = ref(false)

// Detail drawer state
const detailDrawerVisible = ref(false)
const detailVoice = ref<VoiceProfile | null>(null)
const detailLoading = ref(false)

async function handleDetail(voice: VoiceProfile) {
  detailDrawerVisible.value = true
  detailLoading.value = true
  try {
    detailVoice.value = await fetchVoiceDetail(voice.name)
  } catch (err: unknown) {
    ElMessage.error(`加载详情失败: ${(err as Error).message}`)
    detailVoice.value = voice
  } finally {
    detailLoading.value = false
  }
}

// Upload dialog state
const uploadDialogVisible = ref(false)
const uploading = ref(false)
const uploadForm = ref({
  name: '',
  description: '',
  ref_text: '',
  ref_lang: 'zh',
  gpt_file: null as File | null,
  sovits_file: null as File | null,
  ref_audio_file: null as File | null,
})

function resetUploadForm() {
  uploadForm.value = {
    name: '', description: '', ref_text: '', ref_lang: 'zh',
    gpt_file: null, sovits_file: null, ref_audio_file: null,
  }
}

async function loadVoices() {
  loading.value = true
  try {
    voices.value = await fetchVoices()
  } catch (err: unknown) {
    ElMessage.error(`加载模型列表失败: ${(err as Error).message}`)
  } finally {
    loading.value = false
  }
}

async function handleReload() {
  reloading.value = true
  try {
    const result = await reloadVoices()
    ElMessage.success(`刷新成功，共 ${result.count} 个模型`)
    await loadVoices()
  } catch (err: unknown) {
    ElMessage.error(`刷新失败: ${(err as Error).message}`)
  } finally {
    reloading.value = false
  }
}

async function handleUploadSubmit() {
  const f = uploadForm.value
  if (!f.name || !f.gpt_file || !f.sovits_file || !f.ref_audio_file || !f.ref_text) {
    ElMessage.warning('请填写所有必填项')
    return
  }
  uploading.value = true
  try {
    await uploadVoice({
      name: f.name,
      description: f.description,
      ref_text: f.ref_text,
      ref_lang: f.ref_lang,
      gpt_file: f.gpt_file,
      sovits_file: f.sovits_file,
      ref_audio_file: f.ref_audio_file,
    })
    ElMessage.success(`上传成功: ${f.name}`)
    uploadDialogVisible.value = false
    resetUploadForm()
    await loadVoices()
  } catch (err: unknown) {
    ElMessage.error(`上传失败: ${(err as Error).message}`)
  } finally {
    uploading.value = false
  }
}

async function handleDelete(voice: VoiceProfile) {
  try {
    await ElMessageBox.confirm(
      `确定删除模型 "${voice.name}"？此操作不可恢复。`,
      '确认删除',
      { confirmButtonText: '删除', cancelButtonText: '取消', type: 'warning' },
    )
    await deleteVoice(voice.name)
    ElMessage.success(`已删除模型: ${voice.name}`)
    await loadVoices()
  } catch {
    // user cancelled
  }
}

onMounted(loadVoices)
</script>

<template>
  <div class="max-w-[1440px] mx-auto px-8 py-8">
    <!-- Page header -->
    <div class="flex items-center justify-between mb-6">
      <h1 class="text-2xl font-bold text-foreground">模型管理</h1>
      <div class="flex items-center gap-3">
        <el-button :icon="Refresh" :loading="reloading" @click="handleReload">刷新配置</el-button>
        <el-button type="primary" :icon="Plus" @click="uploadDialogVisible = true">上传模型</el-button>
      </div>
    </div>

    <!-- Model list header -->
    <div class="mb-4 flex items-center justify-between">
      <h2 class="text-lg font-semibold text-foreground">已导入模型</h2>
      <span class="text-sm text-muted-fg">共 {{ voices.length }} 个</span>
    </div>

    <!-- Table -->
    <el-table v-if="voices.length > 0" :data="voices" v-loading="loading" class="w-full">
      <el-table-column prop="name" label="模型名称" min-width="160">
        <template #default="{ row }">
          <div>
            <span class="text-foreground font-medium">{{ row.name }}</span>
            <p v-if="row.description" class="text-xs text-muted-fg mt-0.5">{{ row.description }}</p>
          </div>
        </template>
      </el-table-column>
      <el-table-column prop="ref_lang" label="语言" width="80" align="center">
        <template #default="{ row }">
          <el-tag :type="row.ref_lang === 'zh' ? '' : 'success'" size="small">
            {{ { zh: '中文', en: 'EN', ja: 'JA', ko: 'KO' }[row.ref_lang as string] || row.ref_lang }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="ref_text" label="参考文本" width="240" show-overflow-tooltip />
      <el-table-column label="操作" width="160" align="center">
        <template #default="{ row }">
          <el-button size="small" text type="primary" @click="handleDetail(row)">详情</el-button>
          <el-button size="small" text type="danger" @click="handleDelete(row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <!-- Empty state -->
    <div v-else-if="!loading" class="flex flex-col items-center justify-center py-20 rounded-card bg-card">
      <div class="w-16 h-16 rounded-full bg-muted flex items-center justify-center mb-4">
        <el-icon :size="28" class="text-muted-fg"><Microphone /></el-icon>
      </div>
      <p class="text-lg text-muted-fg mb-2">还没有导入任何模型</p>
      <p class="text-sm text-muted-fg/70">
        点击"上传模型"按钮，或在
        <code class="bg-muted px-1.5 py-0.5 rounded text-xs">config/voices.json</code>
        中手动配置后点击刷新
      </p>
    </div>

    <!-- Upload dialog -->
    <el-dialog v-model="uploadDialogVisible" title="上传模型" width="520px" @close="resetUploadForm">
      <div class="space-y-4">
        <div>
          <label class="text-[13px] font-semibold text-foreground block mb-1.5">模型名称 *</label>
          <el-input v-model="uploadForm.name" placeholder="唯一标识，如 neuro1" />
        </div>
        <div>
          <label class="text-[13px] font-semibold text-foreground block mb-1.5">描述</label>
          <el-input v-model="uploadForm.description" placeholder="模型描述（选填）" />
        </div>
        <div>
          <label class="text-[13px] font-semibold text-foreground block mb-1.5">GPT 权重 (.ckpt) *</label>
          <FileUploader accept=".ckpt" :max-size="500 * 1024 * 1024" placeholder="选择 GPT 权重文件" @change="uploadForm.gpt_file = $event" />
        </div>
        <div>
          <label class="text-[13px] font-semibold text-foreground block mb-1.5">SoVITS 权重 (.pth) *</label>
          <FileUploader accept=".pth" :max-size="500 * 1024 * 1024" placeholder="选择 SoVITS 权重文件" @change="uploadForm.sovits_file = $event" />
        </div>
        <div>
          <label class="text-[13px] font-semibold text-foreground block mb-1.5">参考音频 *</label>
          <FileUploader accept=".wav,.mp3,.flac" :max-size="10 * 1024 * 1024" placeholder="选择参考音频文件（< 30s）" @change="uploadForm.ref_audio_file = $event" />
        </div>
        <div>
          <label class="text-[13px] font-semibold text-foreground block mb-1.5">参考文本 *</label>
          <el-input v-model="uploadForm.ref_text" type="textarea" :rows="2" placeholder="参考音频对应的文本内容" />
        </div>
        <div class="flex items-center gap-2">
          <label class="text-[13px] font-semibold text-foreground whitespace-nowrap">参考语言</label>
          <el-select v-model="uploadForm.ref_lang" size="small" class="w-28">
            <el-option value="zh" label="中文" />
            <el-option value="en" label="English" />
            <el-option value="ja" label="日本語" />
            <el-option value="ko" label="한국어" />
          </el-select>
        </div>
      </div>
      <template #footer>
        <el-button @click="uploadDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="uploading" @click="handleUploadSubmit">
          {{ uploading ? '上传中...' : '确认上传' }}
        </el-button>
      </template>
    </el-dialog>

    <!-- Detail drawer -->
    <el-drawer v-model="detailDrawerVisible" title="模型详情" size="400px">
      <div v-if="detailVoice" v-loading="detailLoading" class="space-y-4 text-sm">
        <div>
          <label class="text-muted-fg text-xs block mb-1">名称</label>
          <p class="text-foreground font-medium">{{ detailVoice.name }}</p>
        </div>
        <div v-if="detailVoice.description">
          <label class="text-muted-fg text-xs block mb-1">描述</label>
          <p class="text-foreground">{{ detailVoice.description }}</p>
        </div>
        <div>
          <label class="text-muted-fg text-xs block mb-1">GPT 路径</label>
          <p class="text-foreground break-all text-xs font-mono bg-muted/30 px-2 py-1 rounded">{{ detailVoice.gpt_path }}</p>
        </div>
        <div>
          <label class="text-muted-fg text-xs block mb-1">SoVITS 路径</label>
          <p class="text-foreground break-all text-xs font-mono bg-muted/30 px-2 py-1 rounded">{{ detailVoice.sovits_path }}</p>
        </div>
        <div>
          <label class="text-muted-fg text-xs block mb-1">参考音频</label>
          <p class="text-foreground break-all text-xs font-mono bg-muted/30 px-2 py-1 rounded">{{ detailVoice.ref_audio }}</p>
        </div>
        <div>
          <label class="text-muted-fg text-xs block mb-1">参考文本</label>
          <p class="text-foreground">{{ detailVoice.ref_text }}</p>
        </div>
        <div class="flex gap-4">
          <div>
            <label class="text-muted-fg text-xs block mb-1">语言</label>
            <p class="text-foreground">{{ detailVoice.ref_lang }}</p>
          </div>
          <div>
            <label class="text-muted-fg text-xs block mb-1">托管</label>
            <p class="text-foreground">{{ detailVoice.managed ? '是' : '否' }}</p>
          </div>
        </div>
        <div v-if="detailVoice.created_at" class="flex gap-4">
          <div>
            <label class="text-muted-fg text-xs block mb-1">创建时间</label>
            <p class="text-foreground text-xs">{{ detailVoice.created_at }}</p>
          </div>
          <div v-if="detailVoice.updated_at">
            <label class="text-muted-fg text-xs block mb-1">更新时间</label>
            <p class="text-foreground text-xs">{{ detailVoice.updated_at }}</p>
          </div>
        </div>
      </div>
    </el-drawer>
  </div>
</template>
