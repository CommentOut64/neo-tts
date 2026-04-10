# Workspace Pause Compose Lock Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 Workspace 中的停顿/边界修改走正式的后端 compose-only 流程，前端在处理期间进入全局一致性锁，直到新音频已可播放后再原子更新 Editor、参数表和播放状态。

**Architecture:** 前端不再对 edge 停顿做乐观更新，而是引入一个全局 processing state machine，统一管理提交、后端处理、前端 hydration 与原子切换。后端继续作为正式状态唯一真源，pause-only 修改只重拼接 block、不重推理 segment，并通过 SSE 驱动前端进入 hydration、预热音频后一次性切换正式状态。

**Tech Stack:** Vue 3、TypeScript、Vitest、FastAPI、Python、SSE、现有 edit-session render job / timeline / playback 架构

---

## 文件结构

**前端核心状态与协调**
- Create: `frontend/src/composables/useWorkspaceProcessing.ts`
  负责全局 processing state machine、锁定矩阵、提交摘要、进入/退出 hydrating、完成/失败提示条件。
- Modify: `frontend/src/composables/useRuntimeState.ts`
  负责把 render job 事件暴露给 workspace processing，而不是只在 terminal 时做被动刷新。
- Modify: `frontend/src/composables/useParameterPanel.ts`
  edge 提交统一走 `/edges/{id}` job，接入 processing coordinator，而不是直接刷新正式 UI。
- Modify: `frontend/src/composables/useEditSession.ts`
  提供可被 processing coordinator 调用的“拉取最新正式快照 + timeline + edges”的聚合接口。
- Modify: `frontend/src/composables/usePlayback.ts`
  增加 block 预热、切换前暂停、切换后替换 timeline/block cache 的能力。

**前端 UI 与锁定矩阵**
- Modify: `frontend/src/views/WorkspaceView.vue`
  展示全局处理中提示、遮罩/状态条，统一承接 processing state。
- Modify: `frontend/src/components/workspace/WorkspaceEditorHost.vue`
  processing 中禁止进入编辑、禁止触发播放与 seek。
- Modify: `frontend/src/components/workspace/TransportControlBar.vue`
  processing 中禁用播放、暂停、拖动。
- Modify: `frontend/src/components/workspace/MainActionButton.vue`
  processing 中禁止重推理。
- Modify: `frontend/src/components/workspace/ParameterDraftBar.vue`
  processing 中显示“处理中”说明，并禁用提交/放弃。
- Modify: `frontend/src/components/workspace/ParameterPanelHost.vue`
  透传 processing lock 到各参数面板。
- Modify: `frontend/src/components/workspace/EdgeParameterPanel.vue`
  使用正式 processing 提交路径，处理中置灰。
- Modify: `frontend/src/components/workspace/ResetSessionDialog.vue`
  processing 中禁用清空会话。
- Modify: `frontend/src/components/workspace/ExportDialog.vue`
  processing 中禁用导出。

**后端事件与 compose-only 路径**
- Modify: `backend/app/services/render_job_service.py`
  确保 edge pause-only job 的事件负载足够支撑前端 hydration；必要时补 `changed_block_asset_ids` / `audio_url` 相关信息。
- Modify: `backend/app/services/render_planner.py`
  保持 edge pause-only 为 `compose_only=True`，并为后续 block 限幅打基础。
- Modify: `backend/app/api/routers/edit_session.py`
  明确 `/edges/{id}` 为正式入口；`/config` 仅保留给纯配置接口或内部用途。

**测试**
- Create: `frontend/tests/useWorkspaceProcessing.test.ts`
- Modify: `frontend/tests/useParameterPanel.test.ts`
- Modify: `frontend/tests/usePlayback.seek-fade.test.ts`
- Modify: `frontend/tests/workspaceEditorHostLayoutMode.test.ts`
- Modify: `backend/tests/integration/test_edit_session_router.py`

---

## 目标状态机

### 状态

- `idle`
  正式状态稳定，无后台任务。
- `submitting`
  前端已发起请求，等待后端接受。
- `processing`
  后端 job 已开始运行。
- `hydrating`
  后端已提交新 timeline，前端正在抓取最新正式状态并预热新 block 音频。
- `failed`
  本次处理失败，保持旧正式状态。

### 事件

- `SUBMIT_EDGE_UPDATE`
- `JOB_ACCEPTED`
- `JOB_PROGRESS`
- `TIMELINE_COMMITTED`
- `HYDRATION_READY`
- `JOB_FAILED`
- `HYDRATION_FAILED`
- `RESET`

### 转移

- `idle -> submitting`
- `submitting -> processing`
- `processing -> hydrating`
- `hydrating -> idle`
- `submitting|processing|hydrating -> failed -> idle`

### 锁定规则

processing 期间禁止：
- 提交参数
- 放弃/切换参数草稿
- 正文编辑
- 重推理
- 播放、暂停、seek、拖动播放头
- 导出
- 恢复基线
- 清空会话

processing 期间允许：
- 滚动
- 阅读
- 查看当前旧正式内容
- 查看处理中提示

---

## Chunk 1: 全局 Processing 状态机

### Task 1: 建立 processing composable

**Files:**
- Create: `frontend/src/composables/useWorkspaceProcessing.ts`
- Test: `frontend/tests/useWorkspaceProcessing.test.ts`

- [ ] **Step 1: 写失败测试，定义状态机最小行为**

覆盖：
- 初始为 `idle`
- `startSubmitting` 后变 `submitting`
- `jobAccepted` 后变 `processing`
- `timelineCommitted` 后变 `hydrating`
- `hydrationReady` 后回 `idle`
- `fail` 后回 `failed` 再 `idle`

- [ ] **Step 2: 运行测试确认失败**

Run: `npm run test -- useWorkspaceProcessing.test.ts`
Expected: FAIL，提示 composable 尚不存在或状态转移不匹配

- [ ] **Step 3: 实现最小 composable**

导出至少包含：
- `phase`
- `jobKind`
- `jobId`
- `pendingSummary`
- `isLocked`
- `startSubmitting`
- `acceptJob`
- `enterHydrating`
- `completeHydration`
- `fail`
- `reset`

- [ ] **Step 4: 运行测试确认通过**

Run: `npm run test -- useWorkspaceProcessing.test.ts`
Expected: PASS

### Task 2: 将 runtimeState 事件桥接到 processing

**Files:**
- Modify: `frontend/src/composables/useRuntimeState.ts`
- Modify: `frontend/src/composables/useWorkspaceProcessing.ts`
- Test: `frontend/tests/useWorkspaceProcessing.test.ts`

- [ ] **Step 1: 写失败测试，定义 `timeline_committed` 会驱动 processing 进入 hydrating**

- [ ] **Step 2: 运行测试确认失败**

- [ ] **Step 3: 在 `useRuntimeState.ts` 中暴露 job 事件订阅或回调注入点**

要求：
- 不改变当前 render job 跟踪主语义
- 让 workspace processing 能监听 `job_state_changed` / `timeline_committed`

- [ ] **Step 4: 运行测试确认通过**

---

## Chunk 2: Edge 正式提交链路

### Task 3: edge 提交统一走正式 job，不直接改正式 UI

**Files:**
- Modify: `frontend/src/composables/useParameterPanel.ts`
- Modify: `frontend/src/components/workspace/ParameterDraftBar.vue`
- Modify: `frontend/src/components/workspace/EdgeParameterPanel.vue`
- Test: `frontend/tests/useParameterPanel.test.ts`

- [ ] **Step 1: 写失败测试，定义 edge 提交行为**

覆盖：
- 选择 edge 后提交调用 `/edges/{id}`
- 提交时进入 `submitting`
- 不立刻刷新正式 `snapshot/edges/timeline`
- 等待 processing 协调器接管

- [ ] **Step 2: 运行测试确认失败**

- [ ] **Step 3: 修改 `useParameterPanel.ts`**

要求：
- edge 仅使用 `updateEdge`
- 提交前生成 `pendingSummary`
- 调用 `useWorkspaceProcessing.startSubmitting`
- 不再以“提交完成即刷新正式状态”为结束条件

- [ ] **Step 4: 修改参数栏文案**

要求：
- 处理中显示“正在重拼接停顿…”
- 不再出现“提交后仅持久化配置”的说明

- [ ] **Step 5: 运行测试确认通过**

Run: `npm run test -- useParameterPanel.test.ts`
Expected: PASS

### Task 4: 明确 `/edges/{id}` 是正式入口

**Files:**
- Modify: `backend/app/api/routers/edit_session.py`
- Modify: `backend/tests/integration/test_edit_session_router.py`

- [ ] **Step 1: 写失败测试，定义 pause update 走正式 job 后 timeline 与 block 会更新**

- [ ] **Step 2: 运行测试确认失败**

- [ ] **Step 3: 如有必要，补接口说明/注释，避免前端继续误用 `/config`**

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run --isolated --group dev pytest backend/tests/integration/test_edit_session_router.py -q`
Expected: PASS

---

## Chunk 3: Hydration 与原子切换

### Task 5: 收到 `timeline_committed` 后拉取正式状态并预热音频

**Files:**
- Modify: `frontend/src/composables/useEditSession.ts`
- Modify: `frontend/src/composables/usePlayback.ts`
- Modify: `frontend/src/composables/useWorkspaceProcessing.ts`
- Test: `frontend/tests/useWorkspaceProcessing.test.ts`
- Test: `frontend/tests/usePlayback.seek-fade.test.ts`

- [ ] **Step 1: 写失败测试，定义 hydration 的完成条件**

覆盖：
- 收到 `timeline_committed` 后进入 `hydrating`
- 并发拉取新 `snapshot/timeline/edges`
- 预拉取并 decode 受影响 block
- 只有在预热完成后才允许 `hydrationReady`

- [ ] **Step 2: 运行测试确认失败**

- [ ] **Step 3: 在 `useEditSession.ts` 增加聚合刷新方法**

建议新增：
- `refreshFormalSessionState()`
  一次性拉取 `snapshot + timeline + edges + segments/resources(如需要)`

- [ ] **Step 4: 在 `usePlayback.ts` 增加 block 预热能力**

建议新增：
- `warmBlocks(audioUrls: string[])`
- `pauseForFormalUpdate()`
- `replacePlaybackSources()` 或同等封装

- [ ] **Step 5: 在 `useWorkspaceProcessing.ts` 中完成 hydration 编排**

要求：
- 在新 block 可播放前不切正式状态
- 完成后统一发出 “ready to switch”

- [ ] **Step 6: 运行测试确认通过**

Run: `npm run test -- useWorkspaceProcessing.test.ts usePlayback.seek-fade.test.ts`
Expected: PASS

### Task 6: 原子切换正式 UI

**Files:**
- Modify: `frontend/src/views/WorkspaceView.vue`
- Modify: `frontend/src/components/workspace/WorkspaceEditorHost.vue`
- Modify: `frontend/src/components/workspace/ParameterPanelHost.vue`
- Modify: `frontend/src/composables/useWorkspaceProcessing.ts`
- Test: `frontend/tests/workspaceEditorHostLayoutMode.test.ts`

- [ ] **Step 1: 写失败测试，定义 Editor/参数表/播放引用只在 hydration 完成后切换**

- [ ] **Step 2: 运行测试确认失败**

- [ ] **Step 3: 实现原子切换**

要求：
- Editor pauseBoundary attrs 在切换点统一更新
- 参数表正式值在切换点统一更新
- playback timeline/block cache 在切换点统一切换

- [ ] **Step 4: 运行测试确认通过**

---

## Chunk 4: 全局锁定矩阵

### Task 7: 让所有 mutation 与播放相关控件受 processing lock 控制

**Files:**
- Modify: `frontend/src/components/workspace/WorkspaceEditorHost.vue`
- Modify: `frontend/src/components/workspace/TransportControlBar.vue`
- Modify: `frontend/src/components/workspace/MainActionButton.vue`
- Modify: `frontend/src/components/workspace/ExportDialog.vue`
- Modify: `frontend/src/components/workspace/ResetSessionDialog.vue`
- Modify: `frontend/src/components/workspace/ParameterDraftBar.vue`
- Modify: `frontend/src/views/WorkspaceView.vue`

- [ ] **Step 1: 写失败测试或组件行为断言**

至少覆盖：
- processing 中禁止重推理
- processing 中禁止播放/seek
- processing 中禁止参数提交
- processing 中禁止正文编辑
- processing 中禁止导出与清空

- [ ] **Step 2: 运行测试确认失败**

- [ ] **Step 3: 实现锁定矩阵**

要求：
- 不做全页面 pointer-events: none
- 仅禁用 mutation 和 playback 相关交互
- 保留滚动和阅读

- [ ] **Step 4: 在 `WorkspaceView.vue` 增加全局处理提示**

提示至少区分：
- 提交中
- 正在重拼接
- 正在准备新音频
- 处理完成
- 处理失败

- [ ] **Step 5: 运行相关测试确认通过**

---

## Chunk 5: 性能与 4 秒目标的结构性保障

### Task 8: 为 pause-only 更新建立尾延迟治理方案

**Files:**
- Modify: `backend/app/services/block_planner.py`
- Modify: `backend/app/services/render_planner.py`
- Modify: `backend/app/services/render_job_service.py`
- Test: `backend/tests/integration/test_edit_session_router.py`

- [ ] **Step 1: 写失败测试，定义超长后文下 pause-only 不得全局重拼接**

- [ ] **Step 2: 运行测试确认失败**

- [ ] **Step 3: 给 block 建立硬上限**

建议：
- 最大时长
- 或最大 segment 数

要求：
- 单次 pause 更新最多脏化局部 block（必要时波及相邻 block）
- 不因后文超长而让单次修改触发整篇音频重拼接

- [ ] **Step 4: 在事件/日志中记录 pause-only 的 dirty block 数量与耗时**

- [ ] **Step 5: 运行测试确认通过**

Run: `uv run --isolated --group dev pytest backend/tests/integration/test_edit_session_router.py -q`
Expected: PASS

---

## 验收标准

- edge 停顿提交期间，Editor / 参数表 / 音频不出现半更新状态。
- processing 期间不能发起重推理，也不能提交新的停顿修改。
- 收到 `timeline_committed` 后，前端会进入 hydration，而不是直接提示完成。
- 只有新 block 音频已可播放时，才一次性更新正式状态并提示完成。
- 停顿修改失败时，旧正式状态保持不变。
- 后续性能治理完成后，pause-only 更新在常规场景下可稳定压到可接受延迟范围，并具备极端长文下的结构性上限。

---

## 建议实施顺序

1. 先做 Chunk 1-4，先把“一致性闭环”做对。
2. 再做 Chunk 5，把“4 秒目标”从体验目标升级为有结构约束支撑的性能目标。

---

Plan complete and saved to `docs/superpowers/plans/2026-04-08-workspace-pause-compose-lock.md`. Ready to execute?
