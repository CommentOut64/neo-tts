# End Session Pending Copy Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将“有待重推理内容时的结束会话弹窗”主提示压缩成一句话，清楚说明后果和可选动作。

**Architecture:** 仅修改 `EndSessionDialog.vue` 的主提示文案，不调整按钮分支、不改会话状态机。先更新静态断言测试锁定目标文案，再修改组件与术语文档，最后做定向验证。

**Tech Stack:** Vue 3、Vitest、Element Plus、Markdown 文档

---

## Chunk 1: 文案与验证

### Task 1: 收口待重推理弹窗主提示

**Files:**
- Modify: `frontend/tests/workspaceEndSessionFlow.test.ts`
- Modify: `frontend/src/components/workspace/EndSessionDialog.vue`
- Modify: `docs/系统术语和对应.md`

- [ ] **Step 1: 写失败测试**

在 `frontend/tests/workspaceEndSessionFlow.test.ts` 中新增或修改断言，要求弹窗包含：

```ts
"现在结束会话，这些修改不会进入当前音频。你可以继续编辑、保留文字并结束会话，或撤销这些修改后结束会话。"
```

并移除对旧长文案的依赖。

- [ ] **Step 2: 运行测试确认失败**

Run: `npm test -- workspaceEndSessionFlow.test.ts`
Expected: FAIL，因为组件里仍是旧文案。

- [ ] **Step 3: 写最小实现**

在 `frontend/src/components/workspace/EndSessionDialog.vue` 中：

```vue
<p v-if="hasPendingRerender">
  现在结束会话，这些修改不会进入当前音频。你可以继续编辑、保留文字并结束会话，或撤销这些修改后结束会话。
</p>
```

保留风险提示与按钮文案不变。

同步更新 `docs/系统术语和对应.md` 中“结束会话前弹窗说明”的统一口径。

- [ ] **Step 4: 运行测试确认通过**

Run: `npm test -- workspaceEndSessionFlow.test.ts`
Expected: PASS

- [ ] **Step 5: 运行扩展验证**

Run: `npm test -- workspaceEndSessionFlow.test.ts clearInputDraftFlow.test.ts textInputAreaActions.test.ts`
Expected: PASS

Run: `npm run build`
Expected: PASS（允许保留现有构建 warning）
