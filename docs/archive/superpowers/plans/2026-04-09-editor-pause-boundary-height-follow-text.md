# Editor Pause Boundary Height Follow Text Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 Workspace Editor 中的停顿节点不再维护独立高度，直接跟随正文真实文本盒高度对齐。

**Architecture:** 继续保留现有 `pauseBoundary` 节点结构与交互，仅在 `WorkspaceEditorHost.vue` 收口排版真源。停顿节点按钮改为继承正文字号，并使用 `line-height: normal` 去匹配正文真实文本盒高度，同时删除 list/composition 的高度分叉断言。

**Tech Stack:** Vue 3, TipTap, scoped CSS, Vitest

---

## Chunk 1: Pause Boundary Inline Metrics

### Task 1: 收口宿主层停顿节点高度策略

**Files:**
- Modify: `frontend/src/components/workspace/WorkspaceEditorHost.vue`
- Modify: `frontend/tests/workspaceEditorHostLayoutMode.test.ts`
- Modify: `docs/superpowers/specs/2026-04-09-editor-pause-boundary-alignment-design.md`

- [ ] **Step 1: 更新宿主层 CSS**

删除 `--workspace-pause-boundary-*height` 与 layout-mode 高度分叉，让 `[data-edge-id] button` 继承正文字号并使用 `line-height: normal`。

- [ ] **Step 2: 更新回归断言**

把字符串断言从“分别定义 list/composition 高度”改成“跟随正文排版，不再定义独立高度”。

- [ ] **Step 3: 同步设计文档**

覆写旧 spec 中关于 list/composition 分别控制高度的段落，改成统一按正文真实文本盒高度对齐。

- [ ] **Step 4: 运行定向验证**

Run: `npm test -- --run tests/workspaceEditorHostLayoutMode.test.ts`（在 `frontend/` 目录下执行）

Expected: 相关断言全部通过。
