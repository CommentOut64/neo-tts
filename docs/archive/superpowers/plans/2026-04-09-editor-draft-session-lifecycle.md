# Editor Draft Session Lifecycle Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 Editor 改造成真正的工作区草稿层，做到“编辑即时可见、但不立即污染输入页和正式正文；只有重推理成功才推进当前音频对应文字；结束当前会话前必须显式处理待重推理内容，并在结束后退回语音生成页的首次生成前状态”。

**Architecture:** 以前端状态重构为主，明确拆开 `input_text / session_initial_text / applied_text / working_text` 四层文本对象，并把输入页同步改成显式动作而不是编辑副作用。P0 先用现有后端能力完成闭环；P1 再补会话结束的后端收口与中止硬化；P2 视产品策略决定是否做跨会话缓存复用与批量重推理优化。

**Tech Stack:** Vue 3、TypeScript、Element Plus、Vitest、FastAPI、Python、现有 edit-session / render job / localStorage 工作区草稿体系

---

## 为什么这次应做局部重构而不是继续打补丁

当前代码已经出现明确的结构性信号：

- `WorkspaceEditorHost.vue` 会把 `effectiveText` 直接回写到 `useInputDraft()`，导致 `working_text` 污染 `input_text`
- `useEditSession.ts` 又把输入页版本号当成会话同步依据，导致“输入页是否已同步”和“会话正式文本是否已提交”耦合在一起
- `ResetSessionDialog.vue` 的语义仍是“清空会话”，无法承载“结束当前会话前处理待重推理内容”的分支决策
- 现有文案还把“结束会话”错误表达成“返回输入页”，混淆了页面位置与状态语义

因此本计划选择 **B. 局部重构**，但范围只限定在：

- Workspace 编辑闭环
- 输入页与会话的交接闭环
- 会话结束与恢复最初版本闭环
- 必要的后端中止/删除会话收口能力

不包含：

- 全量重写 editor 文档模型
- 重做 timeline / export 架构
- 改写现有段级重推理主链路

---

## 文件结构

**术语与行为基线**
- Reference: `docs/系统术语和对应.md`

**前端核心状态**
- Modify: `frontend/src/composables/useInputDraft.ts`
  输入页文本的唯一真源；新增最近一轮最初版本缓存、显式 handoff / restore API，禁止普通编辑时被 Workspace 自动覆盖。
- Modify: `frontend/src/composables/useEditSession.ts`
  暴露 `session_initial_text`、`applied_text`、显式回填输入页动作、结束会话动作，以及更干净的输入同步判定。
- Modify: `frontend/src/components/workspace/sessionHandoff.ts`
  重新定义输入页进入 Workspace 的判定，适配 `applied_text`、`input_handoff`、重建会话逻辑。
- Modify: `frontend/src/composables/useWorkspaceLightEdit.ts`
  保留局部草稿集合，但语义对齐为待重推理片段集，不再暗示“输入页草稿已同步”。
- Modify: `frontend/src/utils/workspaceDraftSnapshot.ts`
  如需要，补充工作副本持久化字段，使页面刷新后仍能恢复 `working_text` 与待重推理状态。
- Modify: `frontend/src/composables/useWorkspaceDraftPersistence.ts`
  与新的工作副本快照字段保持一致。

**前端 UI 与交互**
- Modify: `frontend/src/components/workspace/WorkspaceEditorHost.vue`
  停止普通编辑过程中的输入页回写；只在重推理成功或显式保留文字并结束会话时同步输入页。
- Modify: `frontend/src/components/workspace/MainActionButton.vue`
  主动作维持“重推理”，并显示局部增量提示。
- Modify: `frontend/src/components/workspace/mainActionButtonState.ts`
  统一按钮文案与待重推理数量展示。
- Create: `frontend/src/components/workspace/EndSessionDialog.vue`
  承载“继续编辑 / 保留文字并结束会话 / 撤销未重推理修改并结束会话”的分支确认。
- Modify: `frontend/src/views/WorkspaceView.vue`
  接入新的结束会话流、输入回带流和会话入口流，并明确结束后退回语音生成页首次生成前状态。
- Modify: `frontend/src/components/text-input/TextInputArea.vue`
  增加“恢复最初版本”入口，展示何时可恢复。
- Modify: `frontend/src/components/text-input/clearInputDraftFlow.ts`
  保持“清空输入页文字”和“结束当前会话”的边界清晰。
- Modify: `frontend/src/components/workspace/DirtySegmentBadge.vue`
  对齐“待重推理”文案与提示。

**后端与接口硬化**
- Modify: `backend/app/services/edit_session_service.py`
  把删除会话改成“安全结束当前会话”，避免运行中作业被粗暴 `reset()`。
- Modify: `backend/app/services/edit_session_runtime.py`
  明确 delete/end-session 期间的 active job 收口语义。
- Modify: `backend/app/services/render_job_service.py`
  如需要，补充取消后终态和可观测事件，避免前端等待逻辑无锚点。
- Modify: `backend/app/api/routers/edit_session.py`
  如需要，新增或细化“结束当前会话/中止当前作业”接口说明。

**测试**
- Modify: `frontend/tests/useInputDraft.test.ts`
- Modify: `frontend/tests/useEditSessionSync.test.ts`
- Modify: `frontend/tests/sessionHandoff.test.ts`
- Modify: `frontend/tests/mainActionButtonState.test.ts`
- Modify: `frontend/tests/clearInputDraftFlow.test.ts`
- Modify: `frontend/tests/useWorkspaceLightEdit.test.ts`
- Modify: `frontend/tests/workspaceEditorHostLayoutMode.test.ts`
- Create: `frontend/tests/workspaceEndSessionFlow.test.ts`
- Modify: `backend/tests/integration/test_edit_session_router.py`

---

## P0 范围：先完成 Editor 草稿目标的最小闭环

P0 完成后必须达到：

- Editor 修改只改变 `working_text`
- 输入页文字不再被普通编辑过程自动覆盖
- 只有重推理成功才把 `applied_text` 回写到输入页
- 结束当前会话前，若存在待重推理内容，必须让用户显式选择
- 结束当前会话后，页面状态回到语音生成页的首次生成前，而不是错误表述成返回输入文本页
- 输入页可恢复“最近一轮最初版本”

---

## Chunk 1: 锁定新的文本生命周期契约

### Task 1: 用测试冻结四层文本语义

**Files:**
- Modify: `frontend/tests/useInputDraft.test.ts`
- Modify: `frontend/tests/useEditSessionSync.test.ts`
- Modify: `frontend/tests/sessionHandoff.test.ts`
- Create: `frontend/tests/workspaceEndSessionFlow.test.ts`

- [ ] **Step 1: 写失败测试，覆盖新的输入页语义**

至少覆盖：
- `backfillFromAppliedText()` 只用于正式文本回填
- `handoffFromWorkspace()` 只允许在显式结束会话分支中调用
- 普通 Editor 编辑不会改动输入页文字
- `rememberLastSessionInitialText()` 与 `restoreLastSessionInitialText()` 可跨会话工作

- [ ] **Step 2: 写失败测试，覆盖新的会话入口与退出语义**

至少覆盖：
- 输入页来源为 `input_handoff` 时，不代表当前会话已提交成功
- 会话存在且输入页文字领先时，入口动作为“重建会话”
- 结束当前会话且存在待重推理内容时，出现三分支确认
- “撤销未重推理修改并结束会话”会回到 `applied_text`
- 结束后回到语音生成页的首次生成前状态，而不是输入文本页

- [ ] **Step 3: 运行测试确认失败**

Run: `npm test -- useInputDraft.test.ts useEditSessionSync.test.ts sessionHandoff.test.ts workspaceEndSessionFlow.test.ts`
Expected: FAIL，当前实现仍把 workspace 草稿当成输入页同步来源。

- [ ] **Step 4: 完成后重复运行上述测试确认通过**

---

## Chunk 2: 拆开 input_text / session_initial_text / applied_text / working_text

### Task 2: 重构输入页状态模型

**Files:**
- Modify: `frontend/src/composables/useInputDraft.ts`
- Modify: `frontend/tests/useInputDraft.test.ts`

- [ ] **Step 1: 重命名并收紧输入来源语义**

建议把 `InputDraftSource` 调整为能映射新模型的集合，例如：
- `manual`
- `applied_text`
- `input_handoff`

要求：
- 不再保留“workspace 正在实时镜像输入页”的语义
- localStorage 中持久化最近一轮最初版本

- [ ] **Step 2: 增加显式 API**

至少包含：
- `backfillFromAppliedText(text)`
- `handoffFromWorkspace(text)`
- `rememberLastSessionInitialText(text)`
- `restoreLastSessionInitialText()`

- [ ] **Step 3: 清理旧 API**

要求：
- 删除或废弃 `syncFromWorkspaceDraft()`
- `backfillFromSession()` 改成更准确的正式文本命名

- [ ] **Step 4: 运行测试确认通过**

Run: `npm test -- useInputDraft.test.ts`
Expected: PASS

### Task 3: 重构会话同步判定

**Files:**
- Modify: `frontend/src/composables/useEditSession.ts`
- Modify: `frontend/src/components/workspace/sessionHandoff.ts`
- Modify: `frontend/tests/useEditSessionSync.test.ts`
- Modify: `frontend/tests/sessionHandoff.test.ts`

- [ ] **Step 1: 改写 `resolveInputDraftSyncAction()`**

要求：
- 只围绕 `applied_text` 是否应回填输入页做判定
- 不再把 Workspace 普通编辑当成输入同步依据
- 初始化成功、重推理成功后允许回填
- 输入页已有人工新稿时禁止静默覆盖

- [ ] **Step 2: 在 `useEditSession.ts` 显式暴露会话文本**

至少包含：
- `sessionInitialText`
- `appliedText`
- `backfillInputDraftFromAppliedText()`
- `rememberSessionInitialText()`

- [ ] **Step 3: 调整 Workspace 入口判定**

要求：
- “结束会话时保留的文字”只影响下一轮会话初始化
- 不把 `input_handoff` 误判成“当前会话已经同步”

- [ ] **Step 4: 运行测试确认通过**

Run: `npm test -- useEditSessionSync.test.ts sessionHandoff.test.ts`
Expected: PASS

---

## Chunk 3: 让 Editor 只维护 working_text，不再污染输入页

### Task 4: 切断 Workspace 到输入页的自动回写链路

**Files:**
- Modify: `frontend/src/components/workspace/WorkspaceEditorHost.vue`
- Modify: `frontend/src/composables/useWorkspaceLightEdit.ts`
- Modify: `frontend/src/utils/workspaceDraftSnapshot.ts`
- Modify: `frontend/src/composables/useWorkspaceDraftPersistence.ts`
- Modify: `frontend/tests/useWorkspaceLightEdit.test.ts`
- Modify: `frontend/tests/workspaceEditorHostLayoutMode.test.ts`

- [ ] **Step 1: 写失败测试，确认普通编辑不再回写输入页**

至少覆盖：
- Editor 本地编辑后，输入页文字保持不变
- 页面刷新后，Workspace 本地工作副本仍可恢复
- 待重推理片段集仍可从本地状态恢复

- [ ] **Step 2: 删除 `WorkspaceEditorHost.vue` 中对输入页的实时同步**

要求：
- 移除或替换 `inputDraft.syncFromWorkspaceDraft(effectiveText)` 这类链路
- 保留本地持久化，但持久化目标只限工作副本快照

- [ ] **Step 3: 明确重推理成功后的唯一回写点**

要求：
- 仅在段级重推理作业全部成功并刷新出新的 `applied_text` 后，调用 `backfillInputDraftFromAppliedText()`
- 失败、取消、部分取消都不得提前覆盖输入页

- [ ] **Step 4: 如有必要，给工作副本快照补最小字段**

优先只补最小闭环字段，例如：
- `effectiveText`
- `segmentDrafts`
- 可恢复待重推理状态的最小元数据

- [ ] **Step 5: 运行测试确认通过**

Run: `npm test -- useWorkspaceLightEdit.test.ts workspaceEditorHostLayoutMode.test.ts`
Expected: PASS

### Task 5: 收紧主动作与待重推理提示

**Files:**
- Modify: `frontend/src/components/workspace/MainActionButton.vue`
- Modify: `frontend/src/components/workspace/mainActionButtonState.ts`
- Modify: `frontend/src/components/workspace/DirtySegmentBadge.vue`
- Modify: `frontend/tests/mainActionButtonState.test.ts`

- [ ] **Step 1: 写失败测试，锁定主按钮与提示文案**

至少覆盖：
- 主按钮文案保持“重推理”
- dirty count > 0 时提供增量提示，如 `重推理(2)` 或等价表达
- badge 使用“待重推理”

- [ ] **Step 2: 实现 UI 文案与禁用条件调整**

要求：
- 对外保留专业词 `重推理`
- 同时给出局部性暗示，避免用户误以为每次都全篇重跑

- [ ] **Step 3: 运行测试确认通过**

Run: `npm test -- mainActionButtonState.test.ts`
Expected: PASS

---

## Chunk 4: 重建“结束当前会话”与“恢复最初版本”闭环

### Task 6: 用新的对话框替代“清空会话”

**Files:**
- Create: `frontend/src/components/workspace/EndSessionDialog.vue`
- Modify: `frontend/src/views/WorkspaceView.vue`
- Modify: `frontend/src/components/workspace/ResetSessionDialog.vue`
- Modify: `frontend/tests/workspaceEndSessionFlow.test.ts`

- [ ] **Step 1: 写失败测试，锁定结束会话分支**

至少覆盖：
- 无待重推理内容时，可直接结束当前会话并退回语音生成页首次生成前
- 有待重推理内容时，弹出三分支确认
- `继续编辑`
- `保留文字并结束会话`
- `撤销未重推理修改并结束会话`

- [ ] **Step 2: 新建 `EndSessionDialog.vue`**

要求：
- Editor 顶部按钮文案使用“结束会话”
- 破坏性确认使用“结束当前会话”
- 文案解释清楚“结束后将回到首次生成前”
- 文案解释清楚“保留文字并结束会话不会更新当前音频”

- [ ] **Step 3: 迁移或下沉旧 `ResetSessionDialog.vue` 语义**

要求二选一：
- 彻底删除旧“清空会话”语义
- 或只保留为无会话/异常场景的兼容壳，但主流程必须切到 `EndSessionDialog`

- [ ] **Step 4: 运行测试确认通过**

Run: `npm test -- workspaceEndSessionFlow.test.ts`
Expected: PASS

### Task 7: 增加“恢复最初版本”入口与跨会话缓存

**Files:**
- Modify: `frontend/src/components/text-input/TextInputArea.vue`
- Modify: `frontend/src/components/text-input/clearInputDraftFlow.ts`
- Modify: `frontend/src/composables/useInputDraft.ts`
- Modify: `frontend/tests/clearInputDraftFlow.test.ts`
- Modify: `frontend/tests/useInputDraft.test.ts`

- [ ] **Step 1: 写失败测试，定义恢复入口规则**

至少覆盖：
- 仅当存在 `lastSessionInitialText` 时显示或启用“恢复最初版本”
- 点击后输入页文字回到该文本
- 该动作不自动恢复当前会话，也不自动更新音频

- [ ] **Step 2: 实现最近一轮最初版本缓存策略**

建议：
- 会话初始化成功时写入
- 结束当前会话后继续保留
- 下一轮成功初始化后覆盖为新的会话初始文本

- [ ] **Step 3: 补输入页说明与清空逻辑**

要求：
- “清空输入页文字”与“恢复最初版本”语义分离
- 如用户主动清空输入页，不要顺手销毁最近一轮最初版本，除非产品最终确认要这样做

- [ ] **Step 4: 运行测试确认通过**

Run: `npm test -- clearInputDraftFlow.test.ts useInputDraft.test.ts`
Expected: PASS

---

## Chunk 5: 发版前必须补的后端收口能力

> 这一块不是实现 Editor 草稿目标的第一阻塞项，但如果不上，会留下“运行中结束当前会话可能粗暴 reset”的结构性风险。建议在 P0 完成后立刻做。

### Task 8: 让结束当前会话具备安全中止语义

**Files:**
- Modify: `backend/app/services/edit_session_service.py`
- Modify: `backend/app/services/edit_session_runtime.py`
- Modify: `backend/app/services/render_job_service.py`
- Modify: `backend/app/api/routers/edit_session.py`
- Modify: `backend/tests/integration/test_edit_session_router.py`

- [ ] **Step 1: 写失败测试，锁定运行中结束会话的行为**

至少覆盖：
- 存在 active render job 时，结束会话不会直接粗暴清空 runtime
- job 会先收到取消/中止请求
- 前端能等到明确终态，再结束当前会话

- [ ] **Step 2: 改造删除/结束会话语义**

推荐目标：
- `delete_session()` 内部先请求取消 active job
- 等 job 进入安全终态后再清理 repository / asset / runtime

如果不做同步等待，至少要做到：
- 后续 worker 不会继续写入已删除会话的正式状态
- 前端能拿到可感知的 `aborting` / `cancel_requested` 过程

- [ ] **Step 3: 如有必要，补显式接口或文档说明**

候选：
- 保持 `DELETE /v1/edit-session`，但在描述中明确“安全结束当前会话”
- 或新增更准确的结束接口，保留旧接口兼容

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run --isolated --group dev pytest backend/tests/integration/test_edit_session_router.py -q`
Expected: PASS

### Task 9: 为“保留文字并结束会话”补跨会话成本提示

**Files:**
- Modify: `frontend/src/components/workspace/EndSessionDialog.vue`
- Modify: `docs/系统术语和对应.md`

- [ ] **Step 1: 在结束会话确认中加入提示**

要求：
- 明确“保留文字并结束会话”只是文本交接，不是保存当前音频进度
- 如果下次重新开始需要重新生成，应给出耗时/计费风险提示

- [ ] **Step 2: 如实现策略改变，同步术语文档**

要求：
- 不追加补丁说明
- 直接覆盖旧表述，使文档仍是最新系统状态

---

## P2 可选增强：降低重推理和跨会话成本

> 以下不是本轮必须项，但如果后面要进一步提升专业用户体验，可以在 P0/P1 稳定后评估。

### Task 10: 评估批量重推理与跨会话复用

**候选方向：**
- 后端新增批量应用待重推理片段的 job，减少前端串行调度复杂度
- 为“保留文字并结束会话后重新开始”建立可复用缓存，减少整篇重新生成概率
- 在 UI 上展示更清晰的局部重推理范围和预计耗时

- [ ] **Step 1: 先做技术调研，不直接实现**
- [ ] **Step 2: 如果决定立项，再单独出 spec 与实现计划**

---

## 验收标准

- Editor 本地修改后，输入页文字不发生变化。
- 页面刷新后，Workspace 仍能恢复本地工作副本与待重推理状态。
- 任一段重推理失败时，输入页文字不被错误推进到失败后的草稿文本。
- 重推理全部成功后，输入页文字会被新的 `applied_text` 回填。
- 结束当前会话且存在待重推理内容时，系统必须出现显式分支确认。
- 结束当前会话后，页面回到语音生成页的首次生成前状态。
- “保留文字并结束会话”不会伪装成“当前音频已更新”。
- 输入页存在“恢复最初版本”入口，且其来源是最近一轮会话初始文本。
- 发版前，运行中结束当前会话不会留下孤儿 render job 或状态锁死。

---

## 推荐实施顺序

1. 先做 Chunk 1-4，先把前端语义闭环做对。
2. 再做 Chunk 5，把“结束当前会话”的后端硬化补上。
3. P0/P1 都稳定后，再决定是否投入 P2 的成本优化。

---

## 建议验证命令

**前端定向回归**
- `npm test -- useInputDraft.test.ts useEditSessionSync.test.ts sessionHandoff.test.ts workspaceEndSessionFlow.test.ts mainActionButtonState.test.ts clearInputDraftFlow.test.ts useWorkspaceLightEdit.test.ts workspaceEditorHostLayoutMode.test.ts`

**前端全量**
- `npm test`
- `npm run build`

**后端定向**
- `uv run --isolated --group dev pytest backend/tests/integration/test_edit_session_router.py -q`

备注：提交由 wgh 手动执行，本计划不包含自动 commit 步骤。

---

Plan complete and saved to `docs/superpowers/plans/2026-04-09-editor-draft-session-lifecycle.md`. Ready to execute?
