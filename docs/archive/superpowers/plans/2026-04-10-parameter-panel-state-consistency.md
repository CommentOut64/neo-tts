# Parameter Panel State Consistency Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不改动后端 profile/binding 继承与持久化模型的前提下，消除工作区参数栏“参数短暂丢失、回退默认值、稍后又恢复”的失配现象。

**Architecture:** 保留现有后端 session/group/segment 参数解析链，只在前端做一次最小闭环重构：把 edit-session 正式状态刷新改成原子 bundle 提交，再让参数栏显式识别 `resolving` 状态并在同 scope 下保留最后一次稳定值。UI 不再把“未知/同步中”误渲染成业务默认值，而是显示同步态或禁用态。

**Tech Stack:** Vue 3、TypeScript、Element Plus、Vitest、现有 edit-session / render profile / voice binding / parameter panel 体系

**提交约束:** 本计划不包含自动提交步骤；代码提交由 `wgh` 手动执行。

---

## 为什么这是最小范围重构而不是继续打补丁

当前问题不是单个字段没存住，而是前端存在明确的一致性窗口：

- `snapshot`、`timeline`、`segments`、`groups`、`renderProfiles`、`voiceBindings` 分批刷新，参数栏却实时解引用。
- 后端 patch/commit 会创建新的 profile/binding 实体并切换 id，因此前端必须同时拿到“新 id + 新实体列表”才能稳定解析。
- [RuntimeInferenceSettingsPanel.vue](F:/neo-tts/frontend/src/components/workspace/parameter-panel/RuntimeInferenceSettingsPanel.vue) 把 `null` 直接显示成默认数值，放大了同步问题。

因此本计划选择 **B. 局部重构**，但范围只限定在：

- `useEditSession.ts` 的正式状态刷新闭环
- `useParameterPanel.ts` 的参数解析/稳定值闭环
- 参数栏组件的“同步中/未知”显示语义
- 少量调用点替换为原子刷新接口

不包含：

- 后端 `RenderProfile` / `VoiceBinding` 持久化重做
- 参数继承规则重写
- 全量前端 store 重构

---

## 文件结构

**前端正式状态刷新核心**
- Modify: `frontend/src/composables/useEditSession.ts`
  引入正式状态 bundle 加载、原子提交、refresh epoch、防止旧请求晚到覆盖新状态。

**参数栏解析与稳定值**
- Modify: `frontend/src/composables/useParameterPanel.ts`
  引入参数解析状态、scope key、最后一次稳定解析值缓存、提交后统一走原子刷新。
- Modify: `frontend/src/components/workspace/parameter-panel/resolveEffectiveParameters.ts`
  保持纯函数定位，但补最小辅助能力，避免调用方把“空结果”误当成“默认值”。

**参数栏 UI**
- Modify: `frontend/src/components/workspace/parameter-panel/SharedParameterScopePanel.vue`
  展示同步态/缺失态，避免在资源未齐时继续展示可编辑但不可信的值。
- Modify: `frontend/src/components/workspace/parameter-panel/RuntimeInferenceSettingsPanel.vue`
  去掉 `null => 业务默认值` 的展示语义，增加 `status/disabled` 支持。
- Modify: `frontend/src/components/ParameterSlider.vue`
  支持禁用态，避免同步中仍可误编辑。

**调用点**
- Modify: `frontend/src/components/workspace/MainActionButton.vue`
  把参数相关刷新路径改为 `refreshFormalSessionState()`。
- Modify: `frontend/src/composables/useWorkspaceProcessing.ts`
  核对返回值契约，保持与新的原子刷新接口一致。

**测试**
- Create: `frontend/tests/useEditSession.formal-state-bundle.test.ts`
- Modify: `frontend/tests/useEditSessionSync.test.ts`
- Modify: `frontend/tests/useParameterPanel.test.ts`
- Modify: `frontend/tests/resolveEffectiveParameters.test.ts`
- Create: `frontend/tests/runtimeInferenceSettingsPanel.test.ts`
- Modify: `frontend/tests/useWorkspaceProcessing.test.ts`

**文档**
- Modify: `llmdoc/architecture/render-config-resolution.md`
  增补“前端消费约束”段落，说明参数栏必须等待 formal state bundle 一致后再解引用。

---

## Chunk 1: 把正式会话状态刷新收口成原子 bundle

### Task 1: 用测试冻结“原子刷新”目标行为

**Files:**
- Create: `frontend/tests/useEditSession.formal-state-bundle.test.ts`
- Modify: `frontend/tests/useEditSessionSync.test.ts`

- [ ] **Step 1: 写失败测试，覆盖正式状态 bundle 行为**

至少覆盖：
- `refreshFormalSessionState()` 在 `snapshot/timeline/resources` 全部准备好之前，不向公开 refs 暴露半刷新状态。
- 同一轮刷新里，`snapshot.default_render_profile_id` 更新时，`renderProfiles` 与 `voiceBindings` 也必须同步切换到同 epoch。
- 新一轮刷新发起后，旧一轮异步响应晚到不会覆盖新状态。

- [ ] **Step 2: 运行测试确认失败**

Run:
```powershell
npm test -- useEditSession.formal-state-bundle.test.ts useEditSessionSync.test.ts
```

Expected:
- FAIL，当前实现会先写 `snapshot/timeline`，再异步写资源数组。

- [ ] **Step 3: 在 `useEditSession.ts` 新增内部 bundle 类型**

要求新增最小内部结构：
- `FormalSessionBundle`
- `FormalStateStatus = 'idle' | 'refreshing' | 'ready' | 'error'`
- `formalStateEpoch`

bundle 至少包含：
- `snapshot`
- `timeline`
- `segments`
- `edges`
- `groups`
- `renderProfiles`
- `voiceBindings`

- [ ] **Step 4: 实现内部加载/应用双阶段**

要求：
- 新增内部 `loadFormalSessionBundle()`，只返回局部变量，不直接改公开 refs。
- 新增内部 `applyFormalSessionBundle(bundle, epoch)`，只在 epoch 仍为最新时一次性落盘到 refs。
- 公开 refs 保持现有接口不变，避免大面积改调用方。

- [ ] **Step 5: 收口 ready 态刷新入口**

要求：
- `discoverSession()` 在 `ready` 路径下不要再先 `getSnapshot()` 后 `refreshTimeline()`。
- `refreshFormalSessionState()` 成为参数栏依赖的唯一正式刷新入口。
- `refreshSnapshot()` 以后只保留轻量探测语义，不能再承担正式参数刷新职责。

- [ ] **Step 6: 运行测试确认通过**

Run:
```powershell
npm test -- useEditSession.formal-state-bundle.test.ts useEditSessionSync.test.ts
```

Expected:
- PASS

### Task 2: 暴露正式状态同步信号，供参数栏消费

**Files:**
- Modify: `frontend/src/composables/useEditSession.ts`
- Modify: `frontend/tests/useEditSession.formal-state-bundle.test.ts`

- [ ] **Step 1: 暴露只读同步状态**

至少新增：
- `formalStateStatus`
- `isFormalStateRefreshing`
- `formalStateEpoch`

- [ ] **Step 2: 把 `sessionResourcesLoaded` 对齐为 bundle 级语义**

要求：
- 仅在本轮 `segments/edges/groups/renderProfiles/voiceBindings` 全部到齐后才标记为已加载。
- 非 `ready` 状态下清空逻辑仍然保留，但也必须通过统一应用路径执行。

- [ ] **Step 3: 运行类型检查**

Run:
```powershell
npx vue-tsc --noEmit
```

Expected:
- PASS

---

## Chunk 2: 让参数栏显式区分 ready / resolving / unresolved

### Task 3: 用测试冻结“稳定值 + resolving”行为

**Files:**
- Modify: `frontend/tests/useParameterPanel.test.ts`
- Modify: `frontend/tests/resolveEffectiveParameters.test.ts`

- [ ] **Step 1: 写失败测试，覆盖同 scope 刷新时的稳定值行为**

至少覆盖：
- 当 formal state 正在刷新且 scope 未变化时，参数栏继续显示最后一次稳定解析值。
- 当刷新完成后，参数栏切换到新值。

- [ ] **Step 2: 写失败测试，覆盖 scope 改变时的 resolving 行为**

至少覆盖：
- 当 scope 从 `session` 切到 `segment/batch/edge` 且新 scope 数据未齐时，不显示旧 scope 的稳定值。
- 此时参数栏暴露 `resolving` 状态，而不是空值或默认值。

- [ ] **Step 3: 写失败测试，覆盖“实体缺失”和“同步中”语义区分**

至少覆盖：
- 资源未齐时是 `resolving`
- 资源已齐但找不到引用实体时是 `unresolved`

- [ ] **Step 4: 运行测试确认失败**

Run:
```powershell
npm test -- useParameterPanel.test.ts resolveEffectiveParameters.test.ts
```

Expected:
- FAIL，当前实现无法区分 `resolving` 与 `ready/null`。

- [ ] **Step 5: 在 `useParameterPanel.ts` 新增解析状态模型**

至少新增：
- `scopeKey`
- `resolvedStatus = 'ready' | 'resolving' | 'unresolved'`
- `lastStableScopeKey`
- `lastStableResolvedValues`

- [ ] **Step 6: 保持 resolver 纯函数，不把加载逻辑塞进 resolver**

要求：
- `resolveEffectiveParameters()` 仍然只负责“给定输入 -> 解析结果”。
- 是否可相信这次结果，由 `useParameterPanel.ts` 结合 `formalStateStatus/segmentsLoaded/sessionResourcesLoaded` 判断。

- [ ] **Step 7: 实现稳定值策略**

规则固定为：
- `same scope + resolving`：显示最后一次稳定值
- `different scope + resolving`：显示同步中，不复用旧值
- `ready + 可解引用`：更新稳定值
- `ready + 不可解引用`：标记 `unresolved`

- [ ] **Step 8: 运行测试确认通过**

Run:
```powershell
npm test -- useParameterPanel.test.ts resolveEffectiveParameters.test.ts
```

Expected:
- PASS

### Task 4: 把参数比较逻辑从“当前裸值”改成“可信解析值”

**Files:**
- Modify: `frontend/src/composables/useParameterPanel.ts`
- Modify: `frontend/tests/useParameterPanel.test.ts`

- [ ] **Step 1: 修正 `updateRenderProfileField()` / `updateVoiceBindingField()` 的基线**

要求：
- dirty 比较只能和“当前可信的已解析值”比。
- `resolving` 期间不得因为临时 `null` 导致 dirty 误判。

- [ ] **Step 2: 修正 `submitDraft()` 后的刷新路径**

要求：
- 非 edge 参数提交完成后，统一调用 `editSession.refreshFormalSessionState()`。
- 删除 `refreshSnapshot() + refreshTimeline()` 的顺序刷新用法。

- [ ] **Step 3: 运行测试确认通过**

Run:
```powershell
npm test -- useParameterPanel.test.ts
```

Expected:
- PASS

---

## Chunk 3: 把 UI 从“默认值伪装”改成“同步态/未知态”

### Task 5: 改掉 RuntimeInferenceSettingsPanel 的错误 fallback

**Files:**
- Modify: `frontend/src/components/workspace/parameter-panel/RuntimeInferenceSettingsPanel.vue`
- Modify: `frontend/src/components/ParameterSlider.vue`
- Create: `frontend/tests/runtimeInferenceSettingsPanel.test.ts`

- [ ] **Step 1: 写失败测试，覆盖 `null` 不再显示业务默认值**

至少覆盖：
- `status = resolving` 时不显示 `1 / 15 / 0.35` 这类默认业务值。
- `status = unresolved` 时显示明确文案或占位态。
- `status = ready` 时继续正常显示数值。

- [ ] **Step 2: 给 `RuntimeInferenceSettingsPanel.vue` 增加显示状态 props**

至少新增：
- `status`
- `disabled`

规则：
- `resolving`：显示“同步中”，禁用输入
- `unresolved`：显示“当前配置暂不可解析”，禁用输入
- `ready`：正常显示并允许编辑

- [ ] **Step 3: 给 `ParameterSlider.vue` 增加禁用支持**

要求：
- 透传到 `el-slider` / `el-input-number`
- 禁用时不发出更新事件

- [ ] **Step 4: 运行测试确认通过**

Run:
```powershell
npm test -- runtimeInferenceSettingsPanel.test.ts
```

Expected:
- PASS

### Task 6: 让 SharedParameterScopePanel 显示一致的同步提示

**Files:**
- Modify: `frontend/src/components/workspace/parameter-panel/SharedParameterScopePanel.vue`
- Modify: `frontend/tests/useParameterPanel.test.ts`

- [ ] **Step 1: 接入 `resolvedStatus`**

要求：
- 在 `resolving` 时显示顶部提示条，例如“正在同步最新参数…”
- 在 `unresolved` 时显示“当前配置引用不完整，请刷新正式状态”

- [ ] **Step 2: 同步禁用音色、参考音频、参考语言输入**

要求：
- 避免同步窗口中用户继续基于错误基线编辑。
- dirty 草稿仍保留，不在 UI 上被清空。

- [ ] **Step 3: 运行测试确认通过**

Run:
```powershell
npm test -- useParameterPanel.test.ts runtimeInferenceSettingsPanel.test.ts
```

Expected:
- PASS

---

## Chunk 4: 替换调用点并补回归验证

### Task 7: 统一所有参数相关调用点到原子刷新接口

**Files:**
- Modify: `frontend/src/components/workspace/MainActionButton.vue`
- Modify: `frontend/src/composables/useWorkspaceProcessing.ts`
- Modify: `frontend/src/composables/useParameterPanel.ts`
- Modify: `frontend/tests/useWorkspaceProcessing.test.ts`

- [ ] **Step 1: 替换顺序刷新调用**

要求：
- 参数提交后的刷新统一走 `refreshFormalSessionState()`
- `MainActionButton.vue` 中重推理成功后的 session refresh 也统一走该接口

- [ ] **Step 2: 校对 `useWorkspaceProcessing.ts` 对 bundle 返回值的依赖**

要求：
- 确保它仍然拿到完整的 `snapshot/timeline/edges`
- 不依赖中间态 refs

- [ ] **Step 3: 运行回归测试**

Run:
```powershell
npm test -- useWorkspaceProcessing.test.ts useParameterPanel.test.ts useEditSession.formal-state-bundle.test.ts
```

Expected:
- PASS

### Task 8: 更新文档并完成最终验证

**Files:**
- Modify: `llmdoc/architecture/render-config-resolution.md`

- [ ] **Step 1: 更新文档中的前端消费约束**

要求新增一小节，说明：
- 参数栏消费的是已提交 formal state，不是初始化缓存
- 前端必须等待 `snapshot/timeline/resources` bundle 一致后再解析
- `resolving` 期间不得把未知状态渲染成业务默认值

- [ ] **Step 2: 运行定向测试**

Run:
```powershell
npm test -- useEditSession.formal-state-bundle.test.ts useEditSessionSync.test.ts useParameterPanel.test.ts resolveEffectiveParameters.test.ts runtimeInferenceSettingsPanel.test.ts useWorkspaceProcessing.test.ts
```

Expected:
- PASS

- [ ] **Step 3: 运行类型检查**

Run:
```powershell
npx vue-tsc --noEmit
```

Expected:
- PASS

- [ ] **Step 4: 运行生产构建**

Run:
```powershell
$env:GOMAXPROCS='1'
npm run build
```

Expected:
- PASS
- 允许保留 chunk size warning，但不得出现类型错误、构建中断或参数栏相关测试失败

---

## 验收标准

完成后必须满足以下可观察结果：

- 会话级、段级、批量参数在刷新正式状态时不再短暂变空或回到默认数值。
- 同一 scope 刷新时，参数栏保持最后一次稳定值，直到新值到位。
- 切换到新 scope 且数据未齐时，参数栏显示“同步中”，而不是旧值或默认值。
- 参数提交后，前端所有参数相关刷新路径都统一走 `refreshFormalSessionState()`。
- `RuntimeInferenceSettingsPanel` 不再把 `null` 渲染成业务默认参数。
- 文档与实现一致。

---

Plan complete and saved to `docs/superpowers/plans/2026-04-10-parameter-panel-state-consistency.md`. Ready to execute?
