# Phase 7 Frontend Completion Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 完整落地 edit-session 前端 Phase 7：导出、治理、页面交接与顶栏运行态提示，并修复当前阻断构建的坏实现。

**Architecture:** 以文档定义的最小闭环为边界，先补行为测试，再集中修复 API/export runtime，再把 Workspace 与 TextInput 的入口接线补齐。保持现有模块级单例 composable 模式，不引入额外全局状态库，也不扩散到 Phase 7 之外的重构。

**Tech Stack:** Vue 3、Vite、TypeScript、Element Plus、Vitest

---

## Chunk 1: API 与运行态收口

### Task 1: 锁定导出 API 合约并清掉重复实现

**Files:**
- Modify: `frontend/src/api/editSession.ts`
- Modify: `frontend/tests/phase3-regression.test.ts`

- [ ] **Step 1: 先写失败测试**

为 `subscribeExportJobEvents()`、`exportSegments()`、`exportComposition()` 增加回归测试，覆盖：
- 正确拼接 `/v1/edit-session/exports/{jobId}/events`
- accepted export payload 能被 unwrap
- 文件只保留一套导出实现

- [ ] **Step 2: 运行定向测试确认失败**

Run: `npm test -- phase3-regression.test.ts`
Expected: 因 `editSession.ts` 语法错误或缺失行为而失败。

- [ ] **Step 3: 写最小实现**

清理 `editSession.ts` 中重复的导出 API 定义，保留一套合法实现，并确保 `subscribeExportJobEvents()` 的事件路径和回调分发符合 API guide。

- [ ] **Step 4: 运行定向测试确认通过**

Run: `npm test -- phase3-regression.test.ts`
Expected: 新增回归测试通过。

### Task 2: 把 export job 跟踪正式收回 useRuntimeState

**Files:**
- Modify: `frontend/src/composables/useRuntimeState.ts`
- Modify: `frontend/src/types/editSession.ts`
- Modify: `frontend/tests/useRuntimeState.test.ts`

- [ ] **Step 1: 先写失败测试**

增加 `useRuntimeState` 回归测试，覆盖：
- render job 到达终态后清空 `currentRenderJob`
- export job 可跟踪 progress/completed/failed
- 顶栏依赖的 export/render 运行态只保留非终态 job

- [ ] **Step 2: 运行定向测试确认失败**

Run: `npm test -- useRuntimeState.test.ts`
Expected: 因缺少 export 跟踪能力或终态未清空而失败。

- [ ] **Step 3: 写最小实现**

在 `useRuntimeState.ts` 中补上 export job 状态、SSE 订阅、终态清理与对外方法，保持 render/export 两类运行态职责集中。

- [ ] **Step 4: 运行定向测试确认通过**

Run: `npm test -- useRuntimeState.test.ts`
Expected: 新增与既有测试全部通过。

## Chunk 2: Workspace 治理入口与弹窗接线

### Task 3: 接入 Workspace 顶部工具栏与 Phase 7 弹窗

**Files:**
- Modify: `frontend/src/views/WorkspaceView.vue`
- Modify: `frontend/src/components/workspace/ExportDialog.vue`
- Modify: `frontend/src/components/workspace/BaselineRestoreDialog.vue`
- Modify: `frontend/src/components/workspace/ResetSessionDialog.vue`
- Modify: `frontend/src/components/AppNavbar.vue`

- [ ] **Step 1: 先写失败测试**

增加 Phase 7 组件/集成级回归测试，覆盖：
- ready 态存在顶部工具栏入口
- render job 运行时导出按钮禁用
- 恢复基线调用 render job 跟踪
- 清空会话后回到 workspace empty 态
- 顶栏轻提示只显示“推理中 / 已暂停 / 导出中”

- [ ] **Step 2: 运行定向测试确认失败**

Run: `npm test -- workspace-phase7.test.ts`
Expected: 因页面未接线或状态未透出而失败。

- [ ] **Step 3: 写最小实现**

在 `WorkspaceView.vue` 增加顶部工具栏与 3 个弹窗接线；`ResetSessionDialog` 改为调用 `clearSession()`；`ExportDialog` 改用 `useRuntimeState` 的 export 跟踪；`AppNavbar.vue` 用真实运行态替代 placeholder-only 语义。

- [ ] **Step 4: 运行定向测试确认通过**

Run: `npm test -- workspace-phase7.test.ts`
Expected: Phase 7 页面与弹窗相关测试通过。

## Chunk 3: TextInput / Workspace 交接闭环

### Task 4: 实现送入、重建、回填三段式交接

**Files:**
- Modify: `frontend/src/composables/useInputDraft.ts`
- Modify: `frontend/src/composables/useEditSession.ts`
- Modify: `frontend/src/components/text-input/SendToWorkspaceBar.vue`
- Modify: `frontend/src/views/WorkspaceView.vue`
- Create: `frontend/src/components/workspace/sessionHandoff.ts`
- Create: `frontend/tests/sessionHandoff.test.ts`

- [ ] **Step 1: 先写失败测试**

覆盖：
- `sendToWorkspace` 只在非空草稿时跳转
- 存在未送出新稿且已有会话时，workspace 判定需要“重建会话”
- 从 workspace 回填 session head 到 input draft
- 初始化或重建成功受理后更新 `lastSentToSessionRevision`

- [ ] **Step 2: 运行定向测试确认失败**

Run: `npm test -- sessionHandoff.test.ts`
Expected: 因未实现重建/回填闭环而失败。

- [ ] **Step 3: 写最小实现**

抽一个轻量 `sessionHandoff.ts` 管理 Phase 7 的交接判定与回填逻辑；`WorkspaceView.vue` 在 empty/ready 场景里消费该逻辑，不引入额外全局守卫。

- [ ] **Step 4: 运行定向测试确认通过**

Run: `npm test -- sessionHandoff.test.ts`
Expected: 交接回归测试通过。

## Chunk 4: 总体验证与文档同步

### Task 5: 运行总验证并同步文档状态

**Files:**
- Modify: `devdoc/v0.0.2/frontend-development-final.md`（仅当实际实现与文档不一致时）

- [ ] **Step 1: 跑 Phase 7 相关测试**

Run: `npm test -- phase3-regression.test.ts useRuntimeState.test.ts workspace-phase7.test.ts sessionHandoff.test.ts`
Expected: 全部通过。

- [ ] **Step 2: 跑完整前端测试**

Run: `npm test`
Expected: 前端测试通过，若有历史失败需如实记录。

- [ ] **Step 3: 跑前端构建**

Run: `npm run build`
Expected: 构建通过。

- [ ] **Step 4: 同步文档**

若最终实现与 `devdoc/v0.0.2/frontend-development-final.md` 的 Phase 7 约束不一致，则直接覆写相应段落，保持文档与代码状态同步。

备注：提交由 wgh 手动执行，本计划不包含自动 commit 步骤。
