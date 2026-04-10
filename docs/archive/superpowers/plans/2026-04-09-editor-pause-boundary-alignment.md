# Editor Pause Boundary Alignment Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 Workspace Editor 中的停顿节点在列表视图和组合视图里都与正文文本共享同一套行内度量，实现等高且水平基线对齐。

**Architecture:** 以 `WorkspaceEditorHost.vue` 作为正文排版真源，在 `.ProseMirror` 作用域内定义停顿节点共享的排版变量，并按 `layoutMode` 分别对齐列表视图普通文本 span 与组合视图 `segment-fragment` span 的真实高度。`PauseBoundaryNodeView.vue` 与 `pauseBoundaryViewModel.ts` 只保留结构、状态和轻量外观，不再持有固定高度、固定字号或破坏基线的对齐策略。

**Tech Stack:** Vue 3、TypeScript、TipTap、Vitest、Scoped CSS、Tailwind utility class

---

## 文件结构

**停顿节点结构与 class 收口**
- Modify: `frontend/src/components/workspace/workspace-editor/PauseBoundaryNodeView.vue`
- Modify: `frontend/src/components/workspace/workspace-editor/pauseBoundaryViewModel.ts`
- Test: `frontend/tests/pauseBoundaryViewModel.test.ts`

**宿主排版真源与回归断言**
- Modify: `frontend/src/components/workspace/WorkspaceEditorHost.vue`
- Test: `frontend/tests/workspaceEditorHostLayoutMode.test.ts`

---

## Chunk 1: 停顿节点不再自带固定尺寸

### Task 1: 先用 view model 测试锁住“去固定高度/字号”的约束

**Files:**
- Modify: `frontend/tests/pauseBoundaryViewModel.test.ts`
- Test: `frontend/tests/pauseBoundaryViewModel.test.ts`

- [ ] **Step 1: 补失败测试，约束停顿节点 class 必须保留行内按钮语义，但不能再包含固定高度和固定字号**

断言至少覆盖：
- 普通停顿与跨块停顿都包含 `inline-flex`
- 跨块停顿仍包含 `border-dashed`
- class 中不再包含 `h-6`
- class 中不再包含 `text-[11px]`

- [ ] **Step 2: 运行测试确认失败**

Run: `npm run test -- pauseBoundaryViewModel.test.ts`
Expected: FAIL，提示当前 class 仍然包含固定高度或固定字号

- [ ] **Step 3: 收敛 `pauseBoundaryViewModel.ts` 的 class 责任**

把 class 收敛为只负责：
- `inline-flex`
- `items-center`
- `gap-*`
- `rounded`
- `border*`
- `bg-*`
- `px-*`
- `font-medium`
- `text-muted-fg`
- `transition-colors`

明确移除：
- `h-6`
- `text-[11px]`

- [ ] **Step 4: 运行测试确认通过**

Run: `npm run test -- pauseBoundaryViewModel.test.ts`
Expected: PASS

### Task 2: 调整停顿节点模板，改为基线对齐且图标与标签共用同一套排版

**Files:**
- Modify: `frontend/src/components/workspace/workspace-editor/PauseBoundaryNodeView.vue`
- Test: `frontend/tests/workspaceEditorHostLayoutMode.test.ts`

- [ ] **Step 1: 补失败断言，禁止节点 wrapper 继续使用会破坏文本基线的对齐策略**

断言至少覆盖：
- 节点 wrapper 不再包含 `align-middle`
- cross-block 图标不再使用 `leading-none`

- [ ] **Step 2: 运行测试确认失败**

Run: `npm run test -- workspaceEditorHostLayoutMode.test.ts`
Expected: FAIL，提示源码里仍然存在 `align-middle` 或 `leading-none`

- [ ] **Step 3: 修改 `PauseBoundaryNodeView.vue`**

要求：
- wrapper 保留行内原子语义和必要横向间距
- 去掉 `align-middle`
- cross-block 图标改为继承节点内部排版，不再单独压缩行高
- 仅保留结构、title、click handler 和状态 data attrs

- [ ] **Step 4: 运行测试确认通过**

Run: `npm run test -- workspaceEditorHostLayoutMode.test.ts`
Expected: PASS

---

## Chunk 2: 宿主层成为停顿节点的尺寸真源

### Task 3: 在 `WorkspaceEditorHost.vue` 中定义统一行内度量，并让状态样式只改颜色

**Files:**
- Modify: `frontend/src/components/workspace/WorkspaceEditorHost.vue`
- Test: `frontend/tests/workspaceEditorHostLayoutMode.test.ts`

- [ ] **Step 1: 补失败断言，约束宿主层存在停顿节点专用排版变量和按 layoutMode 区分的高度样式块**

断言至少覆盖源码包含：
- `--workspace-pause-boundary-font-size`
- `--workspace-pause-boundary-line-height`
- `--workspace-pause-boundary-list-span-height`
- `data-layout-mode`
- `[data-layout-mode="list"] button`
- `[data-layout-mode="composition"] button`
- `[data-edge-id] button`

并断言：
- 宿主样式中停顿节点按钮使用继承字号/行高
- 列表视图高度对齐普通文本 span
- 组合视图高度对齐 `segment-fragment` span
- 宿主状态样式不再定义额外高度类

- [ ] **Step 2: 运行测试确认失败**

Run: `npm run test -- workspaceEditorHostLayoutMode.test.ts`
Expected: FAIL，提示宿主尚未提供停顿节点统一度量变量

- [ ] **Step 3: 修改 `WorkspaceEditorHost.vue` 样式**

要求：
- 在 `.ProseMirror` 作用域定义停顿节点共享变量
- 为 `[data-edge-id] button` 提供 `font-size: var(...)`、`line-height: var(...)`、`height: var(...)`
- 节点按钮保持 `inline-flex` + `align-items: center`
- selected / dirty / playing / editing-playing 样式只改颜色、边框和阴影，不改尺寸

- [ ] **Step 4: 运行测试确认通过**

Run: `npm run test -- workspaceEditorHostLayoutMode.test.ts`
Expected: PASS

### Task 4: 运行本次改动相关回归测试并记录人工验收项

**Files:**
- Test: `frontend/tests/pauseBoundaryViewModel.test.ts`
- Test: `frontend/tests/workspaceEditorHostLayoutMode.test.ts`

- [ ] **Step 1: 运行全部相关自动化测试**

Run: `npm run test -- pauseBoundaryViewModel.test.ts workspaceEditorHostLayoutMode.test.ts`
Expected: PASS

- [ ] **Step 2: 记录人工验收口径**

人工检查：
- 列表视图普通停顿节点与文本等高且同一基线
- 组合视图普通停顿节点与文本等高且同一基线
- 组合视图跨块停顿节点与文本等高且同一基线
- `selected / dirty / playing / editing-playing` 下高度不跳动
- 列表/组合切换时同一停顿节点尺寸不抖动

---

## 验收标准

- `pauseBoundary` class 不再携带固定高度与固定字号。
- `PauseBoundaryNodeView.vue` 不再通过 `align-middle` 或 `leading-none` 做视觉补偿。
- `WorkspaceEditorHost.vue` 成为停顿节点尺寸的唯一真源。
- 自动化测试通过后，人工检查能确认列表与组合视图下停顿节点都与文本等高且水平对齐。

---

Plan complete and saved to `docs/superpowers/plans/2026-04-09-editor-pause-boundary-alignment.md`. Ready to execute?
