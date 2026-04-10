# Workspace Playback Cursor Unification Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 `workspace` 的正文高亮、控制栏和波形图都以同一个 playback cursor 作为播放语义真源，彻底消除段间 boundary / pause 区间的状态分裂。

**Architecture:** 保留现有 `usePlayback` 的 Web Audio block 调度主干，只把“当前播放位置”的语义解析收口到 `useTimeline` 的纯函数解析器，再由 `usePlayback` 暴露 `currentCursor` 和兼容派生值 `currentSegmentId`。正文 decoration、控制栏、波形图和残余的 workspace 播放消费者全部迁移到 cursor 口径；若时间线 manifest 非法，则播放进入显式错误态并 fail-closed。

**Tech Stack:** Vue 3、TypeScript、Vitest、Web Audio API、TipTap、ripgrep

---

## 文件结构

**时间线解析与类型收口**
- Modify: `frontend/src/types/editSession.ts`
- Modify: `frontend/src/composables/useTimeline.ts`
- Create: `frontend/tests/useTimeline.playbackCursor.test.ts`

**播放状态派生与错误态**
- Modify: `frontend/src/composables/usePlayback.ts`
- Modify: `frontend/tests/usePlayback.seek-fade.test.ts`

**workspace UI 消费者迁移**
- Modify: `frontend/src/components/workspace/WorkspaceEditorHost.vue`
- Modify: `frontend/src/components/workspace/workspace-editor/segmentDecoration.ts`
- Modify: `frontend/src/components/workspace/SegmentListDisplay.vue`
- Modify: `frontend/tests/workspaceEditorDecoration.test.ts`
- Create: `frontend/tests/segmentListDisplay.playback-state.test.ts`

**回归验证与边界检查**
- Modify: `frontend/src/components/workspace/TransportControlBar.vue`
- Modify: `frontend/src/components/workspace/WaveformStrip.vue`
- Modify: `frontend/tests/useWorkspaceProcessing.test.ts`
- Modify: `README.md`

## Chunk 1: 时间线游标与播放内核统一

### Task 1: 先用时间线解析测试锁定 `segment / boundary / pause / ended` 语义

**Files:**
- Create: `frontend/tests/useTimeline.playbackCursor.test.ts`
- Modify: `frontend/src/composables/useTimeline.ts`
- Modify: `frontend/src/types/editSession.ts`

- [ ] **Step 1: 新建失败测试文件，先把 playback cursor 语义写死**

在 `frontend/tests/useTimeline.playbackCursor.test.ts` 里为新的时间线解析器准备最小 manifest fixture，至少覆盖：
- `sample < playable_sample_span[0]` 返回 `before_start`
- 段内 sample 返回 `segment`
- `boundary_start_sample <= sample < boundary_end_sample` 返回 `boundary`
- `pause_start_sample <= sample < pause_end_sample` 返回 `pause`
- `sample >= playable_sample_span[1]` 返回 `ended`
- 临界 sample `3 / 4 / 6 / 9` 的归属严格遵守 spec 的半开区间规则

测试示例应直接断言 cursor 结构，例如：

```ts
expect(resolvePlaybackCursor(manifest, 3)).toEqual({
  sample: 3,
  kind: "boundary",
  segmentId: null,
  edgeId: "edge-1",
  leftSegmentId: "seg-1",
  rightSegmentId: "seg-2",
  spanStartSample: 3,
  spanEndSample: 4,
  progressInSpan: 0,
});
```

- [ ] **Step 2: 运行测试确认失败**

Run: `npm run test -- useTimeline.playbackCursor.test.ts`
Expected: FAIL，提示 `resolvePlaybackCursor` 或相关类型尚不存在

- [ ] **Step 3: 在同一测试文件补兼容护栏，锁定 `sampleToSegmentId()` 的降级行为**

至少增加以下断言：
- `boundary` sample 返回 `null`
- `pause` sample 返回 `null`
- `ended` sample 返回 `null`
- `segment` sample 仍返回正确 `segmentId`

示例：

```ts
expect(sampleToSegmentId(2)).toBe("seg-1");
expect(sampleToSegmentId(3)).toBeNull();
expect(sampleToSegmentId(4)).toBeNull();
expect(sampleToSegmentId(9)).toBeNull();
```

- [ ] **Step 4: 在类型层补充 playback cursor 的显式定义**

在 `frontend/src/types/editSession.ts` 中新增最小闭环所需类型：
- `PlaybackCursorKind`
- `PlaybackCursor`
- 如有必要，补 `TimelineEdgeEntry` 的导出消费注释，但不改后端协议结构

要求：
- 可空规则与 spec 完全一致
- 不为本轮未使用的未来场景添加额外字段

- [ ] **Step 5: 在 `useTimeline.ts` 先实现纯函数解析器，不带额外容错猜测**

实现最小必要能力：
- 导出纯函数 `resolvePlaybackCursor(manifest, sample)`
- 基于半开区间规则正确解析 `before_start / segment / boundary / pause / ended`
- `segmentIdToSampleRange()` 行为保持不变
- `sampleToSegmentId()` 降级为兼容辅助：仅当 cursor.kind === `segment` 时返回段 id，否则返回 `null`

- [ ] **Step 6: 在 `useTimeline.ts` 再补最小 manifest 校验**

实现要求：
- 导出或内聚最小校验逻辑，至少检查：
  - `playable_sample_span` 合法
  - `segment_entries` 单调且不重叠
  - `edge_entries` 的 boundary / pause 区间单调且不重叠
  - edge 区间不与 segment 区间重叠
  - edge 引用的左右 segment 在 manifest 中都存在
- 对 `playable_sample_span` 内未命中任何区间的 sample 抛显式错误

- [ ] **Step 7: 运行时间线解析测试确认通过**

Run: `npm run test -- useTimeline.playbackCursor.test.ts`
Expected: PASS

### Task 2: 用播放测试锁定 `usePlayback` 只写 sample、由 cursor 派生段状态

**Files:**
- Modify: `frontend/tests/usePlayback.seek-fade.test.ts`
- Modify: `frontend/src/composables/usePlayback.ts`

- [ ] **Step 1: 在现有播放测试里补失败断言，要求 `usePlayback` 暴露 `currentCursor`**

在 `frontend/tests/usePlayback.seek-fade.test.ts` 中增加断言，至少覆盖：
- 初次 `setTimeline()` 后能读取 `currentCursor`
- `seekToSample(12000)` 后 `currentCursor.sample` 随之更新
- `currentSegmentId` 仅在 `currentCursor.kind === "segment"` 时有值

最小示例：

```ts
expect(playback.currentCursor.value.kind).toBe("segment");
playback.seekToSample(24000);
expect(playback.currentCursor.value.kind).toBe("ended");
expect(playback.currentSegmentId.value).toBeNull();
```

- [ ] **Step 2: 运行测试确认失败**

Run: `npm run test -- usePlayback.seek-fade.test.ts`
Expected: FAIL，提示 `currentCursor` 或兼容派生逻辑尚不存在

- [ ] **Step 3: 补失败断言，锁定错误态的清除与恢复**

至少覆盖：
- 非法 manifest 导致 `playbackCursorError` 被设置后，`play()` 不应继续推进播放
- 后续 `setTimeline()` 刷新为合法 manifest 后，`playbackCursorError` 被清空
- 错误清除后可再次 `play()` 并恢复正常 cursor 更新

Run: `npm run test -- usePlayback.seek-fade.test.ts`
Expected: FAIL，提示错误态恢复语义尚未实现

- [ ] **Step 4: 在 `usePlayback.ts` 改成“只维护 sample，cursor 纯派生”**

实现要求：
- 新增 `playbackCursorError` 状态
- `currentCursor` 基于 `currentSample + timelineManifest` 派生，不允许动画帧、seek、pause 直接写段级真相
- `currentSegmentId` 改为 `computed(() => currentCursor.value.kind === "segment" ? currentCursor.value.segmentId : null)`
- seek、pause、播放结束等路径中不再手写 `sampleToSegmentId(...)`
- 当 cursor 解析抛错时：
  - 停止播放
  - 设置 `playbackCursorError`
  - 不再保留旧高亮状态
  - 后续 `setTimeline()` 进入合法状态后允许清除错误并恢复播放
  - `playbackCursorError` 未清除前，`play()` 应 fail-closed，不继续调度 block

- [ ] **Step 5: 运行播放测试确认通过**

Run: `npm run test -- usePlayback.seek-fade.test.ts`
Expected: PASS

- [ ] **Step 6: 运行时间线与播放核心测试组**

Run: `npm run test -- useTimeline.playbackCursor.test.ts usePlayback.seek-fade.test.ts`
Expected: PASS

### Task 3: 补非法 manifest 的 fail-closed 回归测试

**Files:**
- Modify: `frontend/tests/useTimeline.playbackCursor.test.ts`
- Modify: `frontend/tests/usePlayback.seek-fade.test.ts`
- Modify: `frontend/src/composables/useTimeline.ts`
- Modify: `frontend/src/composables/usePlayback.ts`

- [ ] **Step 1: 为非法 manifest 新增失败测试**

在 `frontend/tests/useTimeline.playbackCursor.test.ts` 中至少新增两类非法时间线：
- segment / edge 区间重叠
- sample 落在 playable span 内但任何 segment / edge 都未覆盖

并在 `frontend/tests/usePlayback.seek-fade.test.ts` 中断言：
- 解析失败后 `isPlaying` 变为 `false`
- `playbackCursorError` 存在

- [ ] **Step 2: 运行测试确认失败**

Run: `npm run test -- useTimeline.playbackCursor.test.ts usePlayback.seek-fade.test.ts`
Expected: FAIL，提示非法 manifest 尚未触发显式错误或 fail-closed

- [ ] **Step 3: 补齐最小实现，让错误态与测试对齐**

要求：
- 不吞异常
- 不在错误时伪造某个 segment cursor
- 不引入额外 toast / 全局通知系统；先把状态暴露给 workspace UI 使用

- [ ] **Step 4: 运行 Chunk 1 全部测试**

Run: `npm run test -- useTimeline.playbackCursor.test.ts usePlayback.seek-fade.test.ts`
Expected: PASS

## Chunk 2: workspace UI 消费者迁移与收口

### Task 4: 先用 decoration 测试锁住“正文只认 cursor，不认伪造段归属”

**Files:**
- Modify: `frontend/tests/workspaceEditorDecoration.test.ts`
- Modify: `frontend/src/components/workspace/workspace-editor/segmentDecoration.ts`
- Modify: `frontend/src/components/workspace/WorkspaceEditorHost.vue`

- [ ] **Step 1: 补失败测试，锁定 boundary / pause 时正文不高亮**

在 `frontend/tests/workspaceEditorDecoration.test.ts` 中新增覆盖：
- `playingCursor.kind === "segment"` 时，目标段仍加 `segment-playing` / `segment-line-playing`
- `playingCursor.kind === "boundary"` 或 `pause` 时，不给任何段添加播放 class
- `playingCursor.kind === "before_start"` 时，不给任何段添加播放 class
- `playingCursor.kind === "ended"` 时，不给任何段添加播放 class
- 若保留 `playingId` 字段，测试要改成验证新 cursor 字段驱动的结果，而不是直接验证旧字段

- [ ] **Step 2: 运行测试确认失败**

Run: `npm run test -- workspaceEditorDecoration.test.ts`
Expected: FAIL，提示 decoration 还在直接消费旧 `playingId`

- [ ] **Step 3: 修改 `segmentDecoration.ts`，把播放样式输入改成 cursor 语义**

要求：
- 将外部注入状态从“单一 `playingId`”升级为最小必要 cursor 语义
- 仅 `kind === "segment"` 时给段打播放 class
- 不为 boundary / pause 额外引入本轮未要求的新视觉 class

- [ ] **Step 4: 修改 `WorkspaceEditorHost.vue`，把 decoration 状态改接 `currentCursor`**

要求：
- `usePlayback()` 解构改为 `currentCursor`
- `syncDecorationState()` 写入 cursor，而非仅写 `playingId`
- 监听源从 `currentSegmentId` 迁移到 `currentCursor`
- 保持空格播放 / 点击播放 / 双击编辑现有交互不变

- [ ] **Step 5: 运行测试确认通过**

Run: `npm run test -- workspaceEditorDecoration.test.ts workspaceEditorHostLayoutMode.test.ts`
Expected: PASS

### Task 5: 收口残余 workspace 播放消费者，禁止新增旧真源依赖

**Files:**
- Modify: `frontend/src/components/workspace/SegmentListDisplay.vue`
- Create: `frontend/tests/segmentListDisplay.playback-state.test.ts`
- Modify: `frontend/src/components/workspace/TransportControlBar.vue`
- Modify: `frontend/src/components/workspace/WaveformStrip.vue`
- Modify: `frontend/src/components/workspace/WorkspaceEditorHost.vue`

- [ ] **Step 1: 用检索确认旧真源消费点清单**

Run: `rg -n "currentSegmentId|sampleToSegmentId" frontend/src/components/workspace frontend/src/composables`
Expected: 结果至少包含 `WorkspaceEditorHost.vue`、`SegmentListDisplay.vue`、`usePlayback.ts`，并作为本任务的收口清单

- [ ] **Step 2: 修改 `SegmentListDisplay.vue`，改为从 `currentCursor` 判断当前段**

要求：
- 列表视图高亮逻辑与正文一致
- `currentCursor.kind === "segment"` 时才认为某段正在播放
- `boundary / pause / ended` 时不高亮任何条目

- [ ] **Step 3: 新增 `SegmentListDisplay` 行为测试，锁定列表态播放高亮规则**

在 `frontend/tests/segmentListDisplay.playback-state.test.ts` 中至少覆盖：
- `currentCursor.kind === "segment"` 时，当前条目高亮
- `currentCursor.kind === "boundary"` 时，不高亮任何条目
- `currentCursor.kind === "pause"` 时，不高亮任何条目
- `currentCursor.kind === "ended"` 时，不高亮任何条目

- [ ] **Step 4: 修改 `TransportControlBar.vue`，明确接入 cursor 错误态**

要求：
- 从 `usePlayback()` 解构 `playbackCursorError`
- 当 `playbackCursorError` 存在时，播放按钮禁用
- 时间显示与 seek 百分比仍继续基于 `currentSample`
- 不新增 toast，不改变上一段 / 下一段跳转规则

- [ ] **Step 5: 修改 `WaveformStrip.vue`，明确接入 cursor 错误态**

要求：
- 从 `usePlayback()` 解构 `playbackCursorError`
- 当 `playbackCursorError` 存在时，禁止拖拽 seek
- 已有波形进度显示仍继续基于 `currentSample`
- 不新增本轮未要求的过渡区视觉样式

- [ ] **Step 6: 运行列表态与控制组件测试，确认行为收口**

Run: `npm run test -- segmentListDisplay.playback-state.test.ts workspaceEditorDecoration.test.ts`
Expected: PASS

- [ ] **Step 7: 用定向检索确认 src 内 workspace 播放消费点已收口**

Run: `rg -n "usePlayback\\(\\)|currentSegmentId|sampleToSegmentId|currentCursor|playbackCursorError" frontend/src/components/workspace frontend/src/composables/usePlayback.ts frontend/src/composables/useTimeline.ts`
Expected:
- `WorkspaceEditorHost.vue`、`SegmentListDisplay.vue`、`TransportControlBar.vue`、`WaveformStrip.vue` 已显式接入 `currentCursor` 或 `playbackCursorError`
- `currentSegmentId` 只允许保留在 `usePlayback.ts` 作为兼容派生导出
- `sampleToSegmentId` 不再被 workspace UI 直接消费

- [ ] **Step 8: 用测试目录检索确认 mock 与断言已迁移到 cursor 口径**

Run: `rg -n "currentSegmentId|sampleToSegmentId|currentCursor|playbackCursorError" frontend/tests`
Expected:
- workspace 相关测试已出现 `currentCursor` 或 `playbackCursorError`
- 如仍存在旧 `currentSegmentId` 断言，也只能用于验证兼容派生，而不是作为真源行为断言

### Task 6: 修正依赖 `usePlayback` mock 的测试，防止回归误报

**Files:**
- Modify: `frontend/tests/useWorkspaceProcessing.test.ts`
- Modify: `frontend/tests/workspaceEditorDecoration.test.ts`
- Modify: `frontend/tests/usePlayback.seek-fade.test.ts`

- [ ] **Step 1: 为 mock 形态补失败测试或失败断言**

要求：
- 检查 `useWorkspaceProcessing.test.ts` 里的 `playbackMock` 是否需要新增 `currentCursor` / `playbackCursorError`
- 避免测试因为 mock 结构过旧而通过，但真实实现已变更

- [ ] **Step 2: 运行相关测试确认失败或暴露缺口**

Run: `npm run test -- useWorkspaceProcessing.test.ts workspaceEditorDecoration.test.ts usePlayback.seek-fade.test.ts`
Expected: 若 mock 未同步，至少一项测试失败并指出缺失字段

- [ ] **Step 3: 同步更新测试 mock 与断言**

要求：
- 所有 workspace 相关测试都按 cursor 口径准备 mock
- 不再用“给一个 `currentSegmentId` 就够了”的旧方式绕过行为验证

- [ ] **Step 4: 运行 Chunk 2 自动化测试**

Run: `npm run test -- workspaceEditorDecoration.test.ts workspaceEditorHostLayoutMode.test.ts useWorkspaceProcessing.test.ts usePlayback.seek-fade.test.ts`
Expected: PASS

### Task 7: 跑完整相关测试组并同步文档

**Files:**
- Modify: `README.md`
- Modify: `llmdoc/index.md`（仅当索引已收录播放状态说明时才更新）
- Modify: 任何被实现改动直接影响的 `llmdoc` 播放链路文档（若存在）

- [ ] **Step 1: 运行本次改动的完整前端相关测试组**

Run: `npm run test -- useTimeline.playbackCursor.test.ts usePlayback.seek-fade.test.ts workspaceEditorDecoration.test.ts workspaceEditorHostLayoutMode.test.ts useWorkspaceProcessing.test.ts segmentNavigation.test.ts`
Expected: PASS

- [ ] **Step 2: 手工回归 workspace 主链路**

人工检查：
- 点击正文段播放
- 连续播放跨 `boundary`
- 连续播放跨 `pause`
- 拖动控制栏到段间区间
- 拖动波形图到段间区间
- 播放结束后重新播放
- 构造非法时间线或通过测试替身验证错误态时，正文不残留高亮

- [ ] **Step 3: 同步文档到最新状态**

要求：
- `README.md` 中若仍把 `useTimeline` 描述成“只维护段 ↔ sample 映射”，更新为“维护统一时间线语义解析，驱动点击跳转与实时高亮”
- 若 `llmdoc/` 中存在直接描述旧 `currentSegmentId` 口径的文档，做覆盖式更新，不追加补丁说明
- 若没有相关文档，不为形式新建无用文档

- [ ] **Step 4: 运行最终检索门禁，确认无新的 workspace 真源分裂**

Run: `rg -n "usePlayback\\(\\)|currentSegmentId|sampleToSegmentId|currentCursor|playbackCursorError" frontend/src/components/workspace frontend/src/composables/usePlayback.ts frontend/src/composables/useTimeline.ts`
Expected:
- `workspace` UI 播放消费者全部显式走 `currentCursor` / `playbackCursorError`
- `currentSegmentId` 只保留在 `usePlayback.ts` 作为兼容派生导出
- `sampleToSegmentId` 只保留在 `useTimeline.ts` 兼容辅助实现内部，不再被 `workspace` UI 直接消费

## 验收标准

- `currentCursor` 成为 `workspace` 播放语义唯一真源。
- 正文、列表高亮只在 `kind === "segment"` 时激活，段间 `boundary / pause` 不再错误高亮前一段。
- 控制栏与波形图继续反映真实连续时间线位置，且不再与正文语义冲突。
- 非法 manifest 会触发显式错误态并停止播放，而不是静默映射到错误段。
- `workspace` 范围内不存在把 `currentSegmentId` 当作真源的直接消费者。

Plan complete and saved to `docs/superpowers/plans/2026-04-10-workspace-playback-cursor-unification.md`. Ready to execute?
