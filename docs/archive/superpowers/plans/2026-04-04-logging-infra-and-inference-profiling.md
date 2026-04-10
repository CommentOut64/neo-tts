# Logging Infra And Inference Profiling Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为后端建立统一的 Loguru 日志基础设施，并为 TTS 推理前链路补充可落盘的分段耗时日志，定位 `Loading models on cuda` 之前的耗时。

**Architecture:** 在 `backend.app.core.logging` 内集中配置 Loguru 的控制台与文件 sinks，并通过标准库 `logging` 拦截把旧 logger 收口到同一输出。TTS 路由、模型缓存与推理实现改用按模块绑定的 logger，记录请求前链路、首次模块导入、模型初始化和 warmup 的关键耗时点。

**Tech Stack:** Python 3.11, FastAPI, Loguru, pytest

---

### Task 1: 日志基建测试先行

**Files:**
- Modify: `backend/tests/unit/test_runtime_entrypoints.py`
- Create: `backend/tests/unit/test_logging_setup.py`

- [ ] **Step 1: 写失败测试，约束日志目录、级别、格式与标准 logging 接管**
- [ ] **Step 2: 运行日志相关单测，确认当前实现失败**

### Task 2: 接入 Loguru 基础设施

**Files:**
- Modify: `backend/app/core/logging.py`
- Modify: `backend/app/main.py`
- Modify: `pyproject.toml`

- [ ] **Step 1: 实现 Loguru 初始化、按天轮转、14 天保留、控制台/文件双 sink**
- [ ] **Step 2: 接管标准库 logging，并提供按模块绑定 logger 的辅助方法**
- [ ] **Step 3: 运行单测，确认日志基建通过**

### Task 3: 替换后端关键日志并补推理分段耗时

**Files:**
- Modify: `backend/app/api/routers/tts.py`
- Modify: `backend/app/inference/model_cache.py`
- Modify: `backend/app/inference/engine.py`
- Modify: `backend/app/inference/pytorch_optimized.py`
- Modify: `backend/tests/integration/test_tts_router.py`

- [ ] **Step 1: 先写/补失败测试，约束 TTS 前链路关键日志存在**
- [ ] **Step 2: 把关键 `print`/`logging` 替换为 Loguru，并记录请求解析、临时文件写盘、model cache、runtime import、模型加载、warmup、推理摘要的日志**
- [ ] **Step 3: 运行相关单测与集成测试，确认日志与行为都正确**

### Task 4: 最终验证

**Files:**
- Modify: `llmdoc/` 或相关文档（仅在代码事实与文档不一致时）

- [ ] **Step 1: 运行本次改动相关的 pytest 命令**
- [ ] **Step 2: 如发现文档已过时，同步重写对应文档**
- [ ] **Step 3: 汇总验证结果与剩余风险**
