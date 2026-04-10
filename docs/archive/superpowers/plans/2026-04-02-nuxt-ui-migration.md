# Nuxt UI 4 Migration Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 frontend 从 Element Plus 主体迁移到 Nuxt UI 4，并同步升级 Tailwind CSS 4，保证每完成一个 Vue 文件后都通过构建验证。

**Architecture:** 先升级前端基础设施，让 Vite、Nuxt UI 4、Tailwind 4 可以在当前 Vue 3 项目中稳定协作；再按“基础组件 -> 中等复杂组件 -> 页面整合”的顺序逐个替换 Element Plus 组件。保留极少量程序化 Element Plus API 仅作为临时兜底，但模板级 `el-*` 组件和 Element 图标都要被移除。

**Tech Stack:** Vue 3, Vite 6, TypeScript, Tailwind CSS 4, Nuxt UI 4, Vue Router

---

## Chunk 1: 基础设施升级

### Task 1: 接入 Nuxt UI 4 与 Tailwind 4

**Files:**
- Modify: `frontend/package.json`
- Modify: `frontend/package-lock.json`
- Modify: `frontend/vite.config.ts`
- Modify: `frontend/src/main.ts`
- Modify: `frontend/src/App.vue`
- Modify: `frontend/src/assets/styles.css`
- Modify: `frontend/postcss.config.js`
- Modify: `frontend/tailwind.config.ts`

- [ ] 更新依赖，安装 `@nuxt/ui` 与 Tailwind 4 所需包，保留 `element-plus` 作为迁移期兜底。
- [ ] 调整 Vite 插件链，接入 `@nuxt/ui/vite`。
- [ ] 调整 `main.ts`，注册 `@nuxt/ui/vue-plugin`。
- [ ] 调整 `App.vue`，在根部挂载 `UApp`，为 toast / modal 等全局能力提供宿主。
- [ ] 将 `styles.css` 切换到 Tailwind 4 / Nuxt UI 4 的导入方式，并保留现有主题 token。
- [ ] 视升级需要收敛或移除不再生效的 `tailwind.config.ts` / `postcss.config.js` 配置。
- [ ] 运行 `npm run build`，确认基础设施升级完成。

## Chunk 2: 逐个迁移组件

### Task 2: 迁移基础组件

**Files:**
- Modify: `frontend/src/components/StatusIndicator.vue`
- Modify: `frontend/src/components/ParameterSlider.vue`
- Modify: `frontend/src/components/TtsForm.vue`
- Modify: `frontend/src/components/VoiceSelect.vue`

- [ ] 按文件顺序逐个替换为 Nuxt UI 组件。
- [ ] 每完成一个 `.vue` 文件后运行 `npm run build`。
- [ ] 每次构建失败时立即修复，不带错进入下一个文件。

### Task 3: 迁移中等复杂组件

**Files:**
- Modify: `frontend/src/components/AppNavbar.vue`
- Modify: `frontend/src/components/AudioPlayer.vue`
- Modify: `frontend/src/components/InferenceControlBar.vue`
- Modify: `frontend/src/components/AudioResultPanel.vue`
- Modify: `frontend/src/components/FileUploader.vue`
- Modify: `frontend/src/components/InferenceSettingsPanel.vue`

- [ ] 统一替换 Element 图标为 Nuxt UI / Iconify 图标。
- [ ] 处理滑块、上传、确认框、进度条、提示框等差异化 API。
- [ ] 每完成一个 `.vue` 文件后运行 `npm run build`。

## Chunk 3: 页面整合与收尾

### Task 4: 迁移页面文件

**Files:**
- Modify: `frontend/src/views/TtsStudioView.vue`
- Modify: `frontend/src/views/VoiceAdminView.vue`

- [ ] 在单文件内部完成必要的局部整理，不扩散到 API / composable 层。
- [ ] 优先移除模板中的 `el-*` 组件；程序化 `ElMessage / ElMessageBox` 在替换成本过高时可短暂保留。
- [ ] 每完成一个 `.vue` 文件后运行 `npm run build`。

### Task 5: 全量收尾验证

**Files:**
- Modify: `devdoc/nuxt-ui-migration-guide.md`

- [ ] 扫描 `frontend/src` 中剩余的 Element Plus 模板与图标引用。
- [ ] 根据最终代码状态同步更新迁移文档，确保文档只反映当前实现。
- [ ] 运行最终 `npm run build`，如实记录结果。
