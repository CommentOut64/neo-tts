# Edit Session Segment Swap Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 edit-session 增加 `POST /v1/edit-session/segments/swap`，实现交换两个段顺序时不重推理 segment、只重建 fallback boundary 并重新装配。

**Architecture:** 通过 `SegmentService` 负责交换 snapshot 中的段顺序与邻接关系，通过 `RenderPlanner` 只标记受影响 edge / block，通过 `RenderJobService` 在 edit render 路径为新边生成 equal-power crossfade fallback boundary，并复用原 segment render asset 完成新的 composition。

**Tech Stack:** FastAPI, Pydantic, SQLite repository, numpy audio processing, pytest

---

## Chunk 1: API And Domain Mutation

### Task 1: 定义 swap 请求 schema 与路由入口

**Files:**
- Modify: `backend/app/schemas/edit_session.py`
- Modify: `backend/app/api/routers/edit_session.py`
- Test: `backend/tests/integration/test_edit_session_router.py`

- [ ] **Step 1: 写失败测试，声明 swap 路由存在并返回 202**

```python
def test_swap_segments_returns_accepted_job(...):
    response = client.post(
        "/v1/edit-session/segments/swap",
        json={"first_segment_id": "seg-1", "second_segment_id": "seg-2"},
    )
    assert response.status_code == 202
```

- [ ] **Step 2: 运行测试，确认因路由缺失失败**

Run: `pytest backend/tests/integration/test_edit_session_router.py -q -k swap`
Expected: FAIL with 404 or missing route assertion.

- [ ] **Step 3: 增加 `SwapSegmentsRequest` 和 router 入口**

```python
class SwapSegmentsRequest(BaseModel):
    first_segment_id: str
    second_segment_id: str
```

```python
@router.post("/segments/swap", response_model=RenderJobAcceptedResponse, status_code=202)
def swap_segments(request: Request, body: SwapSegmentsRequest) -> RenderJobAcceptedResponse:
    return _build_render_job_service(request).create_swap_segments_job(body)
```

- [ ] **Step 4: 重新运行测试**

Run: `pytest backend/tests/integration/test_edit_session_router.py -q -k swap`
Expected: still FAIL, but now进入 service 缺失或 backend 行为缺失。

### Task 2: 在 SegmentService 实现 snapshot 级 swap

**Files:**
- Modify: `backend/app/services/segment_service.py`
- Test: `backend/tests/unit/test_segment_service.py` 或补到现有相关单测文件

- [ ] **Step 1: 写失败测试，锁定 swap 后顺序与邻接关系**

```python
def test_swap_segments_reorders_snapshot_and_rebuilds_neighbors():
    mutation = service.swap_segments("seg-2", "seg-3", snapshot=snapshot)
    assert [segment.segment_id for segment in mutation.snapshot.segments] == ["seg-1", "seg-3", "seg-2"]
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `pytest backend/tests/unit/test_segment_service.py -q -k swap`
Expected: FAIL with missing method or assertion failure.

- [ ] **Step 3: 最小实现 `swap_segments(...)`**

要求：
- 校验两个 id 存在且不同
- 交换列表位置
- 复用 `_normalize_segment_order(...)`
- 调用 `edge_service.rebuild_neighbor_edges(...)`
- 返回新 snapshot

- [ ] **Step 4: 重新运行测试**

Run: `pytest backend/tests/unit/test_segment_service.py -q -k swap`
Expected: PASS

## Chunk 2: Planning And Fallback Boundary

### Task 3: 为 swap 增加 targeted render planning

**Files:**
- Modify: `backend/app/services/render_planner.py`
- Test: `backend/tests/unit/test_render_planner.py`

- [ ] **Step 1: 写失败测试，锁定 swap 不触发 segment rerender**

```python
def test_for_segment_swap_only_targets_changed_edges_and_blocks():
    plan = planner.for_segment_swap(...)
    assert plan.target_segment_ids == set()
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `pytest backend/tests/unit/test_render_planner.py -q -k swap`
Expected: FAIL with missing method.

- [ ] **Step 3: 实现 `for_segment_swap(...)`**

要求：
- 根据 before/after 邻接差异找出受影响 edge
- 只标记受影响 block
- `compose_only = False`

- [ ] **Step 4: 重新运行测试**

Run: `pytest backend/tests/unit/test_render_planner.py -q -k swap`
Expected: PASS

### Task 4: 实现 equal-power crossfade fallback boundary builder

**Files:**
- Modify: `backend/app/services/composition_builder.py` 或 `backend/app/services/render_job_service.py`
- Test: `backend/tests/unit/test_composition_builder.py` 或新增小型单测

- [ ] **Step 1: 写失败测试，锁定 fallback boundary 使用左右 margin 构造**

```python
def test_build_fallback_boundary_crossfades_left_and_right_margins():
    boundary = build_fallback_boundary(left_asset, right_asset, edge)
    assert boundary.boundary_sample_count == expected
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `pytest backend/tests/unit/test_composition_builder.py -q -k fallback`
Expected: FAIL with missing helper.

- [ ] **Step 3: 最小实现 fallback boundary**

要求：
- 双侧 margin 都有时做 equal-power crossfade
- 单侧缺失时退化为直接输出另一侧可用 margin
- 两侧都为空时返回空 boundary

- [ ] **Step 4: 重新运行测试**

Run: `pytest backend/tests/unit/test_composition_builder.py -q -k fallback`
Expected: PASS

## Chunk 3: Render Job Integration And End-To-End Verification

### Task 5: 将 swap job 接入 RenderJobService

**Files:**
- Modify: `backend/app/services/render_job_service.py`
- Modify: `backend/app/api/routers/edit_session.py`
- Test: `backend/tests/integration/test_edit_session_router.py`

- [ ] **Step 1: 写失败测试，锁定 swap job 完成后 segments / edges / composition 更新**

```python
def test_swap_segments_reuses_segment_assets_and_updates_composition(...):
    accepted = client.post("/v1/edit-session/segments/swap", json=...)
    assert accepted.status_code == 202
    ...
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `pytest backend/tests/integration/test_edit_session_router.py -q -k swap`
Expected: FAIL with missing service behavior or incorrect snapshot.

- [ ] **Step 3: 实现 `create_swap_segments_job(...)` 与 edit render 中的 fallback boundary 路径**

要求：
- `job_kind = "segment_swap"`
- 复用已有 segment assets
- 对目标 edge 生成 fallback boundary
- compose 并 commit 新 snapshot

- [ ] **Step 4: 重新运行集成测试**

Run: `pytest backend/tests/integration/test_edit_session_router.py -q -k swap`
Expected: PASS

### Task 6: 运行回归与真实实验

**Files:**
- Test: `backend/tests/unit/test_render_planner.py`
- Test: `backend/tests/unit/test_composition_builder.py`
- Test: `backend/tests/integration/test_edit_session_router.py`

- [ ] **Step 1: 运行相关单测与集成测试**

Run: `pytest backend/tests/unit/test_render_planner.py backend/tests/unit/test_composition_builder.py backend/tests/integration/test_edit_session_router.py -q -k "swap or composition or segments"`
Expected: PASS

- [ ] **Step 2: 通过公开接口完成一次真实 swap 实验并导出 composition 音频**

Run: 使用 `TestClient` 或真实接口脚本：
- initialize 真实文本
- 调用 `/v1/edit-session/segments/swap`
- 拉取 `/snapshot` `/playback-map` `/composition`
- 导出总音频

Expected:
- 段顺序已交换
- 总音频可下载
- 不发生 segment 重新推理

- [ ] **Step 3: 汇总验证证据**

记录：
- 受影响 edge 列表
- 是否复用了 segment render asset
- composition 音频输出路径
