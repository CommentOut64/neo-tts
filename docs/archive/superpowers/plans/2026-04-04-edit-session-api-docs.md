# Edit Session API Docs Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 `edit-session` 后端补齐可直接给前端使用的 Swagger/OpenAPI 注释，并新增一份流程型 API 指南文档。

**Architecture:** 以 FastAPI 自动生成的 OpenAPI 作为结构化接口真相源，在路由和 schema 上补充摘要、描述、状态码和关键字段语义；另用一份 `docs/api/edit-session-api-guide.md` 承载状态流、调用顺序、SSE 与兼容语义等 Swagger 难完整表达的内容。

**Tech Stack:** FastAPI, Pydantic v2, Markdown

---

## Chunk 1: Swagger 注释基线

### Task 1: 路由级 OpenAPI 描述

**Files:**
- Modify: `backend/app/api/routers/edit_session.py`

- [ ] 为 `initialize / snapshot / timeline / groups / render-profiles / voice-bindings / segments / edges / render-jobs / exports / playback-map / composition / preview` 等路由补 `summary`
- [ ] 为异步 mutation、render job、export job、SSE 路由补 `description`
- [ ] 为关键错误场景补 `responses`，至少覆盖 `400 / 404 / 409 / 410`
- [ ] 在兼容接口上明确 `/timeline` 为主接口、`/playback-map` 与 `/composition` 为兼容接口

### Task 2: Schema 字段说明

**Files:**
- Modify: `backend/app/schemas/edit_session.py`

- [ ] 为前端直接消费的请求/响应模型补 `Field(description=...)`
- [ ] 优先覆盖初始化、追加、段/边编辑、profile/binding patch、render/export job、snapshot、timeline、playback-map、composition、asset delivery
- [ ] 给关键枚举/约束字段补简短说明，避免把内部实现细节暴露成噪音

## Chunk 2: 前端使用指南

### Task 3: 新增 `docs/api/edit-session-api-guide.md`

**Files:**
- Create: `docs/api/edit-session-api-guide.md`

- [ ] 写清接口分层：主读取接口、兼容读取接口、异步作业接口、导出接口
- [ ] 写清推荐调用顺序：initialize -> 轮询/订阅 -> timeline/snapshot -> mutation -> render job/export job 查询
- [ ] 写清 `document_version`、`/composition`、`target_dir`、SSE 事件、兼容语义
- [ ] 用前端接入视角组织内容，而不是后端实现视角

## Chunk 3: 验证

### Task 4: 文档与 OpenAPI 一致性自检

**Files:**
- Modify if needed: `backend/app/api/routers/edit_session.py`
- Modify if needed: `backend/app/schemas/edit_session.py`
- Modify if needed: `docs/api/edit-session-api-guide.md`

- [ ] 运行定向测试，确认文档化改动未破坏现有行为
- [ ] 检查 `docs/api/edit-session-api-guide.md` 与当前 B4 语义一致
- [ ] 检查 Swagger 文案与当前 `/composition`、export、SSE 语义一致
