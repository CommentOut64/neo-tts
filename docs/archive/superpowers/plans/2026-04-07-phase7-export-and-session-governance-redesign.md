# Phase 7 Export And Session Governance Redesign Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 按最新 spec 重做 Phase 7：恢复旧版 navbar，再以最小增量加入独立导出入口；移除 Workspace 会话操作 card；保留 handoff 与双向清空会话逻辑。

**Architecture:** 先通过回归测试锁定新的产品语义，再按“入口层、Workspace 布局层、正文区次级按钮层、导出状态层”四个边界收口。导出只依赖后端持久化 `document_version`；清空会话与 handoff 从页面级治理面板下沉到正文区顶部按钮与既有清空流程。

**Tech Stack:** Vue 3、TypeScript、Element Plus、Vitest、Vite

---

## Chunk 1: 入口层与状态判定

### Task 1: 锁定 navbar 与导出门禁的新规则

**Files:**
- Modify: `frontend/tests/sessionHandoff.test.ts`
- Modify: `frontend/src/components/workspace/sessionHandoff.ts`
- Modify: `frontend/src/components/AppNavbar.vue`

- [ ] **Step 1: Write the failing test**

补充回归测试，覆盖：
- navbar 运行态提示与导出门禁的判定函数
- render job `paused` 时允许导出
- render job 运行态时禁用导出
- `AppNavbar.vue` 不再依赖会话操作 card 的运行态占位实现

- [ ] **Step 2: Run test to verify it fails**

Run: `npm test -- sessionHandoff.test.ts`
Expected: 因当前门禁规则和 helper 逻辑不符合新设计而失败。

- [ ] **Step 3: Write minimal implementation**

调整 `sessionHandoff.ts` 只保留仍需要的判定函数；恢复 `AppNavbar.vue` 到旧版视觉与逻辑，再最小增量加入导出按钮与新门禁。

- [ ] **Step 4: Run test to verify it passes**

Run: `npm test -- sessionHandoff.test.ts`
Expected: 相关回归测试通过。

## Chunk 2: Workspace 布局与页面治理入口下沉

### Task 2: 删除 Workspace 会话操作 card，重挂次级按钮

**Files:**
- Modify: `frontend/src/views/WorkspaceView.vue`
- Modify: `frontend/src/components/workspace/WorkspaceEditorHost.vue`
- Modify: `frontend/src/components/workspace/ResetSessionDialog.vue`
- Modify: `frontend/src/composables/useWorkspaceDialogState.ts`

- [ ] **Step 1: Write the failing test**

新增回归测试，覆盖：
- `WorkspaceView.vue` 不再渲染会话操作 card
- `WorkspaceEditorHost.vue` 顶部按钮区保留“清空会话”和“转到文本输入页继续编辑”
- `ResetSessionDialog.vue` 仍然使用 `clearSession()` 的当前语义

- [ ] **Step 2: Run test to verify it fails**

Run: `npm test -- workspace-governance-redesign.test.ts`
Expected: 因页面上仍存在 card 或入口位置不正确而失败。

- [ ] **Step 3: Write minimal implementation**

从 `WorkspaceView.vue` 移除 card 与恢复基线接线；将回填文本与清空会话入口下沉到 `WorkspaceEditorHost.vue` 顶部工具区；只保留必要的对话框状态。

- [ ] **Step 4: Run test to verify it passes**

Run: `npm test -- workspace-governance-redesign.test.ts`
Expected: Workspace 治理入口下沉后的测试通过。

## Chunk 3: 导出中心独立化

### Task 3: 让导出只依赖后端持久化版本

**Files:**
- Modify: `frontend/src/components/workspace/ExportDialog.vue`
- Modify: `frontend/src/composables/useRuntimeState.ts`
- Modify: `frontend/tests/useRuntimeState.test.ts`
- Modify: `frontend/tests/phase3-regression.test.ts`
- Modify: `frontend/tests/workspace-governance-redesign.test.ts`

- [ ] **Step 1: Write the failing test**

覆盖：
- `ExportDialog.vue` 仅依赖 `snapshot.document_version`
- render job 运行中禁用导出，`paused` 不禁用
- export job 继续通过 `useRuntimeState.ts` 跟踪
- 移除对恢复基线和页面 card 的耦合

- [ ] **Step 2: Run test to verify it fails**

Run: `npm test -- phase3-regression.test.ts useRuntimeState.test.ts workspace-governance-redesign.test.ts`
Expected: 因导出门禁或依赖来源仍旧不符合设计而失败。

- [ ] **Step 3: Write minimal implementation**

调整 `ExportDialog.vue` 的禁用逻辑和数据读取边界；保留 export runtime 观测，但移除对页面级治理面板的假设。

- [ ] **Step 4: Run test to verify it passes**

Run: `npm test -- phase3-regression.test.ts useRuntimeState.test.ts workspace-governance-redesign.test.ts`
Expected: 导出中心相关测试通过。

## Chunk 4: Handoff 与双向清空回归

### Task 4: 保留 handoff 与文本输入页清空共管逻辑

**Files:**
- Modify: `frontend/src/views/WorkspaceView.vue`
- Modify: `frontend/src/components/text-input/TextInputArea.vue`
- Modify: `frontend/src/components/text-input/clearInputDraftFlow.ts`
- Modify: `frontend/tests/clearInputDraftFlow.test.ts`
- Modify: `frontend/tests/sessionHandoff.test.ts`

- [ ] **Step 1: Write the failing test**

覆盖：
- `转到文本输入页继续编辑` 仍会回填 session head
- 输入稿版本领先时仍能提示重建会话
- 文本输入页清空时的“同步清理会话”逻辑不回退
- workspace 清空会话不清空输入稿文本

- [ ] **Step 2: Run test to verify it fails**

Run: `npm test -- clearInputDraftFlow.test.ts sessionHandoff.test.ts workspace-governance-redesign.test.ts`
Expected: 因入口迁移或状态边界变化导致旧测试失败。

- [ ] **Step 3: Write minimal implementation**

让 handoff 继续存在，但只通过正文区按钮和状态判定触发；确保文本输入页清空与 workspace 清空会话仍共用现有清理语义。

- [ ] **Step 4: Run test to verify it passes**

Run: `npm test -- clearInputDraftFlow.test.ts sessionHandoff.test.ts workspace-governance-redesign.test.ts`
Expected: handoff 与清空会话相关测试通过。

## Chunk 5: 总验证与文档同步

### Task 5: 全量验证并同步设计文档

**Files:**
- Modify: `docs/superpowers/specs/2026-04-07-phase7-export-and-session-governance-redesign.md`（仅在实现后需要微调措辞时）

- [ ] **Step 1: Run focused regression suite**

Run: `npm test -- phase3-regression.test.ts useRuntimeState.test.ts sessionHandoff.test.ts clearInputDraftFlow.test.ts workspace-governance-redesign.test.ts`
Expected: 全部通过。

- [ ] **Step 2: Run full frontend test suite**

Run: `npm test`
Expected: 前端测试全部通过。

- [ ] **Step 3: Run frontend build**

Run: `npm run build`
Expected: 构建通过。

- [ ] **Step 4: Sync docs if needed**

若实现过程中对 spec 细节有最小偏移，直接更新 spec 文档，保持当前状态同步。

备注：提交由 wgh 手动执行，本计划不包含自动 commit 步骤。
