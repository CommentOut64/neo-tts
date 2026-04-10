# UI/UX 设计规格：GPT-SoVITS TTS Studio（归档）

> Archived: 2026-04-10
> Reason:
> - 文档以 `/studio` 双页架构和 `/v1/audio/speech` 主链为中心，已不再代表当前前端主流程
> Current Entry:
> - `/llmdoc/overview/backend-overview.md`
> - `/llmdoc/overview/edit-session-domain-overview.md`

**设计时间**：2026-03-21
**目标平台**：Web (Desktop-first, Responsive)
**技术栈**：Vue 3 (Composition API) + TypeScript + Tailwind CSS + Element Plus
**后端对接**：FastAPI (`/v1/audio/speech`, `/v1/voices`, `/v1/voices/{voice_name}`, `POST /v1/voices/upload`, `DELETE /v1/voices/{voice_name}`, `/v1/voices/reload`, `/health`)

---

## 1. 设计系统 (Design System)

### 1.1 颜色 Token

Tailwind 自定义配置（`tailwind.config.ts` extend 部分）：

```typescript
// tailwind.config.ts
import type { Config } from 'tailwindcss'

export default {
  darkMode: 'class',
  content: ['./index.html', './src/**/*.{vue,ts,tsx}'],
  theme: {
    extend: {
      colors: {
        // 语义色
        primary:        '#1E293B',
        secondary:      '#334155',
        accent:         '#22C55E',
        background:     '#0F172A',
        foreground:     '#F8FAFC',
        card:           '#1B2336',
        'card-fg':      '#F8FAFC',
        muted:          '#272F42',
        'muted-fg':     '#94A3B8',
        border:         '#475569',
        destructive:    '#EF4444',
        cta:            '#3B82F6',

        // 状态色
        'success':      '#22C55E',
        'warning':      '#F59E0B',
        'error':        '#EF4444',
        'info':         '#3B82F6',
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', '-apple-system', 'sans-serif'],
      },
      borderRadius: {
        'card': '12px',
        'btn':  '8px',
        'input': '8px',
      },
      boxShadow: {
        'card':     '0 2px 8px rgba(0, 0, 0, 0.3)',
        'card-hover': '0 4px 16px rgba(0, 0, 0, 0.4)',
        'glow-accent': '0 0 12px rgba(34, 197, 94, 0.25)',
        'glow-cta':    '0 0 12px rgba(59, 130, 246, 0.25)',
      },
    },
  },
} satisfies Config
```

### 1.2 字体规范

| 层级 | 字号 | 字重 | 行高 | Tailwind 类 |
|------|------|------|------|-------------|
| H1 页面标题 | 24px | Bold (700) | 1.3 | `text-2xl font-bold leading-tight` |
| H2 区块标题 | 18px | Semibold (600) | 1.4 | `text-lg font-semibold` |
| H3 小节标题 | 16px | Semibold (600) | 1.5 | `text-base font-semibold` |
| Body 正文 | 14px | Regular (400) | 1.6 | `text-sm font-normal leading-relaxed` |
| Caption 辅助文字 | 12px | Regular (400) | 1.5 | `text-xs font-normal` |
| Button 按钮 | 14px | Medium (500) | 1.0 | `text-sm font-medium` |
| Label 表单标签 | 13px | Semibold (600) | 1.4 | `text-[13px] font-semibold` |

### 1.3 间距系统 (4dp Base Grid)

| Token | 值 | Tailwind | 使用场景 |
|-------|-----|---------|---------|
| space-xs | 4px | `p-1` / `gap-1` | 图标与文字间距 |
| space-sm | 8px | `p-2` / `gap-2` | 紧凑元素间距 |
| space-md | 12px | `p-3` / `gap-3` | 表单项间距 |
| space-base | 16px | `p-4` / `gap-4` | 卡片内边距、区块间距 |
| space-lg | 24px | `p-6` / `gap-6` | 区块间分隔 |
| space-xl | 32px | `p-8` / `gap-8` | 页面级留白 |
| space-2xl | 48px | `p-12` / `gap-12` | 主区域间距 |

### 1.4 圆角与阴影

| 元素 | 圆角 | 阴影 |
|------|------|------|
| 页面容器 | 0 | 无 |
| 卡片/面板 | 12px (`rounded-card`) | `shadow-card` |
| 按钮 | 8px (`rounded-btn`) | 无 (hover 时 `shadow-glow-cta`) |
| 输入框 | 8px (`rounded-input`) | 无 |
| 下拉菜单 | 8px | `shadow-card` |
| 音频播放条 | 8px | 无 |
| 头像/图标容器 | 50% (`rounded-full`) | 无 |

### 1.5 组件状态规范

所有可交互元素遵循以下五种状态：

| 状态 | 视觉变化 | 过渡时长 |
|------|---------|---------|
| **Default** | 基准样式 | - |
| **Hover** | 背景亮度 +8%，CTA 按钮加 `shadow-glow-cta` | 150ms `ease-out` |
| **Active/Pressed** | 背景亮度 -4%，`scale(0.98)` | 100ms `ease-in` |
| **Disabled** | `opacity: 0.5`，`cursor: not-allowed`，移除 hover 效果 | - |
| **Loading** | 内容替换为 spinner + "处理中..." 文字，同时 disabled | 200ms `fade` |

按钮状态的 Tailwind 实现：

```html
<!-- CTA 按钮 -->
<button class="
  bg-cta text-foreground font-medium text-sm
  rounded-btn px-6 py-2.5 min-h-[44px] min-w-[120px]
  transition-all duration-150 ease-out
  hover:shadow-glow-cta hover:brightness-110
  active:scale-[0.98] active:brightness-95
  disabled:opacity-50 disabled:cursor-not-allowed disabled:hover:shadow-none disabled:hover:brightness-100
">
  开始推理
</button>

<!-- Destructive 按钮 -->
<button class="
  bg-destructive/10 text-destructive border border-destructive/30
  rounded-btn px-4 py-2 min-h-[44px]
  transition-all duration-150
  hover:bg-destructive/20
  active:scale-[0.98]
">
  删除
</button>
```

### 1.6 Element Plus 主题覆写

Element Plus 需覆写为暗色方案，在 `src/assets/styles.css` 中：

```css
/* Element Plus 暗色主题覆写 */
:root {
  --el-color-primary: #3B82F6;
  --el-color-success: #22C55E;
  --el-color-warning: #F59E0B;
  --el-color-danger: #EF4444;
  --el-color-info: #94A3B8;

  --el-bg-color: #0F172A;
  --el-bg-color-overlay: #1B2336;
  --el-bg-color-page: #0F172A;

  --el-text-color-primary: #F8FAFC;
  --el-text-color-regular: #CBD5E1;
  --el-text-color-secondary: #94A3B8;
  --el-text-color-placeholder: #64748B;

  --el-border-color: #475569;
  --el-border-color-light: #334155;
  --el-border-color-lighter: #272F42;

  --el-fill-color: #272F42;
  --el-fill-color-light: #1B2336;
  --el-fill-color-blank: #0F172A;

  --el-border-radius-base: 8px;
  --el-font-family: 'Inter', system-ui, -apple-system, sans-serif;
  --el-font-size-base: 14px;
}
```

---

## 2. 全局布局与路由

### 2.1 导航结构：顶部导航栏

采用固定顶部导航栏（非侧边栏），理由：
- 只有两个核心页面，侧边栏浪费横向空间
- TTS 推理页面需要最大化左右分栏的可用宽度
- 顶部导航在移动端折叠更自然

```
+==================================================================+
|  [Logo/品牌] GPT-SoVITS Studio    [语音合成] [模型管理]  [状态灯] |
+==================================================================+
|                                                                    |
|                        Page Content                                |
|                                                                    |
+==================================================================+
```

顶部导航栏高度：56px，固定定位 `fixed top-0`，页面内容 `pt-14` 偏移。

导航栏 ASCII 细化：

```
+------------------------------------------------------------------+
| [波形图标] GPT-SoVITS Studio                                     |
|                                                                    |
|         [语音合成]  [模型管理]               [●] Backend Online    |
+------------------------------------------------------------------+
```

- 左侧：品牌图标（波形 SVG）+ 产品名
- 中部：路由 Tab（当前页面高亮，底部 2px accent 线条）
- 右侧：后端连接状态指示器（绿点 = 在线，红点 = 离线，黄点 = 重连中）

### 2.2 路由规划

```typescript
// src/router/index.ts
const routes = [
  {
    path: '/',
    redirect: '/studio',
  },
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
]
```

默认落地页为 `/studio`（语音合成），因为这是用户最高频操作。

### 2.3 响应式断点策略

| 屏幕 | Tailwind 前缀 | 宽度范围 | 布局策略 |
|------|---------------|---------|---------|
| Mobile | (default) | < 768px | 单列堆叠，参数面板折叠 |
| Tablet | `md:` | 768px - 1279px | 左右分栏 40:60，参数面板可折叠 |
| Desktop | `lg:` | 1280px - 1535px | 左右分栏 35:65 |
| Wide | `xl:` | >= 1536px | 左右分栏 30:70，最大宽度 1440px 居中 |

页面最大宽度：`max-w-[1440px] mx-auto`，防止超宽屏下内容过度拉伸。

---

## 3. 页面 1：模型管理 (VoiceAdminView)

### 3.1 页面布局

```
+------------------------------------------------------------------+
|  NavBar                                                           |
+------------------------------------------------------------------+
|  padding: 32px                                                    |
|                                                                    |
|  +--------------------------------------------------------------+ |
|  | H1: 模型管理                                    [刷新按钮]   | |
|  +--------------------------------------------------------------+ |
|                                                                    |
|  +--------------------------------------------------------------+ |
|  |  拖拽上传区 (DragUploadZone)                                 | |
|  |  +----------------------------------------------------------+| |
|  |  |                                                          || |
|  |  |     [上传图标]                                           || |
|  |  |     拖拽模型文件到此处，或 [点击选择文件]                || |
|  |  |     支持格式：.ckpt, .pth                                || |
|  |  |                                                          || |
|  |  +----------------------------------------------------------+| |
|  +--------------------------------------------------------------+ |
|                                                                    |
|  +--------------------------------------------------------------+ |
|  | H2: 已导入模型                                  共 N 个      | |
|  +--------------------------------------------------------------+ |
|  | 模型名称     | 类型    | 大小   | 导入时间   | 操作          | |
|  |--------------|---------|--------|------------|---------------| |
|  | Neuro1       | GPT+So  | 278MB  | 2026-03-20 | [详情][删除]  | |
|  | firefly      | GPT+So  | 265MB  | 2026-03-19 | [详情][删除]  | |
|  +--------------------------------------------------------------+ |
|                                                                    |
|  [空状态：当没有模型时显示]                                       |
|  +--------------------------------------------------------------+ |
|  |                                                              | |
|  |     [空状态插画]                                             | |
|  |     还没有导入任何模型                                       | |
|  |     点击上方区域上传你的第一个模型                           | |
|  |                                                              | |
|  +--------------------------------------------------------------+ |
+------------------------------------------------------------------+
```

### 3.2 区块详细说明

#### 3.2.1 页面头部

- H1 标题 "模型管理"，右侧放置刷新按钮（调用 `POST /v1/voices/reload`）
- 刷新按钮带旋转动画反馈：点击后图标旋转 360 度，持续至接口返回

#### 3.2.2 拖拽上传区 (DragUploadZone)

- 高度：160px
- 边框：2px dashed `border` 色（`#475569`）
- 背景：`muted` 色 + 透明度 30%（`bg-muted/30`）
- 拖拽悬停态：边框色变为 `accent`（`#22C55E`），背景变为 `accent/10`，添加 `shadow-glow-accent`
- 上传中态：显示进度条（`el-progress`），禁用重复拖拽
- 上传成功：短暂显示成功提示（绿色对勾 + "上传成功"），2 秒后恢复默认态
- 上传失败：显示错误提示（红色文字），保持在上传区内部

文件类型限制：
- 权重文件：`gpt_file=.ckpt`、`sovits_file=.pth`
- 参考音频：`ref_audio_file=.wav/.mp3/.flac`

上传接口以后端实现为准，使用 `POST /v1/voices/upload`，`Content-Type: multipart/form-data`。除文件外还必须一并提交：
- `name`：voice 唯一标识
- `description`：可选描述
- `ref_text`：参考音频对应文本
- `ref_lang`：参考语种
- `speed / top_k / top_p / temperature / pause_length`：可选默认参数

这意味着上传区在视觉上仍可保持“拖拽上传”，但交互上不能只有一个文件选择器；在真正提交前，必须补完参考音频和参考文本元数据，才能创建一个可立即用于推理的 voice。

#### 3.2.3 模型列表表格

使用 `el-table`，暗色主题，列定义：

| 列 | 宽度 | 对齐 | 说明 |
|----|------|------|------|
| 模型名称 | auto (flex-grow) | 左 | 显示 `voice.name`，附带描述文字 |
| 语言 | 80px | 居中 | 显示 `ref_lang`，用 Tag 样式区分 |
| 参考文本 | 200px | 左 | `ref_text` 单行截断，hover 显示 tooltip |
| 操作 | 160px | 居中 | [详情] [删除] 按钮，分别调用 `GET /v1/voices/{name}` 与 `DELETE /v1/voices/{name}` |

行 hover 背景：`secondary` 色。

删除操作：点击后弹出 `el-popconfirm`，确认文字为 "确定删除模型 {name}？此操作不可恢复。"

详情操作：可打开 Drawer / Dialog，直接展示后端返回的 `VoiceProfile`，包括 `gpt_path`、`sovits_path`、`ref_audio`、`managed`、`created_at`、`updated_at`。

#### 3.2.4 空状态设计

当 `voices` 列表为空时：
- 隐藏表格
- 显示居中的空状态卡片：
  - 图标：一个灰色的麦克风 + 加号组合图标（64x64px）
  - 主文字："还没有导入任何模型"（`text-lg text-muted-fg`）
  - 辅助文字："点击上方上传完整模型，或通过 config/voices.json 手动维护后点击刷新按钮"（`text-sm text-muted-fg/70`）

### 3.3 Vue SFC 伪代码

```vue
<!-- src/views/VoiceAdminView.vue -->
<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Refresh } from '@element-plus/icons-vue'
import type { VoiceProfile } from '@/types/tts'
import { deleteVoice, fetchVoices, reloadVoices, uploadVoice } from '@/api/tts'

const voices = ref<VoiceProfile[]>([])
const loading = ref(false)
const reloading = ref(false)

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

async function handleUpload(payload: {
  name: string
  description?: string
  ref_text: string
  ref_lang: string
  gpt_file: File
  sovits_file: File
  ref_audio_file: File
}) {
  try {
    await uploadVoice(payload)
    ElMessage.success(`上传成功: ${payload.name}`)
    await loadVoices()
  } catch (err: unknown) {
    ElMessage.error(`上传失败: ${(err as Error).message}`)
  }
}

async function handleDelete(voice: VoiceProfile) {
  try {
    await ElMessageBox.confirm(
      `确定删除模型 "${voice.name}"？此操作不可恢复。`,
      '确认删除',
      { confirmButtonText: '删除', cancelButtonText: '取消', type: 'warning' }
    )
    await deleteVoice(voice.name)
    ElMessage.success(`已删除模型: ${voice.name}`)
    await loadVoices()
  } catch {
    // 用户取消，无操作
  }
}

onMounted(loadVoices)
</script>

<template>
  <div class="max-w-[1440px] mx-auto px-8 py-8">
    <!-- 页面标题 -->
    <div class="flex items-center justify-between mb-6">
      <h1 class="text-2xl font-bold text-foreground">模型管理</h1>
      <el-button
        :icon="Refresh"
        :loading="reloading"
        @click="handleReload"
        class="!bg-secondary !border-border !text-foreground hover:!bg-border"
      >
        刷新配置
      </el-button>
    </div>

    <!-- 拖拽上传区 -->
    <div class="
      mb-8 rounded-card border-2 border-dashed border-border
      bg-muted/30 flex flex-col items-center justify-center
      h-40 transition-all duration-200
      hover:border-accent hover:bg-accent/10
    ">
      <el-icon :size="32" class="text-muted-fg mb-3">
        <!-- UploadFilled 图标 -->
      </el-icon>
      <p class="text-sm text-muted-fg">拖拽 GPT/SoVITS 权重到此处，随后补完参考音频与文本信息</p>
      <p class="text-xs text-muted-fg/60 mt-1">权重支持：.ckpt / .pth，参考音频支持：.wav / .mp3 / .flac</p>
    </div>

    <!-- 模型列表 -->
    <div class="mb-4 flex items-center justify-between">
      <h2 class="text-lg font-semibold text-foreground">已导入模型</h2>
      <span class="text-sm text-muted-fg">共 {{ voices.length }} 个</span>
    </div>

    <!-- 表格 -->
    <el-table
      v-if="voices.length > 0"
      :data="voices"
      v-loading="loading"
      class="w-full"
      row-class-name="hover:bg-secondary/50"
    >
      <el-table-column prop="name" label="模型名称" min-width="160">
        <template #default="{ row }">
          <div>
            <span class="text-foreground font-medium">{{ row.name }}</span>
            <p class="text-xs text-muted-fg mt-0.5">{{ row.description }}</p>
          </div>
        </template>
      </el-table-column>
      <el-table-column prop="ref_lang" label="语言" width="80" align="center">
        <template #default="{ row }">
          <el-tag :type="row.ref_lang === 'zh' ? '' : 'success'" size="small">
            {{ row.ref_lang === 'zh' ? '中文' : 'EN' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="ref_text" label="参考文本" width="240" show-overflow-tooltip />
      <el-table-column label="操作" width="160" align="center">
        <template #default="{ row }">
          <el-button size="small" text type="primary">详情</el-button>
          <el-button size="small" text type="danger" @click="handleDelete(row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <!-- 空状态 -->
    <div
      v-else-if="!loading"
      class="flex flex-col items-center justify-center py-20 rounded-card bg-card"
    >
      <div class="w-16 h-16 rounded-full bg-muted flex items-center justify-center mb-4">
        <el-icon :size="28" class="text-muted-fg"><!-- Microphone --></el-icon>
      </div>
      <p class="text-lg text-muted-fg mb-2">还没有导入任何模型</p>
      <p class="text-sm text-muted-fg/70">
        在 <code class="bg-muted px-1.5 py-0.5 rounded text-xs">config/voices.json</code>
        中配置模型路径，然后点击刷新按钮
      </p>
    </div>
  </div>
</template>
```

---

## 4. 页面 2：语音合成 (TtsStudioView)

### 4.1 整体布局

Desktop 视图下的左右分栏（35:65）：

```
+==================================================================+
|  NavBar (固定)                                                    |
+==================================================================+
|                                                                    |
|  +------- 左侧面板 (35%) -------+  +---- 右侧面板 (65%) -------+ |
|  |                               |  |                            | |
|  | [模型选择区]                  |  | [文本输入区]               | |
|  | +---------------------------+ |  | +------------------------+ | |
|  | | Voice: [下拉选择]         | |  | |                        | | |
|  | | 描述: Neuro1 (V2 Pro)     | |  | |  在此输入要合成的文本   | | |
|  | +---------------------------+ |  | |                        | | |
|  |                               |  | |                        | | |
|  | [参考音频配置区]              |  | |  (textarea 8-12行)     | | |
|  | +---------------------------+ |  | |                        | | |
|  | | 预设: [neuro1_ref]        | |  | +------------------------+ | |
|  | | 或 [上传自定义参考音频]   | |  |                            | |
|  | | 参考文本:                  | |  | 字数统计    [开始推理] ●   | |
|  | | [textarea 2行]            | |  |                            | |
|  | +---------------------------+ |  | [音频结果区]               | |
|  |                               |  | +------------------------+ | |
|  | [推理参数] ▼ 展开/折叠       |  | | ★ 最新结果（高亮）      | | |
|  | +---------------------------+ |  | | "Then tomorrow we..."   | | |
|  | | 语速    [----●----] 1.0   | |  | | [▶ ━━━━━━━━ 00:03] [↓] | | |
|  | | 温度    [----●----] 1.0   | |  | +------------------------+ | |
|  | | Top P   [----●----] 1.0   | |  | +------------------------+ | |
|  | | Top K   [----●----] 15    | |  | | 历史 #2                 | | |
|  | | 停顿    [----●----] 0.3   | |  | | "Hello world..."        | | |
|  | | 文本语言 [auto ▼]         | |  | | [▶ ━━━━━━━━ 00:02] [↓] | | |
|  | +---------------------------+ |  | +------------------------+ | |
|  |                               |  | ...最多5条                 | |
|  +-------------------------------+  +----------------------------+ |
|                                                                    |
+==================================================================+
```

Mobile 视图下（< 768px）堆叠为单列：

```
+====================================+
|  NavBar                            |
+====================================+
|                                    |
|  [模型选择] (全宽下拉)            |
|                                    |
|  [文本输入区] (全宽 textarea)      |
|                                    |
|  [开始推理按钮] (全宽)            |
|                                    |
|  [音频结果区]                      |
|  +------------------------------+  |
|  | 最新结果（卡片）             |  |
|  | [▶ ━━━━━━━━ 00:03] [↓]      |  |
|  +------------------------------+  |
|                                    |
|  [参数配置] (折叠面板, 默认收起)  |
|  [参考音频配置] (折叠面板)        |
+====================================+
```

### 4.2 左侧面板详细设计

#### 4.2.1 模型选择区

```
+---------------------------------------------+
| 模型 (Voice)                                 |
| +------------------------------------------+|
| | [下拉选择器]              ▼              ||
| | neuro1 - Neuro1 (V2 Pro, English)        ||
| +------------------------------------------+|
| 当前模型：Neuro1 (V2 Pro, English)          |
+---------------------------------------------+
```

- 使用 `el-select` 组件
- Option 格式：`{voice.name} - {voice.description}`
- 选中后在下方显示模型描述文字（`text-xs text-muted-fg`）
- 下拉选项支持搜索过滤（`filterable`）
- 切换模型时自动填充该模型的默认参数和参考配置

#### 4.2.2 参考音频配置区

```
+---------------------------------------------+
| 参考音频                                     |
+---------------------------------------------+
| 来源:  (●) 模型预设  ( ) 自定义上传         |
+---------------------------------------------+
| [预设选择时]                                 |
| 预设参考音频: neuro1_ref.wav                 |
| [小型波形预览条 ▶]                           |
|                                               |
| [自定义上传时]                                |
| [上传音频文件] 或拖拽到此处                  |
| 支持: .wav, .mp3, .flac (< 30s)             |
+---------------------------------------------+
| 参考文本                                     |
| +------------------------------------------+|
| | Then tomorrow we can celebrate her       ||
| | birthday, and maybe even get her a...    ||
| +------------------------------------------+|
| 语言: [en ▼]                                |
+---------------------------------------------+
```

- 来源切换：`el-radio-group`，两个选项
  - "模型预设"：使用 `voice.ref_audio` 和 `voice.ref_text`，此时参考文本框为只读
  - "自定义上传"：启用上传组件和文本编辑
- 预设模式下显示当前参考音频文件名和一个迷你播放按钮
- 自定义模式下使用 `el-upload`（accept: `.wav,.mp3,.flac`，单文件，大小限制 30s/10MB）
- 当存在 `customRefFile` 时，`POST /v1/audio/speech` 必须切换为 `multipart/form-data`，并携带字段 `ref_audio_file`
- 参考文本：`el-input` textarea，2 行高度
- 语言选择：`el-select`，选项为 `auto / zh / en / ja / ko`

#### 4.2.3 推理参数区 (可折叠)

使用 `el-collapse` 或自定义折叠面板，默认状态：
- Desktop：展开
- Mobile/Tablet：折叠

折叠标题："推理参数" + 右侧折叠/展开图标

参数列表：

| 参数 | 字段 | 控件 | 范围 | 步长 | 默认值 | 说明 |
|------|------|------|------|------|--------|------|
| 语速 | `speed` | Slider + InputNumber | 0.5 - 2.0 | 0.05 | 1.0 | 语音播放速度 |
| 温度 | `temperature` | Slider + InputNumber | 0.1 - 2.0 | 0.05 | 1.0 | 控制随机性 |
| Top P | `top_p` | Slider + InputNumber | 0.0 - 1.0 | 0.05 | 1.0 | 核采样概率阈值 |
| Top K | `top_k` | Slider + InputNumber | 1 - 50 | 1 | 15 | 候选 token 数量 |
| 停顿时长 | `pause_length` | Slider + InputNumber | 0.0 - 1.0 | 0.05 | 0.3 | 分段间停顿（秒） |
| 文本语言 | `text_lang` | Select | auto/zh/en/ja/ko | - | auto | 目标文本语言 |
| 分段长度 | `chunk_length` | Slider + InputNumber | 10 - 100 | 1 | 24 | 文本分段字符数 |

每个 Slider 参数的布局：

```
+---------------------------------------------+
| 语速 (Speed)                           1.00 |
| [━━━━━━━━━●━━━━━━━━━━━━] [  1.00  ▲▼] |
| 0.5                                    2.0  |
+---------------------------------------------+
```

- 标签在左上，当前值在右上
- Slider 占主要宽度（约 70%），InputNumber 在右侧（约 25%）
- Slider 下方用极小文字标注最小/最大值
- 拖动 Slider 和修改 InputNumber 双向同步

"恢复默认" 按钮：放在参数区底部，点击后将所有参数恢复为当前选中 voice 的 `defaults` 值。

#### 4.2.4 左侧面板滚动行为

- 左侧面板内容可能超出视口高度（尤其参数展开时）
- 使用 `overflow-y: auto` 独立滚动
- 滚动条样式：细滚动条（`scrollbar-thin scrollbar-thumb-border scrollbar-track-transparent`）

### 4.3 右侧面板详细设计

#### 4.3.1 文本输入区

```
+----------------------------------------------------------+
| 合成文本                                                  |
| +------------------------------------------------------+ |
| |                                                      | |
| |  Then tomorrow we can celebrate her birthday, and    | |
| |  maybe even get her a lava lamp. I think she would   | |
| |  really like that.                                   | |
| |                                                      | |
| |                                                      | |
| |                                                      | |
| |                                                      | |
| +------------------------------------------------------+ |
| 已输入 128 字符                              [开始推理]   |
+----------------------------------------------------------+
```

- `el-input` textarea，`rows="10"`，可拖拽调整高度（`resize: vertical`）
- 占位符文字："在此输入要合成的语音文本..."（`text-muted-fg/60`）
- 底部工具栏（flex, justify-between）：
  - 左侧：字符计数 `text-xs text-muted-fg`
  - 右侧：**开始推理** CTA 按钮
- 文本为空时，推理按钮 disabled

推理按钮规格：
- 尺寸：`min-w-[140px] min-h-[44px]`
- 颜色：`bg-cta text-foreground`
- 图标：左侧放一个播放三角图标（推理中替换为 spinner）
- Loading 态文字："推理中..."
- 推理中：按钮 disabled，文本区域 readonly

#### 4.3.2 音频结果区

**三种状态**：

**状态 A：空状态（未做过推理）**

```
+----------------------------------------------------------+
|                                                            |
|     [波形图标，灰色]                                      |
|     输入文本并点击"开始推理"                              |
|     生成的音频将显示在此处                                |
|                                                            |
+----------------------------------------------------------+
```

- 居中显示
- 文字颜色 `text-muted-fg/50`
- 图标尺寸 48x48px

**状态 B：推理中**

```
+----------------------------------------------------------+
| [推理进行中...]                                           |
| +------------------------------------------------------+ |
| | ★ 正在生成...                                        | |
| |                                                      | |
| | [动态波形动画 ~~~∿∿∿~~~]                             | |
| |                                                      | |
| | "Then tomorrow we can celebrate her birthday..."     | |
| +------------------------------------------------------+ |
|                                                            |
| [之前的历史条目...]                                       |
+----------------------------------------------------------+
```

- 最新卡片位置显示加载占位
- 波形动画：3-5 条竖线做高度脉动动画（纯 CSS，参考 audio-bars 效果）
- 显示当前推理的文本截断
- 历史条目保持不变

**状态 C：有结果**

```
+----------------------------------------------------------+
| 合成结果                                                  |
| +------------------------------------------------------+ |
| | ★ 最新                                    2s ago     | |
| | "Then tomorrow we can celebrate her birthday, a..."  | |
| |                                                      | |
| | [▶]  [━━━━━●━━━━━━━━━━━━]  01:23 / 03:45           | |
| |                                                      | |
| | [波形可视化区域 ∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿∿]              | |
| |                                                      | |
| |                              [下载 WAV]              | |
| +------------------------------------------------------+ |
|                                                            |
| +------------------------------------------------------+ |
| | #2                                          5min ago  | |
| | "Hello world, this is a test..."                     | |
| | [▶] [━━━━━━━━━━━━━━━━━━━━] 00:00 / 00:02  [↓]      | |
| +------------------------------------------------------+ |
|                                                            |
| +------------------------------------------------------+ |
| | #3                                          12min ago | |
| | "Another test sentence for..."                       | |
| | [▶] [━━━━━━━━━━━━━━━━━━━━] 00:00 / 00:05  [↓]      | |
| +------------------------------------------------------+ |
+----------------------------------------------------------+
```

### 4.4 音频队列 UI 状态机

```
                    +---------+
                    |  Empty  |  (初始状态，无历史)
                    +---------+
                         |
                    用户点击"开始推理"
                         |
                         v
                   +------------+
                   | Inferring  |  (队列头部显示 loading 占位卡片)
                   +------------+
                      /       \
              API 成功        API 失败
                /                 \
               v                   v
        +-------------+     +----------+
        | HasResults  |     |  Error   |
        +-------------+     +----------+
             |                    |
        用户再次推理          用户再次推理
             |                    |
             v                    v
        +------------+      +------------+
        | Inferring  |      | Inferring  |
        +------------+      +------------+
```

状态定义（TypeScript）：

```typescript
type AudioQueueState = 'empty' | 'inferring' | 'has-results' | 'error'

interface AudioHistoryItem {
  id: string                  // 唯一标识（nanoid 或 timestamp）
  text: string                // 原始合成文本
  blobUrl: string | null      // Blob URL（推理中为 null）
  duration: number | null     // 音频时长（秒）
  createdAt: Date             // 创建时间
  status: 'pending' | 'done' | 'error'
  errorMessage?: string       // 错误信息
}
```

队列管理规则：
1. 新结果 `unshift` 到数组头部
2. 数组最大长度 5，超出时 `pop` 尾部元素
3. 被移除元素的 `blobUrl` 必须调用 `URL.revokeObjectURL()` 释放
4. 页面卸载（`onBeforeUnmount`）时释放所有 Blob URL

### 4.5 波形可视化

最新结果卡片中包含简化波形可视化：

- 实现方式：`<canvas>` 或 SVG，使用 Web Audio API 的 `AnalyserNode` 在播放时实时渲染
- 静态态：从音频 buffer 提取波形数据，绘制为灰色条状图（bar chart 风格，每 bar 宽 2px，间距 1px）
- 播放态：已播放部分高亮为 `accent` 色，未播放部分保持 `muted-fg` 色
- 高度：48px
- 仅最新结果显示波形，历史条目使用简化的进度条

如果波形渲染复杂度过高，可降级为纯 CSS 进度条方案（`<input type="range">` 样式化），在首版实现中这是可接受的。

### 4.6 Vue SFC 伪代码

```vue
<!-- src/views/TtsStudioView.vue -->
<script setup lang="ts">
import { ref, computed, onBeforeUnmount, watch } from 'vue'
import { ElMessage } from 'element-plus'
import type { VoiceProfile, AudioHistoryItem } from '@/types/tts'
import { fetchVoices, synthesizeSpeech } from '@/api/tts'
import VoiceSelect from '@/components/VoiceSelect.vue'
import InferenceSettingsPanel from '@/components/InferenceSettingsPanel.vue'
import AudioResultPanel from '@/components/AudioResultPanel.vue'
import TtsForm from '@/components/TtsForm.vue'

// ---- 模型列表 ----
const voices = ref<VoiceProfile[]>([])
const selectedVoiceName = ref<string>('')
const selectedVoice = computed(() =>
  voices.value.find(v => v.name === selectedVoiceName.value) ?? null
)

// ---- 参考音频配置 ----
const refSource = ref<'preset' | 'custom'>('preset')
const customRefFile = ref<File | null>(null)
const refText = ref('')
const refLang = ref('auto')

// ---- 推理参数 ----
const params = ref({
  speed: 1.0,
  temperature: 1.0,
  top_p: 1.0,
  top_k: 15,
  pause_length: 0.3,
  text_lang: 'auto' as string,
  chunk_length: 24,
})

// ---- 文本输入 ----
const inputText = ref('')
const isInferring = ref(false)

// ---- 音频队列 ----
const audioHistory = ref<AudioHistoryItem[]>([])
const MAX_QUEUE_SIZE = 5

// 切换 voice 时同步默认参数和参考配置
watch(selectedVoice, (voice) => {
  if (!voice) return
  params.value.speed = voice.defaults.speed
  params.value.temperature = voice.defaults.temperature
  params.value.top_p = voice.defaults.top_p
  params.value.top_k = voice.defaults.top_k
  params.value.pause_length = voice.defaults.pause_length
  refText.value = voice.ref_text
  refLang.value = voice.ref_lang
})

// 开始推理
async function handleInference() {
  if (!inputText.value.trim() || !selectedVoiceName.value) return
  if (isInferring.value) return

  isInferring.value = true

  // 推入 pending 占位
  const pendingItem: AudioHistoryItem = {
    id: `${Date.now()}`,
    text: inputText.value,
    blobUrl: null,
    duration: null,
    createdAt: new Date(),
    status: 'pending',
  }
  audioHistory.value.unshift(pendingItem)

  // 超出队列上限时释放尾部
  while (audioHistory.value.length > MAX_QUEUE_SIZE) {
    const removed = audioHistory.value.pop()
    if (removed?.blobUrl) URL.revokeObjectURL(removed.blobUrl)
  }

  try {
    const blob = await synthesizeSpeech({
      input: inputText.value,
      voice: selectedVoiceName.value,
      speed: params.value.speed,
      temperature: params.value.temperature,
      top_p: params.value.top_p,
      top_k: params.value.top_k,
      pause_length: params.value.pause_length,
      text_lang: params.value.text_lang,
      chunk_length: params.value.chunk_length,
      // 自定义参考音频（如有）
      ...(refSource.value === 'custom' && customRefFile.value
        ? {
            ref_audio_file: customRefFile.value,
            ref_text: refText.value,
            ref_lang: refLang.value,
          }
        : {}),
    })

    const blobUrl = URL.createObjectURL(blob)

    // 获取音频时长
    const audio = new Audio(blobUrl)
    await new Promise<void>((resolve) => {
      audio.addEventListener('loadedmetadata', () => resolve(), { once: true })
      audio.addEventListener('error', () => resolve(), { once: true })
    })

    // 更新 pending 条目为完成态
    pendingItem.blobUrl = blobUrl
    pendingItem.duration = audio.duration || null
    pendingItem.status = 'done'
  } catch (err: unknown) {
    pendingItem.status = 'error'
    pendingItem.errorMessage = (err as Error).message
    ElMessage.error(`推理失败: ${(err as Error).message}`)
  } finally {
    isInferring.value = false
  }
}

// 恢复默认参数
function resetParams() {
  const voice = selectedVoice.value
  if (!voice) return
  params.value = {
    speed: voice.defaults.speed,
    temperature: voice.defaults.temperature,
    top_p: voice.defaults.top_p,
    top_k: voice.defaults.top_k,
    pause_length: voice.defaults.pause_length,
    text_lang: 'auto',
    chunk_length: 24,
  }
}

// 下载音频
function handleDownload(item: AudioHistoryItem) {
  if (!item.blobUrl) return
  const a = document.createElement('a')
  a.href = item.blobUrl
  a.download = `tts_${item.id}.wav`
  a.click()
}

// 组件卸载时释放所有 Blob URL
onBeforeUnmount(() => {
  audioHistory.value.forEach((item) => {
    if (item.blobUrl) URL.revokeObjectURL(item.blobUrl)
  })
})

// 初始化加载 voices
async function init() {
  try {
    voices.value = await fetchVoices()
    if (voices.value.length > 0) {
      selectedVoiceName.value = voices.value[0].name
    }
  } catch (err: unknown) {
    ElMessage.error(`加载模型列表失败: ${(err as Error).message}`)
  }
}
init()
</script>

<template>
  <div class="max-w-[1440px] mx-auto px-4 lg:px-8 py-6">
    <!-- Desktop: 左右分栏 / Mobile: 单列 -->
    <div class="flex flex-col md:flex-row gap-6">

      <!-- 左侧面板：配置区 -->
      <aside class="
        w-full md:w-[35%] lg:w-[30%]
        md:max-h-[calc(100vh-120px)] md:overflow-y-auto
        md:sticky md:top-20
        space-y-5
        scrollbar-thin scrollbar-thumb-border scrollbar-track-transparent
      ">
        <!-- 模型选择 -->
        <section class="bg-card rounded-card p-4 shadow-card">
          <h3 class="text-[13px] font-semibold text-foreground mb-3">模型 (Voice)</h3>
          <VoiceSelect
            v-model="selectedVoiceName"
            :voices="voices"
          />
          <p v-if="selectedVoice" class="text-xs text-muted-fg mt-2">
            {{ selectedVoice.description }}
          </p>
        </section>

        <!-- 参考音频配置 -->
        <section class="bg-card rounded-card p-4 shadow-card">
          <h3 class="text-[13px] font-semibold text-foreground mb-3">参考音频</h3>

          <el-radio-group v-model="refSource" class="mb-3">
            <el-radio value="preset">模型预设</el-radio>
            <el-radio value="custom">自定义上传</el-radio>
          </el-radio-group>

          <!-- 预设模式 -->
          <div v-if="refSource === 'preset' && selectedVoice" class="space-y-2">
            <p class="text-xs text-muted-fg">
              {{ selectedVoice.ref_audio.split('/').pop() }}
            </p>
          </div>

          <!-- 自定义模式 -->
          <div v-if="refSource === 'custom'" class="space-y-2">
            <el-upload
              :auto-upload="false"
              accept=".wav,.mp3,.flac"
              :limit="1"
              drag
              class="w-full"
            >
              <p class="text-sm text-muted-fg">拖拽或点击上传参考音频</p>
            </el-upload>
          </div>

          <!-- 参考文本 -->
          <div class="mt-3">
            <label class="text-[13px] font-semibold text-foreground block mb-1.5">
              参考文本
            </label>
            <el-input
              v-model="refText"
              type="textarea"
              :rows="2"
              :readonly="refSource === 'preset'"
              placeholder="参考音频对应的文本内容"
            />
          </div>

          <!-- 参考语言 -->
          <div class="mt-3 flex items-center gap-2">
            <label class="text-[13px] font-semibold text-foreground whitespace-nowrap">
              语言
            </label>
            <el-select v-model="refLang" size="small" class="w-24">
              <el-option value="auto" label="自动" />
              <el-option value="zh" label="中文" />
              <el-option value="en" label="English" />
              <el-option value="ja" label="日本語" />
              <el-option value="ko" label="한국어" />
            </el-select>
          </div>
        </section>

        <!-- 推理参数 (可折叠) -->
        <section class="bg-card rounded-card shadow-card overflow-hidden">
          <InferenceSettingsPanel
            v-model:params="params"
            @reset="resetParams"
          />
        </section>
      </aside>

      <!-- 右侧面板：输入与输出 -->
      <main class="w-full md:w-[65%] lg:w-[70%] space-y-5">
        <!-- 文本输入 -->
        <TtsForm
          v-model:text="inputText"
          :is-inferring="isInferring"
          :disabled="!selectedVoiceName"
          @submit="handleInference"
        />

        <!-- 音频结果 -->
        <AudioResultPanel
          :history="audioHistory"
          :is-inferring="isInferring"
          @download="handleDownload"
        />
      </main>
    </div>
  </div>
</template>
```

---

## 5. 共享组件清单

### 5.1 AudioPlayer

内联音频播放器，用于音频队列中每条结果的播放控制。

```typescript
// Props
interface AudioPlayerProps {
  src: string | null         // Blob URL 或音频文件 URL
  duration?: number | null   // 总时长（秒），可由组件内部计算
  compact?: boolean          // 紧凑模式（历史条目用）
}

// Emits
interface AudioPlayerEmits {
  (e: 'play'): void
  (e: 'pause'): void
  (e: 'ended'): void
  (e: 'timeupdate', currentTime: number): void
}
```

**视觉规格**：
- 高度：紧凑模式 36px，标准模式 48px
- 播放/暂停按钮：圆形，40x40px（紧凑 32x32px），`bg-accent text-background`
- 进度条：`el-slider`，track 颜色 `muted`，已播放部分 `accent`
- 时间显示：`text-xs text-muted-fg`，格式 `mm:ss / mm:ss`

**关键样式**：

```html
<div class="flex items-center gap-3 px-3 py-2 bg-muted/30 rounded-btn">
  <!-- 播放按钮 -->
  <button class="
    w-10 h-10 rounded-full bg-accent text-background
    flex items-center justify-center
    transition-all duration-150
    hover:shadow-glow-accent hover:brightness-110
    active:scale-95
    disabled:opacity-50
  ">
    <!-- Play / Pause 图标 -->
  </button>

  <!-- 进度条 -->
  <div class="flex-1">
    <el-slider
      v-model="currentTime"
      :max="duration"
      :show-tooltip="false"
      class="!my-0"
    />
  </div>

  <!-- 时间 -->
  <span class="text-xs text-muted-fg whitespace-nowrap min-w-[80px] text-right">
    {{ formatTime(currentTime) }} / {{ formatTime(duration) }}
  </span>
</div>
```

**内部状态**：
- `isPlaying: boolean`
- `currentTime: number`
- `internalDuration: number`（从 `<audio>` 元素的 `loadedmetadata` 事件获取）

**注意事项**：
- 内部创建隐藏的 `<audio>` 元素（不渲染原生控件）
- `src` 变化时重新加载
- 组件卸载时暂停播放
- 同一页面多个播放器：播放新的时暂停其他（通过 `provide/inject` 或事件总线协调）

### 5.2 FileUploader

通用文件上传组件，包装 `el-upload` 并添加拖拽高亮、格式限制、大小限制。

```typescript
// Props
interface FileUploaderProps {
  accept: string             // 接受的文件格式，如 ".wav,.mp3,.flac"
  maxSize?: number           // 最大文件大小（字节），默认 10MB
  disabled?: boolean
  placeholder?: string       // 拖拽区提示文字
  hint?: string              // 辅助说明文字
}

// Emits
interface FileUploaderEmits {
  (e: 'change', file: File | null): void
  (e: 'error', message: string): void
}
```

**视觉规格**：
- 拖拽区高度：120px（参考音频上传）/ 160px（模型上传）
- 边框：2px dashed `border`，hover/dragover 变 `accent`
- 背景：`bg-muted/30`，dragover 变 `bg-accent/10`
- 已选文件时显示文件名 + 大小 + 删除按钮，隐藏拖拽区

### 5.3 ParameterSlider

Slider + InputNumber 的组合控件，用于推理参数调节。

```typescript
// Props
interface ParameterSliderProps {
  modelValue: number
  label: string              // 参数名称
  min: number
  max: number
  step: number
  unit?: string              // 单位标签（如 "s", "x"）
  tooltip?: string           // 参数说明
}

// Emits
interface ParameterSliderEmits {
  (e: 'update:modelValue', value: number): void
}
```

**视觉规格**：

```html
<div class="space-y-1">
  <!-- 标签行 -->
  <div class="flex items-center justify-between">
    <label class="text-[13px] font-semibold text-foreground flex items-center gap-1">
      {{ label }}
      <el-tooltip v-if="tooltip" :content="tooltip" placement="top">
        <el-icon :size="14" class="text-muted-fg cursor-help">
          <!-- QuestionFilled -->
        </el-icon>
      </el-tooltip>
    </label>
    <span class="text-xs text-muted-fg tabular-nums">
      {{ modelValue.toFixed(stepDecimals) }}{{ unit }}
    </span>
  </div>

  <!-- Slider + InputNumber 行 -->
  <div class="flex items-center gap-3">
    <el-slider
      :model-value="modelValue"
      :min="min"
      :max="max"
      :step="step"
      :show-tooltip="false"
      class="flex-1"
      @update:model-value="$emit('update:modelValue', $event)"
    />
    <el-input-number
      :model-value="modelValue"
      :min="min"
      :max="max"
      :step="step"
      :controls="false"
      size="small"
      class="!w-20"
      @update:model-value="$emit('update:modelValue', $event ?? min)"
    />
  </div>
</div>
```

### 5.4 StatusIndicator

后端连接状态指示器，显示在导航栏右侧。

```typescript
// Props
interface StatusIndicatorProps {
  status: 'online' | 'offline' | 'reconnecting'
  label?: string             // 自定义标签文字
}
```

**视觉规格**：

| 状态 | 圆点颜色 | 文字 | 动画 |
|------|---------|------|------|
| online | `bg-accent` (#22C55E) | "Backend Online" | 无（静态圆点） |
| offline | `bg-destructive` (#EF4444) | "Backend Offline" | 无 |
| reconnecting | `bg-warning` (#F59E0B) | "重连中..." | 圆点呼吸动画 (`animate-pulse`) |

```html
<div class="flex items-center gap-2">
  <span :class="[
    'w-2 h-2 rounded-full',
    status === 'online' ? 'bg-accent' : '',
    status === 'offline' ? 'bg-destructive' : '',
    status === 'reconnecting' ? 'bg-warning animate-pulse' : '',
  ]" />
  <span class="text-xs text-muted-fg">{{ displayLabel }}</span>
</div>
```

**实现逻辑**：
- 每 15 秒轮询 `GET /health`
- 连续 2 次失败 → 切换为 `offline`
- 从 offline 恢复后显示 `reconnecting`，确认成功后回到 `online`
- 在 `App.vue` 级别使用 `setInterval`，通过 `provide` 向下传递状态

### 5.5 VoiceSelect

模型选择下拉框，包装 `el-select`。

```typescript
// Props
interface VoiceSelectProps {
  modelValue: string         // 选中的 voice name
  voices: VoiceProfile[]
}

// Emits
interface VoiceSelectEmits {
  (e: 'update:modelValue', value: string): void
}
```

视觉规格：全宽 `el-select`，`filterable`，Option 格式为 `{name} - {description}`。

### 5.6 TtsForm

文本输入 + 提交按钮组合。

```typescript
// Props
interface TtsFormProps {
  text: string
  isInferring: boolean
  disabled?: boolean
}

// Emits
interface TtsFormEmits {
  (e: 'update:text', value: string): void
  (e: 'submit'): void
}
```

### 5.7 AudioResultPanel

音频结果列表面板。

```typescript
// Props
interface AudioResultPanelProps {
  history: AudioHistoryItem[]
  isInferring: boolean
}

// Emits
interface AudioResultPanelEmits {
  (e: 'download', item: AudioHistoryItem): void
}
```

### 5.8 InferenceSettingsPanel

推理参数折叠面板。

```typescript
interface InferenceParams {
  speed: number
  temperature: number
  top_p: number
  top_k: number
  pause_length: number
  text_lang: string
  chunk_length: number
}

// Props
interface InferenceSettingsPanelProps {
  params: InferenceParams
}

// Emits
interface InferenceSettingsPanelEmits {
  (e: 'update:params', value: InferenceParams): void
  (e: 'reset'): void
}
```

---

## 6. 交互流程

### 6.1 完整用户旅程：首次使用

```
用户打开网页
  |
  v
[加载页面] --> 自动 GET /v1/voices 获取模型列表
  |
  v
[语音合成页面渲染]
  |-- 左侧：模型列表加载完毕，自动选中第一个 voice
  |-- 右侧：文本区为空，音频区显示空状态
  |-- 导航栏：后端状态灯变绿
  |
  v
用户在文本区输入要合成的文字
  |-- 底部实时显示字符计数
  |-- "开始推理"按钮从 disabled 变为 enabled
  |
  v
用户（可选）调整左侧参数
  |-- 拖动 slider 或修改 input-number
  |-- 参数实时双向同步
  |
  v
用户点击"开始推理"
  |
  v
[前端状态变化]
  |-- 按钮: "开始推理" --> "推理中..." + spinner + disabled
  |-- 文本区: readonly
  |-- 音频区: 队列头部插入 pending 占位卡片（显示波形动画）
  |
  v
POST /v1/audio/speech
  |-- 预设参考音频：`application/json`
  |-- 自定义参考音频：`multipart/form-data` + `ref_audio_file`
  |
  +--- 成功 (HTTP 200, audio/wav blob)
  |     |
  |     v
  |   URL.createObjectURL(blob) --> blobUrl
  |   更新 pending 卡片为 done 态
  |   自动获取音频时长 (loadedmetadata)
  |   按钮恢复, 文本区恢复可编辑
  |   最新卡片高亮展示 (accent 左边框 + 波形)
  |   用户可: [播放] [暂停] [拖动进度] [下载 WAV]
  |
  +--- 失败 (HTTP 4xx/5xx 或网络错误)
        |
        v
      更新 pending 卡片为 error 态
      显示错误信息
      ElMessage.error 弹出 toast 提示
      按钮恢复, 文本区恢复可编辑
```

### 6.2 模型切换流程

```
用户切换 Voice 下拉选择
  |
  v
watch(selectedVoice) 触发
  |-- 推理参数重置为新 voice 的 defaults
  |-- 参考文本更新为新 voice 的 ref_text
  |-- 参考语言更新为新 voice 的 ref_lang
  |-- 参考音频来源重置为"模型预设"
  |
  v
音频队列保持不变（历史结果不清除）
```

### 6.3 模型管理流程

```
用户导航到"模型管理"页面
  |
  v
自动 GET /v1/voices 加载列表
  |
  +--- 有模型: 渲染表格
  +--- 无模型: 渲染空状态
  |
  v
用户上传完整模型
  |
  v
POST /v1/voices/upload
  |-- multipart/form-data
  |-- 字段: name / gpt_file / sovits_file / ref_audio_file / ref_text / ref_lang / 可选 defaults
  |
  +--- 成功: toast 提示 "上传成功"
  |          重新加载列表
  +--- 失败: toast 提示错误信息
  |
  v
用户点击"刷新配置"
  |
  v
POST /v1/voices/reload
  |-- 按钮 loading 态 + 图标旋转
  |
  +--- 成功: toast 提示 "刷新成功，共 N 个模型"
  |          重新加载列表
  +--- 失败: toast 提示错误信息
  |
  v
用户删除模型
  |
  v
DELETE /v1/voices/{voice_name}
  |-- 成功: 从表格移除该条目
  +--- 失败: toast 提示错误信息
```

### 6.4 音频队列 FIFO 管理流程

```
每次推理完成（成功或失败）:
  1. unshift 新条目到 audioHistory 头部
  2. 检查 audioHistory.length > 5
  3. 若超出:
     a. pop 尾部元素
     b. 若该元素有 blobUrl，调用 URL.revokeObjectURL(blobUrl)
  4. 触发 Vue 响应式更新，UI 自动刷新

页面卸载时:
  1. 遍历 audioHistory
  2. 对每个有 blobUrl 的条目调用 URL.revokeObjectURL()
```

### 6.5 API 请求构造

```typescript
// src/api/tts.ts

import axios from './http'
import type { VoiceProfile } from '@/types/tts'

// 获取 voice 列表
export async function fetchVoices(): Promise<VoiceProfile[]> {
  const { data } = await axios.get<VoiceProfile[]>('/v1/voices')
  return data
}

export async function fetchVoiceDetail(name: string): Promise<VoiceProfile> {
  const { data } = await axios.get<VoiceProfile>(`/v1/voices/${name}`)
  return data
}

// 重新加载 voices 配置
export async function reloadVoices(): Promise<{ status: string; count: number }> {
  const { data } = await axios.post<{ status: string; count: number }>('/v1/voices/reload')
  return data
}

export async function uploadVoice(params: {
  name: string
  description?: string
  ref_text: string
  ref_lang?: string
  speed?: number
  top_k?: number
  top_p?: number
  temperature?: number
  pause_length?: number
  gpt_file: File
  sovits_file: File
  ref_audio_file: File
}): Promise<VoiceProfile> {
  const form = new FormData()
  form.append('name', params.name)
  form.append('description', params.description ?? '')
  form.append('ref_text', params.ref_text)
  form.append('ref_lang', params.ref_lang ?? 'zh')
  if (params.speed !== undefined) form.append('speed', String(params.speed))
  if (params.top_k !== undefined) form.append('top_k', String(params.top_k))
  if (params.top_p !== undefined) form.append('top_p', String(params.top_p))
  if (params.temperature !== undefined) form.append('temperature', String(params.temperature))
  if (params.pause_length !== undefined) form.append('pause_length', String(params.pause_length))
  form.append('gpt_file', params.gpt_file)
  form.append('sovits_file', params.sovits_file)
  form.append('ref_audio_file', params.ref_audio_file)

  const { data } = await axios.post<VoiceProfile>('/v1/voices/upload', form)
  return data
}

export async function deleteVoice(name: string): Promise<{ status: string; name: string }> {
  const { data } = await axios.delete<{ status: string; name: string }>(`/v1/voices/${name}`)
  return data
}

// 语音合成 - 返回音频 Blob
export async function synthesizeSpeech(params: {
  input: string
  voice: string
  speed?: number
  temperature?: number
  top_p?: number
  top_k?: number
  pause_length?: number
  text_lang?: string
  chunk_length?: number
  ref_audio?: string
  ref_audio_file?: File
  ref_text?: string
  ref_lang?: string
}): Promise<Blob> {
  if (params.ref_audio_file) {
    const form = new FormData()
    form.append('input', params.input)
    form.append('voice', params.voice)
    if (params.speed !== undefined) form.append('speed', String(params.speed))
    if (params.temperature !== undefined) form.append('temperature', String(params.temperature))
    if (params.top_p !== undefined) form.append('top_p', String(params.top_p))
    if (params.top_k !== undefined) form.append('top_k', String(params.top_k))
    if (params.pause_length !== undefined) form.append('pause_length', String(params.pause_length))
    if (params.text_lang !== undefined) form.append('text_lang', params.text_lang)
    if (params.chunk_length !== undefined) form.append('chunk_length', String(params.chunk_length))
    if (params.ref_text !== undefined) form.append('ref_text', params.ref_text)
    if (params.ref_lang !== undefined) form.append('ref_lang', params.ref_lang)
    form.append('ref_audio_file', params.ref_audio_file)

    const { data } = await axios.post('/v1/audio/speech', form, {
      responseType: 'blob',
      timeout: 120_000,
    })
    return data
  }

  const { ref_audio_file, ...jsonPayload } = params
  const { data } = await axios.post('/v1/audio/speech', jsonPayload, {
    responseType: 'blob',
    timeout: 120_000,  // TTS 推理可能耗时较长
  })
  return data
}
```

```typescript
// src/api/http.ts

import axios from 'axios'

const http = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || '',
  timeout: 30_000,
})

// 响应拦截器：统一错误处理
http.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response) {
      const detail = error.response.data?.detail
      throw new Error(detail || `HTTP ${error.response.status}`)
    }
    if (error.code === 'ECONNABORTED') {
      throw new Error('请求超时，请检查后端是否正常运行')
    }
    throw new Error('网络错误，请检查连接')
  }
)

export default http
```

---

## 7. TypeScript 类型定义

```typescript
// src/types/tts.ts

export interface VoiceDefaults {
  speed: number
  top_k: number
  top_p: number
  temperature: number
  pause_length: number
}

export interface VoiceProfile {
  name: string
  gpt_path: string
  sovits_path: string
  ref_audio: string
  ref_text: string
  ref_lang: string
  description: string
  defaults: VoiceDefaults
  managed: boolean
  created_at?: string | null
  updated_at?: string | null
}

export interface AudioHistoryItem {
  id: string
  text: string
  blobUrl: string | null
  duration: number | null
  createdAt: Date
  status: 'pending' | 'done' | 'error'
  errorMessage?: string
}

export interface InferenceParams {
  speed: number
  temperature: number
  top_p: number
  top_k: number
  pause_length: number
  text_lang: string
  chunk_length: number
}

export interface SpeechRequest {
  input: string
  voice: string
  model?: string
  response_format?: string
  speed?: number
  top_k?: number
  top_p?: number
  temperature?: number
  text_lang?: string
  chunk_length?: number
  history_window?: number
  pause_length?: number
  noise_scale?: number
  ref_audio?: string
  ref_audio_file?: File
  ref_text?: string
  ref_lang?: string
}
```

---

## 8. 无障碍访问 (A11y)

### 8.1 关键实践清单

| 实践 | 实施方式 |
|------|---------|
| 语义化 HTML | 所有可交互元素使用 `<button>`/`<a>`/`<input>`，不用 `<div onclick>` |
| 表单关联 | 所有 `<input>` 配套 `<label for="...">` 或 `aria-label` |
| 键盘导航 | Tab 顺序逻辑：模型选择 -> 参考配置 -> 参数 -> 文本输入 -> 推理按钮 -> 音频播放 |
| 焦点可见 | `focus:ring-2 focus:ring-cta focus:ring-offset-2 focus:ring-offset-background` |
| 屏幕阅读器 | 推理按钮使用 `aria-label="开始语音合成推理"`，loading 态补充 `aria-busy="true"` |
| 错误提示 | 使用 `role="alert" aria-live="polite"` |
| 颜色对比度 | 主文字 `#F8FAFC` on `#0F172A` = 17.4:1 (超过 WCAG AAA) |
| 触控目标 | 所有按钮 `min-h-[44px] min-w-[44px]` |

### 8.2 音频播放器 A11y

```html
<div role="group" aria-label="音频播放器">
  <button
    :aria-label="isPlaying ? '暂停' : '播放'"
    @click="togglePlay"
  >
    <!-- Play/Pause 图标 -->
  </button>

  <label for="audio-progress" class="sr-only">播放进度</label>
  <input
    id="audio-progress"
    type="range"
    :value="currentTime"
    :max="duration"
    :aria-valuetext="`${formatTime(currentTime)} / ${formatTime(duration)}`"
    @input="seek($event)"
  />

  <span aria-live="off" class="text-xs">
    {{ formatTime(currentTime) }} / {{ formatTime(duration) }}
  </span>
</div>
```

---

## 9. Vite 开发代理配置

```typescript
// vite.config.ts
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { resolve } from 'path'

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': resolve(__dirname, 'src'),
    },
  },
  server: {
    port: 5173,
    proxy: {
      '/v1': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
      '/health': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
})
```

---

## 10. 设计资产清单

### 10.1 图标需求

所有图标使用 `@element-plus/icons-vue` 或 Lucide Vue，保持单一来源。

| 图标 | 用途 | 来源 |
|------|------|------|
| Microphone | 品牌图标、空状态 | Element Plus Icons |
| VideoPlay / VideoPause | 音频播放/暂停 | Element Plus Icons |
| Download | 下载按钮 | Element Plus Icons |
| Delete | 删除模型 | Element Plus Icons |
| Refresh | 刷新配置 | Element Plus Icons |
| Upload | 上传区域 | Element Plus Icons |
| Setting | 参数区图标 | Element Plus Icons |
| ArrowDown / ArrowUp | 折叠/展开 | Element Plus Icons |
| WarningFilled | 错误状态 | Element Plus Icons |
| CircleCheckFilled | 成功状态 | Element Plus Icons |
| QuestionFilled | 参数提示 | Element Plus Icons |
| Loading | 加载中 spinner | Element Plus Icons |

### 10.2 CSS 动画

需要定义的自定义动画（在 `styles.css` 或 Tailwind `@layer` 中）：

```css
/* 波形加载动画（推理中状态） */
@keyframes audio-bars {
  0%, 100% { height: 20%; }
  50% { height: 80%; }
}

.audio-bar {
  animation: audio-bars 1.2s ease-in-out infinite;
}
.audio-bar:nth-child(1) { animation-delay: 0s; }
.audio-bar:nth-child(2) { animation-delay: 0.15s; }
.audio-bar:nth-child(3) { animation-delay: 0.3s; }
.audio-bar:nth-child(4) { animation-delay: 0.45s; }
.audio-bar:nth-child(5) { animation-delay: 0.6s; }

/* 刷新按钮旋转 */
@keyframes spin-once {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

.animate-spin-once {
  animation: spin-once 0.6s ease-in-out;
}
```

---

## 11. 开发交付检查清单

面向前端开发者的实施检查清单：

- [ ] 项目初始化：Vite + Vue 3 + TypeScript
- [ ] 安装依赖：Element Plus, Tailwind CSS, Vue Router, Pinia (可选), Axios
- [ ] Tailwind 配置：颜色 token, 字体, 圆角, 阴影
- [ ] Element Plus 暗色主题覆写
- [ ] 路由配置：`/studio`, `/voices`
- [ ] API 客户端封装：`http.ts`, `tts.ts`
- [ ] TypeScript 类型定义：`types/tts.ts`
- [ ] 全局布局：`App.vue` (NavBar + RouterView)
- [ ] StatusIndicator 组件 + 健康检查轮询
- [ ] VoiceAdminView 页面
  - [ ] 模型列表表格
  - [ ] 空状态
  - [ ] 刷新按钮
  - [ ] 上传区（disabled 占位）
- [ ] TtsStudioView 页面
  - [ ] 左右分栏布局 + 响应式
  - [ ] VoiceSelect 模型选择
  - [ ] 参考音频配置区（预设/自定义切换）
  - [ ] InferenceSettingsPanel 参数面板（折叠/展开）
  - [ ] ParameterSlider 组件
  - [ ] TtsForm 文本输入 + 提交
  - [ ] AudioResultPanel 音频结果区
  - [ ] AudioPlayer 播放器组件
  - [ ] 音频队列 FIFO 管理 + Blob URL 释放
- [ ] 音频结果区三种状态：empty / inferring / has-results
- [ ] 推理按钮 loading 态 + 防重复提交
- [ ] 错误处理：toast 提示 + 卡片内错误展示
- [ ] 响应式适配：Mobile (< 768px) 单列
- [ ] A11y：键盘导航、焦点环、aria 属性
- [ ] Vite 开发代理配置
- [ ] 构建验证：`npm run build` 成功
