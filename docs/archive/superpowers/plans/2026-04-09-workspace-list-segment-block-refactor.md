# Workspace List SegmentBlock Refactor Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 Workspace Editor 的列表式从“paragraph + decoration + widget 占位”重构为“`segmentBlock` + NodeView 外壳”，彻底消除编辑时段间错位，同时尽可能保留现有列表式样式、布局和交互观感。

**Architecture:** 保留 `sourceDoc` 作为前端唯一业务事实源，组合视图继续沿用现有 `segmentAnchor + pauseBoundary + composition projection`。列表式改成专用块节点 `segmentBlock`，由 NodeView 提供稳定 gutter 和内容区，行号/拖拽头退出正文内容模型；列表式基础布局不再依赖 `renderMap`、`segmentDecoration` 或 widget decoration。列表式 normalizer 改为按 `segmentBlock.attrs.segmentId` 回写，旧的 list-only decoration/renderMap 路径整体删除。

**Tech Stack:** Vue 3、TypeScript、TipTap、@tiptap/vue-3 NodeView、Vitest、Scoped CSS、Tailwind utility class、现有 Workspace Editor 状态机

---

> **Repo Rule:** 仓库规则要求 commit 由 wgh 手动执行，本计划不包含自动 commit 步骤。

## 为什么这次必须做局部重构，而不是继续打补丁

当前列表式的基础盒模型依赖：

- `segmentDecoration.ts` 给 paragraph 打 `segment-line`
- `WorkspaceEditorHost.vue` 中 `p.segment-line` 的 `padding-left`
- `listReorderHandleDecoration.ts` 插入 widget handle / 行号
- `extractRenderMapFromDoc.ts` 基于绝对坐标提取 `segmentBlockRanges`

这已经满足结构性问题的触发条件：

- 编辑态文档真实结构变化后，列表式基础布局仍依赖旧坐标和外部 decoration
- 同一段职责分散在 Host、builder、renderMap、decoration、widget 五处
- 继续补丁只会增加更多 special case，并继续放大列表/组合双布局的耦合

因此本计划选择 **B. 局部重构**，但范围严格限制在：

- 列表式 projection
- 列表式编辑态承载结构
- 列表式 normalizer
- 列表式拖拽 DOM 命中入口
- 与上述改动直接相关的 Host 编排和测试

不包含：

- 后端接口改造
- 组合视图重写
- `pauseBoundary` NodeView 语义重做
- 整个 `WorkspaceEditorHost` 拆组件重写

---

## 硬约束

### 1. 视觉兼容是硬要求

本次重构必须尽可能保留现有列表式视觉结果，优先保留：

- gutter 宽度
- 行号位置
- 拖拽头位置与 hover 感受
- 段行高、段间距、圆角、背景、边框、阴影
- dirty / selected / playing / reorder 相关颜色语义
- pauseBoundary 胶囊的基线与尺寸

允许变化的是：

- 内部 DOM 结构
- TipTap extension 组织方式
- 列表式 normalizer / renderMap / decoration 的实现责任

### 2. 删除旧实现，不留双轨兼容壳

完成后必须删除：

- `frontend/src/components/workspace/workspace-editor/listReorderHandleDecoration.ts`
- 列表式对 `segmentBlockRanges` 的依赖
- 列表式基础布局对 `.segment-line + padding-left` 的依赖
- 列表式基于 widget decoration 的拖拽 handle 命中路径
- 列表式通过 `segmentAnchor` 聚合文本的 normalizer 路径

如果有新旧两套并存，只算半完成。

### 3. 组合视图保持现状

本轮只重构列表式：

- 组合视图 doc builder 保持现有结构
- `segmentAnchorMark` 继续保留给组合视图使用
- 组合视图 `extractRenderMapFromDoc()` 路径保留
- 列表式与组合视图只共享 `sourceDoc`、`pauseBoundary` 和少量公共工具

---

## 文件结构

**列表式 schema / NodeView**
- Create: `frontend/src/components/workspace/workspace-editor/list/segmentBlock.ts`
- Create: `frontend/src/components/workspace/workspace-editor/list/SegmentBlockNodeView.vue`

**列表式 builder / normalizer**
- Create: `frontend/src/components/workspace/workspace-editor/list/buildListSegmentBlockDocument.ts`
- Create: `frontend/src/components/workspace/workspace-editor/list/normalizeListViewDocToSourceDoc.ts`
- Modify: `frontend/src/components/workspace/workspace-editor/documentModel.ts`
- Modify: `frontend/src/components/workspace/workspace-editor/buildListLayoutDocument.ts`
- Modify: `frontend/src/components/workspace/workspace-editor/sourceDocNormalizer.ts`

**Editor extension 装配与状态收缩**
- Modify: `frontend/src/components/workspace/workspace-editor/buildEditorExtensions.ts`
- Modify: `frontend/src/components/workspace/workspace-editor/segmentDecoration.ts`
- Modify: `frontend/src/components/workspace/workspace-editor/extractRenderMapFromDoc.ts`
- Modify: `frontend/src/components/workspace/workspace-editor/layoutTypes.ts`
- Delete: `frontend/src/components/workspace/workspace-editor/listReorderHandleDecoration.ts`

**Host 与拖拽入口**
- Modify: `frontend/src/components/workspace/WorkspaceEditorHost.vue`
- Modify: `frontend/src/composables/useWorkspaceListReorder.ts`
- Modify: `frontend/src/components/workspace/workspace-editor/resolveSegmentBlockElement.ts`
- Modify: `frontend/src/components/workspace/workspace-editor/workspaceEditorHostModel.ts`

**测试**
- Modify: `frontend/tests/workspaceEditorHostLayoutMode.test.ts`
- Modify: `frontend/tests/workspaceEditorDecoration.test.ts`
- Create: `frontend/tests/workspaceEditorListSegmentBlock.test.ts`
- Create: `frontend/tests/workspaceListViewNormalizer.test.ts`

**文档**
- Modify: `llmdoc/` 中与 Workspace Editor 列表式结构直接相关的文档；若当前无对应文档，则新增一篇最小架构说明并同步到索引

---

## Chunk 1: 用测试冻结“重构后不变”和“必须删除”的边界

### Task 1: 先锁定列表式重构后的结构目标和视觉兼容约束

**Files:**
- Create: `frontend/tests/workspaceEditorListSegmentBlock.test.ts`
- Modify: `frontend/tests/workspaceEditorHostLayoutMode.test.ts`
- Modify: `frontend/tests/workspaceEditorDecoration.test.ts`

- [ ] **Step 1: 新增失败测试，约束列表式 builder 产出 `segmentBlock` 而不是 paragraph**

测试至少覆盖：
- 列表式文档中的每一段根节点类型为 `segmentBlock`
- `segmentBlock.attrs.segmentId` 与 `semanticDocument.segmentOrder` 一一对应
- `pauseBoundary` 仍位于每个段块内容尾部
- 组合视图 builder 行为不受影响

- [ ] **Step 2: 新增失败测试，约束列表式基础布局不再依赖旧的 widget / node decoration 路径**

断言至少覆盖源码不再包含：
- `ListReorderHandleDecoration`
- `segmentBlockRanges`
- 列表式 `.segment-line` 作为基础盒模型入口

并断言源码必须包含：
- `segmentBlock`
- `SegmentBlockNodeView`
- 列表式专用 normalizer 入口

- [ ] **Step 3: 新增失败测试，锁定视觉兼容约束**

断言至少覆盖：
- gutter 宽度仍然由稳定 DOM 结构承担，而不是靠 `padding-left`
- 行号/拖拽头位于 NodeView 左列，而不是 widget decoration
- 编辑态允许隐藏 gutter 内容，但不能移除列表式结构容器

- [ ] **Step 4: 运行测试确认失败**

Run: `npm run test -- workspaceEditorListSegmentBlock.test.ts workspaceEditorHostLayoutMode.test.ts workspaceEditorDecoration.test.ts`
Expected: FAIL，当前实现仍是 paragraph + decoration + widget 路径

### Task 2: 先冻结列表式回写契约，避免重构时误伤 `sourceDoc`

**Files:**
- Create: `frontend/tests/workspaceListViewNormalizer.test.ts`
- Modify: `frontend/src/components/workspace/workspace-editor/sourceDocNormalizer.ts`

- [ ] **Step 1: 新增失败测试，约束列表式回写改为按 `segmentBlock.attrs.segmentId` 提取**

测试至少覆盖：
- 能从 `segmentBlock` 顺序提取 segment 文本
- 即使文本中间连续输入字符，后续块也不会丢失映射
- 删除/篡改 `segmentId` 会明确报错
- 组合视图仍然按 `segmentAnchor` 聚合

- [ ] **Step 2: 运行测试确认失败**

Run: `npm run test -- workspaceListViewNormalizer.test.ts`
Expected: FAIL，当前 normalizer 仍依赖 `segmentAnchor`

---

## Chunk 2: 引入 `segmentBlock` 节点和 NodeView，建立稳定列表结构

### Task 3: 新建列表式块节点 `segmentBlock`

**Files:**
- Create: `frontend/src/components/workspace/workspace-editor/list/segmentBlock.ts`
- Create: `frontend/src/components/workspace/workspace-editor/list/SegmentBlockNodeView.vue`
- Modify: `frontend/src/components/workspace/workspace-editor/buildEditorExtensions.ts`

- [ ] **Step 1: 定义 `segmentBlock` TipTap 节点**

要求：
- 节点名固定为 `segmentBlock`
- group 为 block
- attrs 至少包含 `segmentId`
- content 支持 `inline*`
- 允许内部继续承载 `text` 与 `pauseBoundary`
- 使用 `VueNodeViewRenderer(SegmentBlockNodeView)`

- [ ] **Step 2: 编写 `SegmentBlockNodeView.vue`**

结构必须固定为两列：
- 左列 `segment-block-gutter`
- 右列 `segment-block-content`

要求：
- gutter DOM 提供 `data-segment-block-handle`
- 根节点提供 `data-segment-id`
- 根节点提供稳定 class，供 selected/dirty/playing/reorder 状态落样式
- `contentDOM` 只能挂在右列
- gutter 内容可按 `isEditing` 切换显示/隐藏，但列宽必须始终保留

- [ ] **Step 3: 把 `segmentBlock` 接进 `buildEditorExtensions.ts`**

要求：
- 列表式与组合视图共享同一个编辑器实例时，`segmentBlock` 扩展必须始终注册
- 删除对 `ListReorderHandleDecoration` 的注册

- [ ] **Step 4: 运行测试确认通过**

Run: `npm run test -- workspaceEditorListSegmentBlock.test.ts`
Expected: PASS，列表式结构已切到 `segmentBlock`

### Task 4: 把列表式 builder 从 paragraph 改成 `segmentBlock`

**Files:**
- Modify: `frontend/src/components/workspace/workspace-editor/buildListLayoutDocument.ts`
- Create: `frontend/src/components/workspace/workspace-editor/list/buildListSegmentBlockDocument.ts`
- Modify: `frontend/src/components/workspace/workspace-editor/documentModel.ts`

- [ ] **Step 1: 提取新的列表式 builder**

要求：
- 让 `buildListSegmentBlockDocument()` 负责生成列表式 doc
- 每个 segment 输出一个 `segmentBlock`
- `segmentBlock` 内部正文继续沿用现有文本与 `pauseBoundary`
- 空态仍然返回最小可渲染 doc

- [ ] **Step 2: 收口旧 `buildListLayoutDocument.ts`**

允许两种方式二选一：
- 直接把实现迁到新文件并删除旧文件
- 或让旧文件只做一层转发，随后在同一任务末尾删掉旧壳

最终要求：
- 仓库里只保留一份列表式 builder 真源

- [ ] **Step 3: 运行测试确认通过**

Run: `npm run test -- workspaceEditorListSegmentBlock.test.ts`
Expected: PASS，列表式投影稳定输出 `segmentBlock`

---

## Chunk 3: 把列表式基础布局职责从 decoration/renderMap 挪回结构层

### Task 5: 收缩 `segmentDecoration`，让它退出列表式基础盒模型职责

**Files:**
- Modify: `frontend/src/components/workspace/workspace-editor/segmentDecoration.ts`
- Modify: `frontend/src/components/workspace/workspace-editor/layoutTypes.ts`
- Modify: `frontend/tests/workspaceEditorDecoration.test.ts`

- [ ] **Step 1: 写失败测试，约束列表式 decoration 只保留视觉状态，不再定义基础结构**

测试至少覆盖：
- 列表式不再通过 node decoration 提供 `segment-line` 作为基础布局 class
- 列表式状态类改为挂在 `segmentBlock` 根节点上，或由 NodeView 根据 storage 状态自行计算
- 组合视图 decoration 行为保持不变

- [ ] **Step 2: 修改 `segmentDecoration.ts`**

要求：
- 组合视图继续走当前 `segmentRanges -> Decoration.inline`
- 列表式不再依赖 `segmentBlockRanges`
- 如果列表式仍需 decoration，只允许承担颜色/状态 class，不允许承担结构 class

- [ ] **Step 3: 修改 `layoutTypes.ts`**

要求：
- 删除仅服务旧列表式的 `SegmentBlockRange`
- 删除 `WorkspaceRenderMap.segmentBlockRanges`
- 调整相关类型引用

- [ ] **Step 4: 运行测试确认通过**

Run: `npm run test -- workspaceEditorDecoration.test.ts`
Expected: PASS，组合视图未回归，列表式不再依赖旧结构 decoration

### Task 6: 精简 `extractRenderMapFromDoc()`，移除列表式 block 范围提取

**Files:**
- Modify: `frontend/src/components/workspace/workspace-editor/extractRenderMapFromDoc.ts`
- Modify: `frontend/tests/workspaceEditorDecoration.test.ts`

- [ ] **Step 1: 删除列表式 paragraph 扫描逻辑**

要求：
- 删除 `collectParagraphSegmentIds()`
- 删除列表式 `segmentBlockRanges` 提取
- `extractRenderMapFromDoc()` 只保留组合视图真正需要的 `segmentRanges` 和 `edgeAnchors`

- [ ] **Step 2: 清理相关调用点**

要求：
- 所有读取 `renderMap.segmentBlockRanges` 的调用点必须在本任务结束前清零
- 不能保留死字段或兼容空数组占位

- [ ] **Step 3: 运行测试确认通过**

Run: `npm run test -- workspaceEditorDecoration.test.ts`
Expected: PASS，旧列表式 renderMap 依赖已删除

---

## Chunk 4: 重写列表式回写和拖拽入口，删除 widget 路径

### Task 7: 把 normalizer 拆成列表式 / 组合视图双路径

**Files:**
- Create: `frontend/src/components/workspace/workspace-editor/list/normalizeListViewDocToSourceDoc.ts`
- Modify: `frontend/src/components/workspace/workspace-editor/sourceDocNormalizer.ts`
- Modify: `frontend/tests/workspaceListViewNormalizer.test.ts`

- [ ] **Step 1: 新建列表式 normalizer**

要求：
- 从 `segmentBlock` 根节点读取 `segmentId`
- 逐块聚合文本
- 遇到顺序、缺失、重复、非法节点时明确抛错
- 输出仍回到统一的 `buildWorkspaceSourceDoc(...)`

- [ ] **Step 2: 把旧 `sourceDocNormalizer.ts` 改成调度层**

要求：
- `layoutMode === "list"` 时走新 normalizer
- `layoutMode === "composition"` 时保留现有 `segmentAnchor` 逻辑
- 列表式路径中删除对 `segmentAnchor` 的依赖

- [ ] **Step 3: 运行测试确认通过**

Run: `npm run test -- workspaceListViewNormalizer.test.ts`
Expected: PASS，列表式与组合视图回写都能稳定工作

### Task 8: 把拖拽命中入口改到 `segmentBlock` NodeView gutter，并删除 widget decoration

**Files:**
- Modify: `frontend/src/composables/useWorkspaceListReorder.ts`
- Modify: `frontend/src/components/workspace/workspace-editor/resolveSegmentBlockElement.ts`
- Modify: `frontend/src/components/workspace/WorkspaceEditorHost.vue`
- Delete: `frontend/src/components/workspace/workspace-editor/listReorderHandleDecoration.ts`
- Modify: `frontend/tests/workspaceEditorHostLayoutMode.test.ts`

- [ ] **Step 1: 改写命中入口**

要求：
- handle 命中改成 `closest('[data-segment-block-handle]')`
- 段命中改成 `closest('[data-segment-id]')`
- `resolveSegmentBlockElement()` 改为命中新的 `segmentBlock` 根节点 DOM

- [ ] **Step 2: 删除 `listReorderHandleDecoration.ts`**

要求：
- 删除文件
- 删除所有 import / storage / extension 注册 / 测试引用
- 不允许留下“已废弃但暂时保留”的兼容壳

- [ ] **Step 3: 调整 `WorkspaceEditorHost.vue`**

要求：
- 不再向 editor storage 注入 `listReorderHandleDecoration.state`
- 拖拽 ghost、`displayOrder`、`reorderDraft` 逻辑保留
- 编辑态禁止重排和切布局的规则保持不变

- [ ] **Step 4: 运行测试确认通过**

Run: `npm run test -- workspaceEditorHostLayoutMode.test.ts workspaceEditorListSegmentBlock.test.ts`
Expected: PASS，拖拽入口已切到 NodeView DOM，旧 widget 路径已删除

---

## Chunk 5: 视觉对齐回归，确保“底层重构但外观尽量不变”

### Task 9: 把现有列表式 CSS 迁到 `segmentBlock` DOM，并做最小改写

**Files:**
- Modify: `frontend/src/components/workspace/WorkspaceEditorHost.vue`
- Modify: `frontend/tests/workspaceEditorHostLayoutMode.test.ts`

- [ ] **Step 1: 迁移样式责任**

要求：
- 把旧 `.segment-line` 相关基础样式迁到 `segmentBlock` 根节点 class
- gutter 宽度由 NodeView 左列承担，不再依赖 `padding-left`
- 行号、拖拽头、hover 态、selected/dirty/playing/reorder 状态尽量复用现有视觉 token

- [ ] **Step 2: 写回归断言**

断言至少覆盖源码包含：
- `segment-block-gutter`
- `segment-block-content`
- 稳定 gutter 宽度定义
- 编辑态仅隐藏 gutter 内容，而不是让正文重新缩进

- [ ] **Step 3: 运行相关测试**

Run: `npm run test -- workspaceEditorHostLayoutMode.test.ts workspaceEditorDecoration.test.ts workspaceEditorListSegmentBlock.test.ts`
Expected: PASS

- [ ] **Step 4: 做人工视觉验收**

人工检查：
- 展示态列表式与当前主分支外观尽量一致
- 编辑态列表式输入后不会出现当前段及以下段左移
- 展示态行号位置与旧版本基本一致
- 拖拽头 hover 感受与旧版本接近
- pauseBoundary 在列表式中的视觉基线未回归

---

## Chunk 6: 文档园丁收尾

### Task 10: 同步文档，删除过期口径

**Files:**
- Modify: `llmdoc/` 中与 Workspace Editor 列表式结构相关的文档
- Modify: `llmdoc/index.md`（如果存在且已纳入索引）

- [ ] **Step 1: 定位现有文档口径**

重点查找是否仍有以下过期描述：
- 列表式是“一段一个 paragraph”
- 行号/拖拽头由 widget decoration 插入
- 列表式基础布局依赖 `segmentDecoration`

- [ ] **Step 2: 彻底重写相关段落**

要求：
- 改成 `segmentBlock + NodeView` 口径
- 明确组合视图保持现状
- 删除而不是追加旧方案说明

- [ ] **Step 3: 核对索引**

要求：
- 如果新增了 `llmdoc` 文档，必须把索引补齐
- 如果没有可维护的 `llmdoc` 现存文档，则新增一篇最小架构说明，不允许只把新口径留在代码里

---

## 验收标准

- 列表式编辑任意段后，当前段及以下段不会再顶到原行号位置。
- 列表式基础布局由 `segmentBlock` NodeView 承担，不再依赖 `.segment-line + padding-left`。
- `listReorderHandleDecoration.ts` 已删除，仓库中无残留引用。
- `WorkspaceRenderMap.segmentBlockRanges` 已删除，列表式不再依赖旧坐标区间。
- 列表式 normalizer 已改为按 `segmentBlock.attrs.segmentId` 提取。
- 组合视图用户行为和视觉语义保持不变。
- 自动化测试通过，人工视觉验收确认列表式外观与旧版本尽量一致。
- 相关 `llmdoc` 文档已同步到最新架构，不遗留旧口径。

---

Plan complete and saved to `docs/superpowers/plans/2026-04-09-workspace-list-segment-block-refactor.md`. Ready to execute?
