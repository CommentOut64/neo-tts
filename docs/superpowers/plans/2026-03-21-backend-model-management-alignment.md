# Backend Model Management Alignment Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为重构版 FastAPI 后端补齐模型管理接口，保持现有 TTS 能力兼容，并把前端设计文档中的接口定义同步到以后端实现为准。

**Architecture:** 继续沿用 `schema -> repository -> service -> router` 分层，在 `voices` 命名空间内扩展详情、上传、删除和写回能力。上传能力只负责“完整可用 voice”注册：保存上传文件、写入 `voices.json`、返回标准 `VoiceProfile`；TTS 仍消费同一份 voice 配置。

**Tech Stack:** FastAPI, Pydantic, pytest, TestClient, Python pathlib/shutil/json

---

## Chunk 1: Model Management API

### Task 1: 为模型管理写失败测试

**Files:**
- Modify: `backend/tests/conftest.py`
- Modify: `backend/tests/integration/test_voices_router.py`
- Test: `backend/tests/integration/test_voices_router.py`

- [ ] **Step 1: 为详情、上传、删除接口补测试夹具与失败测试**

```python
def test_get_voice_detail_returns_profile(...): ...
def test_upload_voice_persists_files_and_updates_config(...): ...
def test_delete_voice_removes_uploaded_voice(...): ...
```

- [ ] **Step 2: 运行 voices 路由测试，确认新测试先失败**

Run: `.venv\Scripts\python.exe -m pytest backend\tests\integration\test_voices_router.py -v`
Expected: FAIL，原因是新接口或持久化逻辑尚未实现。

### Task 2: 实现 voices 持久化与文件上传

**Files:**
- Modify: `backend/app/core/settings.py`
- Modify: `backend/app/schemas/voice.py`
- Modify: `backend/app/repositories/voice_repository.py`
- Modify: `backend/app/services/voice_service.py`
- Modify: `backend/app/api/routers/voices.py`
- Test: `backend/tests/integration/test_voices_router.py`
- Test: `backend/tests/unit/test_voice_repository.py`

- [ ] **Step 1: 扩展配置与 schema**

```python
class VoiceProfile(BaseModel):
    ...
    managed: bool = False
    created_at: str | None = None
    updated_at: str | None = None
```

- [ ] **Step 2: 为 repository 增加 get/create/upload/delete/write-back 能力**

```python
class VoiceRepository:
    def get_voice(...)
    def create_voice(...)
    def create_uploaded_voice(...)
    def delete_voice(...)
```

- [ ] **Step 3: 在 service/router 暴露 `/v1/voices/{name}`、`/v1/voices/upload`、`DELETE /v1/voices/{name}`**

```python
@router.get("/{voice_name}")
@router.post("/upload")
@router.delete("/{voice_name}")
```

- [ ] **Step 4: 重新运行 voices 相关测试，确认转绿**

Run: `.venv\Scripts\python.exe -m pytest backend\tests\integration\test_voices_router.py backend\tests\unit\test_voice_repository.py -v`
Expected: PASS。

## Chunk 2: TTS Compatibility And Documentation

### Task 3: 验证 TTS 兼容并补必要保护

**Files:**
- Modify: `backend/tests/unit/test_tts_service.py`
- Modify: `backend/tests/integration/test_tts_router.py`
- Modify: `backend/app/services/tts_service.py`
- Test: `backend/tests/unit/test_tts_service.py`
- Test: `backend/tests/integration/test_tts_router.py`

- [ ] **Step 1: 为上传后的 voice 仍可被 TTS 消费补回归测试**

```python
def test_prepare_request_accepts_managed_voice_metadata(...): ...
```

- [ ] **Step 2: 跑 TTS 测试确认是否先失败**

Run: `.venv\Scripts\python.exe -m pytest backend\tests\unit\test_tts_service.py backend\tests\integration\test_tts_router.py -v`
Expected: 若行为未覆盖或被新 schema 影响则 FAIL。

- [ ] **Step 3: 做最小兼容实现并重新验证**

Run: `.venv\Scripts\python.exe -m pytest backend\tests\unit\test_tts_service.py backend\tests\integration\test_tts_router.py -v`
Expected: PASS。

### Task 4: 同步前端设计文档并完成接口验收

**Files:**
- Modify: `docs/superpowers/specs/frontend-ui-design-spec.md`

- [ ] **Step 1: 将文档中的模型管理接口改为后端真实接口**

```text
GET /v1/voices
GET /v1/voices/{voice_name}
POST /v1/voices/upload
DELETE /v1/voices/{voice_name}
POST /v1/voices/reload
```

- [ ] **Step 2: 更新上传交互说明，补足完整 voice 所需元数据**

```text
上传需要同时提供 gpt/sovits 文件、参考音频、参考文本、参考语言与可选默认参数。
```

- [ ] **Step 3: 运行完整接口验证**

Run: `.venv\Scripts\python.exe -m pytest backend\tests\integration\test_health_router.py backend\tests\integration\test_voices_router.py backend\tests\integration\test_tts_router.py backend\tests\unit\test_voice_repository.py backend\tests\unit\test_tts_service.py -v`
Expected: PASS。
