# Phase 7 Export And Session Governance Redesign（归档）

> Archived: 2026-04-10
> Reason:
> - 文档要求导出弹窗输入相对路径 `target_dir`，与当前后端“只接受绝对路径”的实现冲突
> Current Entry:
> - `/llmdoc/guides/export-workflow.md`
> - `/llmdoc/architecture/asset-storage-preview-and-export.md`

## 背景

`devdoc/v0.0.2/frontend-development-final.md` 中原 Phase 7 方案已经落后于当前产品决策。

当前需要以新的交互边界重新定义 Phase 7：

- 删除 `WorkspaceView` 中的会话操作 card
- 顶栏 `AppNavbar.vue` 先恢复旧样式与旧逻辑，再最小化新增导出按钮
- 导出改为顶栏唯一入口，点击进入全模态导出窗口
- 导出与编辑、参数、推理解耦，只基于后端已持久化的会话版本与音频资产工作
- 文本输入页清空与语音合成页清空会话继续共同管理会话清理逻辑
- `转到文本输入页继续编辑` 与“提示重建会话”继续保留

## 目标

本次改动只收敛以下闭环：

1. 导出入口与导出弹窗重构
2. Workspace 页面治理入口下沉
3. 清空会话与 handoff 逻辑保留并重新安置
4. 删除已不再需要的恢复基线方案

不扩展到播放、参数解析、推理流程或新的页面设计。

## 设计结论

### 1. AppNavbar

`AppNavbar.vue` 先恢复到旧版样式和旧版基础逻辑，去掉本轮 Phase 7 引入的 card-era 占位和耦合实现。

在恢复旧 navbar 之后，只做一个最小增量：

- 仅在 `/workspace` 页面显示导出按钮
- 导出按钮点击后打开全模态导出窗口
- 导出按钮禁用规则：
  - render job 运行中禁用
  - `paused` 不禁用
- 顶栏仍可显示轻量运行态提示，但不再承担 Workspace 页面治理入口

### 2. Workspace 页面

`WorkspaceView.vue` 删除整个会话操作 card。

因此以下入口都不再出现在页面级 card 中：

- 导出
- 恢复基线
- 清空会话
- 转到文本输入页继续编辑

其中：

- `恢复基线` 整体从当前版本移除
- `清空会话` 与 `转到文本输入页继续编辑` 下沉到正文区顶部次级按钮区

页面重新回到更单纯的结构：

- 左栏参数
- 右侧正文/波形/底部主控制

### 3. 导出中心

`ExportDialog.vue` 改为真正的全模态导出中心。

职责只包括：

- 选择导出类型：整条导出 / 分段导出
- 输入相对路径 `target_dir`
- 展示 export job 进度
- 展示导出结果

导出的事实源固定为后端当前已持久化版本：

- 使用 `snapshot.document_version`
- 不读取编辑缓冲
- 不读取参数草稿
- 不尝试带着未提交本地状态导出

也就是说，导出始终只针对后端当前可导出的正式版本。

### 4. 导出门禁

导出功能必须满足以下门禁：

- 没有 `snapshot.document_version` 时不可导出
- render job 运行中不可导出
- `paused` 状态允许导出

建议统一为：

- 禁用导出：`queued`、`preparing`、`rendering`、`composing`、`committing`、`pause_requested`、`cancel_requested`
- 允许导出：`paused`、`completed`、`failed`、`cancelled_partial`、无 job

这条规则同时作用于：

- 顶栏导出按钮
- 导出弹窗内部提交按钮

### 5. 清空会话

清空会话保留两条路径，并继续共享同一组后端清理语义：

#### 5.1 文本输入页清空

沿用 `TextInputArea.vue` + `clearInputDraftFlow.ts`：

- 先确认是否清空输入稿
- 若会话存在内容，再询问是否同步清理会话
- 用户选择同步时，调用 `useEditSession.clearSession()`

#### 5.2 语音合成页清空

在 `WorkspaceEditorHost.vue` 顶部右上角次级按钮区保留“清空会话”入口。

其语义固定为：

- 清空当前 edit-session 的结果、参数状态、运行态与时间线
- 不清空 `InputDraft.text`
- 清空后用户仍可基于原输入文本重新初始化并全量推理

这不是“清空输入稿”，而是“清空会话”。

### 6. Handoff 保留

以下 handoff 逻辑继续保留：

#### 6.1 返回文本输入继续编辑

- 从当前 session head 拼接正文
- 回填到 `InputDraft`
- 跳转到 `/text-input`

#### 6.2 输入稿更新后提示重建会话

- 当 `InputDraft` 版本领先于当前会话来源版本时
- 用户进入 `/workspace` 后仍提示是否用当前输入稿重建会话

这两条逻辑保留，但 UI 入口不再依附于页面级治理 card。

### 7. 状态边界

`render` 与 `export` 可以共享“运行态观测”，但不能共享“业务事实源”。

- `render` 关心当前推理运行态
- `export` 关心当前已持久化 `document_version`

因此：

- `useRuntimeState` 可以继续跟踪 export job 与 render job
- `ExportDialog` 不能依赖本地编辑或参数草稿来决定导出内容

### 8. 删除范围

本次应删除或停用的内容：

- `WorkspaceView.vue` 中会话操作 card
- `BaselineRestoreDialog.vue` 及其接线
- 与 card 强绑定的页面级治理按钮

保留但重挂位置的内容：

- `ExportDialog.vue`
- `ResetSessionDialog.vue`
- `转到文本输入页继续编辑`
- 输入稿版本领先时的重建提示

### 9. 测试要求

至少覆盖以下回归：

1. `AppNavbar` 恢复旧逻辑后，在 `/workspace` 显示导出按钮
2. render job 运行中导出按钮禁用；`paused` 不禁用
3. `WorkspaceView` 不再渲染会话操作 card
4. `WorkspaceEditorHost` 保留“清空会话”和“转到文本输入页继续编辑”
5. 导出只依赖 `snapshot.document_version`
6. 文本输入页清空时的“同步清理会话”逻辑不回退

## 实现边界

本 spec 只服务当前版本的导出与会话治理重构，不扩展为新的路由设计、导出历史管理或多版本导出中心。

如后续需要导出历史、导出队列管理或基线恢复回归，应另开独立设计。
