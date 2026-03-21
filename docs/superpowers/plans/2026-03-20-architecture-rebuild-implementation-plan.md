# Architecture Rebuild Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 以现有仓库为基础，完成 PyTorch 推理内核统一、FastAPI 标准化重构、Vue 前端接入，以及 ONNX/TensorRT 体系退场，最终形成可持续维护的新架构。

**Architecture:** 采用“双轨迁移”策略。先保留 [run_optimized_inference.py](f:/GPT-SoVITS_minimal_inference-master/run_optimized_inference.py) 与 [api_server.py](f:/GPT-SoVITS_minimal_inference-master/api_server.py) 作为迁移基线，在 `backend/app` 中抽离新的 PyTorch 推理内核与标准 FastAPI 分层，再在 `frontend/` 中建设 Vue 3 单页应用，待新链路稳定后删除 ONNX/TensorRT 入口与相关依赖。整个过程以最小闭环推进，优先建立回归测试和基线验证，再做结构迁移。

**Tech Stack:** Python 3.11, FastAPI, Pydantic v2, PyTorch, Transformers, pytest, Vue 3, Vite, TypeScript, Pinia, Vue Router, npm, PowerShell

---

## Planned File Map

### New Backend Files

- `backend/app/main.py`
- `backend/app/api/router.py`
- `backend/app/api/routers/health.py`
- `backend/app/api/routers/tts.py`
- `backend/app/api/routers/voices.py`
- `backend/app/core/settings.py`
- `backend/app/core/logging.py`
- `backend/app/core/lifespan.py`
- `backend/app/core/exceptions.py`
- `backend/app/schemas/tts.py`
- `backend/app/schemas/voice.py`
- `backend/app/services/tts_service.py`
- `backend/app/services/voice_service.py`
- `backend/app/repositories/voice_repository.py`
- `backend/app/inference/engine.py`
- `backend/app/inference/model_cache.py`
- `backend/app/inference/text_processing.py`
- `backend/app/inference/audio_processing.py`
- `backend/app/inference/pipeline.py`
- `backend/app/inference/types.py`
- `backend/app/cli.py`
- `backend/tests/conftest.py`
- `backend/tests/unit/test_voice_repository.py`
- `backend/tests/unit/test_tts_service.py`
- `backend/tests/integration/test_health_router.py`
- `backend/tests/integration/test_voices_router.py`
- `backend/tests/integration/test_tts_router.py`

### New Frontend Files

- `frontend/package.json`
- `frontend/vite.config.ts`
- `frontend/tsconfig.json`
- `frontend/index.html`
- `frontend/src/main.ts`
- `frontend/src/App.vue`
- `frontend/src/router/index.ts`
- `frontend/src/stores/tts.ts`
- `frontend/src/api/http.ts`
- `frontend/src/api/tts.ts`
- `frontend/src/types/tts.ts`
- `frontend/src/views/TtsStudioView.vue`
- `frontend/src/views/VoiceAdminView.vue`
- `frontend/src/components/TtsForm.vue`
- `frontend/src/components/VoiceSelect.vue`
- `frontend/src/components/AudioResultPanel.vue`
- `frontend/src/components/InferenceSettingsPanel.vue`
- `frontend/src/assets/styles.css`

### Existing Files To Modify

- [pyproject.toml](f:/GPT-SoVITS_minimal_inference-master/pyproject.toml)
- [requirements.txt](f:/GPT-SoVITS_minimal_inference-master/requirements.txt)
- [config/voices.json](f:/GPT-SoVITS_minimal_inference-master/config/voices.json)
- [api_server.py](f:/GPT-SoVITS_minimal_inference-master/api_server.py)
- [run_optimized_inference.py](f:/GPT-SoVITS_minimal_inference-master/run_optimized_inference.py)
- [README.md](f:/GPT-SoVITS_minimal_inference-master/README.md)
- [README_zh.md](f:/GPT-SoVITS_minimal_inference-master/README_zh.md)
- [docs/superpowers/specs/2026-03-20-architecture-rebuild-design.md](f:/GPT-SoVITS_minimal_inference-master/docs/superpowers/specs/2026-03-20-architecture-rebuild-design.md)

### Legacy Baseline Files To Keep Until Final Cutover

- [run_inference.py](f:/GPT-SoVITS_minimal_inference-master/run_inference.py)
- [run_long_inference.py](f:/GPT-SoVITS_minimal_inference-master/run_long_inference.py)
- [run_streaming_inference.py](f:/GPT-SoVITS_minimal_inference-master/run_streaming_inference.py)
- [run_optimized_inference.py](f:/GPT-SoVITS_minimal_inference-master/run_optimized_inference.py)
- [api_server.py](f:/GPT-SoVITS_minimal_inference-master/api_server.py)

### Retirement Candidates For Final Cleanup

- [api_server_onnx.py](f:/GPT-SoVITS_minimal_inference-master/api_server_onnx.py)
- [api_server_trt.py](f:/GPT-SoVITS_minimal_inference-master/api_server_trt.py)
- [run_onnx_inference.py](f:/GPT-SoVITS_minimal_inference-master/run_onnx_inference.py)
- [run_onnx_long_inference.py](f:/GPT-SoVITS_minimal_inference-master/run_onnx_long_inference.py)
- [run_onnx_streaming_inference.py](f:/GPT-SoVITS_minimal_inference-master/run_onnx_streaming_inference.py)
- [run_trt_inference.py](f:/GPT-SoVITS_minimal_inference-master/run_trt_inference.py)
- [export_onnx.py](f:/GPT-SoVITS_minimal_inference-master/export_onnx.py)
- [onnx_to_fp16.py](f:/GPT-SoVITS_minimal_inference-master/onnx_to_fp16.py)
- [onnx_validation.py](f:/GPT-SoVITS_minimal_inference-master/onnx_validation.py)
- [onnx2trt.py](f:/GPT-SoVITS_minimal_inference-master/onnx2trt.py)
- `onnx_export/` 下仅服务于 ONNX/TRT 推理的导出产物和说明

> 注：本仓库遵循 `commit` 由用户手动执行的规则，实施过程中不要自动提交。

## Chunk 1: Baseline And Migration Guardrails

### Task 1: 建立迁移基线与目录脚手架

**Files:**
- Create: `backend/app/`
- Create: `backend/tests/`
- Create: `frontend/`
- Modify: [README.md](f:/GPT-SoVITS_minimal_inference-master/README.md)
- Modify: [README_zh.md](f:/GPT-SoVITS_minimal_inference-master/README_zh.md)
- Modify: [docs/superpowers/specs/2026-03-20-architecture-rebuild-design.md](f:/GPT-SoVITS_minimal_inference-master/docs/superpowers/specs/2026-03-20-architecture-rebuild-design.md)

- [x] **Step 1: 记录当前可运行入口与迁移基线**

Run: `Get-ChildItem api_server*.py,run_*inference.py | Select-Object Name`
Expected: 列出当前旧入口，作为迁移阶段的对照清单。

- [x] **Step 2: 创建新目录骨架**

Run: `New-Item -ItemType Directory -Force backend\\app\\api\\routers,backend\\app\\core,backend\\app\\schemas,backend\\app\\services,backend\\app\\repositories,backend\\app\\inference,backend\\tests\\unit,backend\\tests\\integration,frontend\\src\\api,frontend\\src\\components,frontend\\src\\views,frontend\\src\\stores,frontend\\src\\router,frontend\\src\\types,frontend\\src\\assets`
Expected: 新目录全部创建成功，不影响旧脚本运行。

- [x] **Step 3: 新增迁移说明并标记旧入口为 legacy baseline**

Expected: 在 README 中明确新架构迁移状态、旧入口用途和不再扩展 ONNX/TRT 的原则。

- [x] **Step 4: 记录旧文件迁移归属表**

Expected: 在设计文档或 README 补充“旧文件 -> 新模块”的映射摘要，避免后续改动失焦。

### Task 2: 建立最小测试护栏

**Files:**
- Create: `backend/tests/conftest.py`
- Create: `backend/tests/unit/test_voice_repository.py`
- Create: `backend/tests/unit/test_tts_service.py`
- Create: `backend/tests/integration/test_health_router.py`

- [x] **Step 1: 为 voice 配置读取写第一个失败测试**

```python
def test_load_voice_profiles_from_json(tmp_path):
    ...
```

Run: `.venv\\Scripts\\python.exe -m pytest backend\\tests\\unit\\test_voice_repository.py -v`
Expected: FAIL，原因是 `voice_repository` 还不存在。

- [x] **Step 2: 为健康检查路由写失败测试**

```python
def test_health_endpoint_returns_ok():
    ...
```

Run: `.venv\\Scripts\\python.exe -m pytest backend\\tests\\integration\\test_health_router.py -v`
Expected: FAIL，原因是 `backend.app.main` 还不存在。

- [x] **Step 3: 补充测试夹具与临时配置样例**

Expected: 测试可以在不加载真实大模型的前提下验证配置和 API 结构。

## Chunk 2: Extract The Unified PyTorch Inference Kernel

### Task 3: 抽离推理领域模型与模型缓存

**Files:**
- Create: `backend/app/inference/types.py`
- Create: `backend/app/inference/model_cache.py`
- Create: `backend/app/core/settings.py`
- Modify: [run_optimized_inference.py](f:/GPT-SoVITS_minimal_inference-master/run_optimized_inference.py)

- [x] **Step 1: 为推理配置和 voice 配置定义类型**

```python
class VoiceProfile(BaseModel):
    name: str
    gpt_path: str
    sovits_path: str
```

Expected: `VoiceProfile`、`InferenceRequest`、`InferenceResult`、`ModelHandle` 等类型放入独立模块。

- [x] **Step 2: 为模型缓存写失败测试**

Run: `.venv\\Scripts\\python.exe -m pytest backend\\tests\\unit\\test_tts_service.py -v`
Expected: FAIL，原因是模型缓存与服务编排尚未实现。

- [x] **Step 3: 实现模型缓存与路径解析**

Expected: `model_cache.py` 负责模型实例复用、设备选择、warmup 触发、路径标准化，不再让 API 路由直接构造模型。

- [x] **Step 4: 将旧脚本中的模型构造逻辑迁移为可调用适配层**

Expected: [run_optimized_inference.py](f:/GPT-SoVITS_minimal_inference-master/run_optimized_inference.py) 只保留轻量 CLI/WebUI 适配，核心模型加载逻辑迁移到 `backend/app/inference/`。

### Task 4: 抽离文本处理、音频处理与统一推理流水线

**Files:**
- Create: `backend/app/inference/text_processing.py`
- Create: `backend/app/inference/audio_processing.py`
- Create: `backend/app/inference/pipeline.py`
- Create: `backend/app/inference/engine.py`
- Modify: [run_inference.py](f:/GPT-SoVITS_minimal_inference-master/run_inference.py)
- Modify: [run_long_inference.py](f:/GPT-SoVITS_minimal_inference-master/run_long_inference.py)
- Modify: [run_streaming_inference.py](f:/GPT-SoVITS_minimal_inference-master/run_streaming_inference.py)
- Modify: [run_optimized_inference.py](f:/GPT-SoVITS_minimal_inference-master/run_optimized_inference.py)

- [x] **Step 1: 把公共预处理逻辑从旧脚本提取到 `text_processing.py`**

Expected: 文本清洗、分段、语言判定、phoneme/bert 特征准备不再散落于多个脚本。

- [x] **Step 2: 把参考音频与输出拼接逻辑提取到 `audio_processing.py`**

Expected: 参考音频加载、静音拼接、流式块处理、最终 waveform 合并进入独立模块。

- [x] **Step 3: 在 `pipeline.py` 中统一长文本与流式路径**

Expected: 通过显式参数控制是否流式、是否使用 history window，而不是复制一套脚本。

- [x] **Step 4: 在 `engine.py` 暴露单一入口**

```python
class PyTorchInferenceEngine:
    def synthesize(self, request: InferenceRequest) -> InferenceResult:
        ...
```

Expected: 新后端、CLI、未来前端联调都只依赖 `PyTorchInferenceEngine`。

- [x] **Step 5: 跑最小回归测试验证迁移未破坏基础行为**

Run: `.venv\\Scripts\\python.exe -m pytest backend\\tests\\unit\\test_tts_service.py -v`
Expected: PASS，参数编排、默认值合并和服务调用链测试通过。

## Chunk 3: Rebuild The FastAPI Backend

### Task 5: 建立标准 FastAPI 应用骨架

**Files:**
- Create: `backend/app/main.py`
- Create: `backend/app/api/router.py`
- Create: `backend/app/api/routers/health.py`
- Create: `backend/app/core/logging.py`
- Create: `backend/app/core/lifespan.py`
- Create: `backend/app/core/exceptions.py`
- Modify: [pyproject.toml](f:/GPT-SoVITS_minimal_inference-master/pyproject.toml)
- Modify: [requirements.txt](f:/GPT-SoVITS_minimal_inference-master/requirements.txt)

- [x] **Step 1: 实现应用工厂与生命周期管理**

```python
def create_app() -> FastAPI:
    ...
```

Expected: `main.py` 中只做应用组装，不再直接承载业务逻辑。

- [x] **Step 2: 实现 `/health` 路由并让先前测试转绿**

Run: `.venv\\Scripts\\python.exe -m pytest backend\\tests\\integration\\test_health_router.py -v`
Expected: PASS。

- [x] **Step 3: 调整 Python 依赖定义**

Expected: 依赖开始为新后端结构服务，并为后续移除 ONNX/TRT 做准备；此阶段先不删除旧依赖，只移动为“待清理”状态。

- [x] **Step 4: 补一个本地启动命令**

Run: `.venv\\Scripts\\python.exe -m uvicorn backend.app.main:app --reload`
Expected: 新后端可启动并返回健康检查。

### Task 6: 实现 voice repository、service 与 API 路由

**Files:**
- Create: `backend/app/repositories/voice_repository.py`
- Create: `backend/app/services/voice_service.py`
- Create: `backend/app/schemas/voice.py`
- Create: `backend/app/api/routers/voices.py`
- Create: `backend/tests/integration/test_voices_router.py`
- Modify: [config/voices.json](f:/GPT-SoVITS_minimal_inference-master/config/voices.json)

- [x] **Step 1: 为 `/voices` 与 `/voices/reload` 写失败测试**

Run: `.venv\\Scripts\\python.exe -m pytest backend\\tests\\integration\\test_voices_router.py -v`
Expected: FAIL，原因是路由尚未实现。

- [x] **Step 2: 实现 `voice_repository.py`**

Expected: 负责读取 `config/voices.json`、相对路径归一化、数据校验和 reload。

- [x] **Step 3: 收敛 voice 配置结构**

Expected: 从 `voices.json` 中移除 `onnx_path`、`trt_path` 的运行时依赖，保留 `gpt_path`、`sovits_path`、`ref_audio`、`ref_text`、`ref_lang`、`defaults` 等 PyTorch 所需字段。

- [x] **Step 4: 跑测试并确认 API 行为**

Run: `.venv\\Scripts\\python.exe -m pytest backend\\tests\\unit\\test_voice_repository.py backend\\tests\\integration\\test_voices_router.py -v`
Expected: PASS。

### Task 7: 实现 TTS service 与 API 路由

**Files:**
- Create: `backend/app/schemas/tts.py`
- Create: `backend/app/services/tts_service.py`
- Create: `backend/app/api/routers/tts.py`
- Create: `backend/tests/integration/test_tts_router.py`
- Modify: [api_server.py](f:/GPT-SoVITS_minimal_inference-master/api_server.py)

- [x] **Step 1: 为 `/v1/audio/speech` 写失败测试**

Run: `.venv\\Scripts\\python.exe -m pytest backend\\tests\\integration\\test_tts_router.py -v`
Expected: FAIL，原因是 TTS 路由和 service 尚未实现。

- [x] **Step 2: 在 `tts_service.py` 中实现参数合并与引擎调用**

Expected: `speed`、`top_k`、`top_p`、`temperature`、`pause_length`、`noise_scale` 的默认值合并逻辑从旧 API 脚本迁出。

- [x] **Step 3: 实现 REST 输出与可选流式输出**

Expected: 新路由至少支持一次性音频返回；若实现流式，则采用统一的引擎生成器，不复制旧 API 分支。

- [x] **Step 4: 将旧 [api_server.py](f:/GPT-SoVITS_minimal_inference-master/api_server.py) 改成薄兼容壳或显式废弃入口**

Expected: 旧入口不再持有业务逻辑，最多转发到新应用或输出迁移提示。

- [x] **Step 5: 运行后端测试**

Run: `.venv\\Scripts\\python.exe -m pytest backend\\tests -v`
Expected: PASS。

## Chunk 4: Build And Integrate The Vue Frontend

### Task 8: 初始化 Vue 工程与 API 客户端

**Files:**
- Create: `frontend/package.json`
- Create: `frontend/vite.config.ts`
- Create: `frontend/tsconfig.json`
- Create: `frontend/index.html`
- Create: `frontend/src/main.ts`
- Create: `frontend/src/App.vue`
- Create: `frontend/src/router/index.ts`
- Create: `frontend/src/api/http.ts`
- Create: `frontend/src/api/tts.ts`
- Create: `frontend/src/types/tts.ts`

- [ ] **Step 1: 初始化 Vite Vue TS 工程**

Run: `npm create vite@latest frontend -- --template vue-ts`
Expected: 生成基础前端工程。

- [ ] **Step 2: 安装状态管理与路由**

Run: `npm install --prefix frontend pinia vue-router axios`
Expected: 依赖安装成功。

- [ ] **Step 3: 配置开发代理到 FastAPI**

Expected: `vite.config.ts` 中将 `/api` 或 `/v1` 代理到本地后端，前后端联调无需手动改跨域配置。

- [ ] **Step 4: 封装 API 客户端**

Expected: `src/api/tts.ts` 只暴露稳定的 `fetchVoices()`、`synthesizeSpeech()` 等调用，不在视图组件中直接写 HTTP 细节。

### Task 9: 实现首版 TTS 控制台页面

**Files:**
- Create: `frontend/src/stores/tts.ts`
- Create: `frontend/src/views/TtsStudioView.vue`
- Create: `frontend/src/views/VoiceAdminView.vue`
- Create: `frontend/src/components/TtsForm.vue`
- Create: `frontend/src/components/VoiceSelect.vue`
- Create: `frontend/src/components/AudioResultPanel.vue`
- Create: `frontend/src/components/InferenceSettingsPanel.vue`
- Create: `frontend/src/assets/styles.css`

- [ ] **Step 1: 实现 TTS 表单与参数面板**

Expected: 支持文本输入、voice 选择、速度/采样参数调节、提交状态展示。

- [ ] **Step 2: 实现结果面板**

Expected: 返回音频后可直接播放、下载，并展示错误信息或空状态。

- [ ] **Step 3: 实现 voice 管理页面最小版本**

Expected: 至少可以查看后端当前 voice 列表和手动触发 reload。

- [ ] **Step 4: 验证前端构建**

Run: `npm run build --prefix frontend`
Expected: PASS，生成 `frontend/dist`。

- [ ] **Step 5: 完成前后端联调**

Run: `npm run dev --prefix frontend`
Expected: 浏览器可完成一次完整语音合成流程。

## Chunk 5: Retire ONNX/TRT And Finalize Docs

### Task 10: 下线 ONNX/TensorRT 代码、依赖与文档

**Files:**
- Delete: [api_server_onnx.py](f:/GPT-SoVITS_minimal_inference-master/api_server_onnx.py)
- Delete: [api_server_trt.py](f:/GPT-SoVITS_minimal_inference-master/api_server_trt.py)
- Delete: [run_onnx_inference.py](f:/GPT-SoVITS_minimal_inference-master/run_onnx_inference.py)
- Delete: [run_onnx_long_inference.py](f:/GPT-SoVITS_minimal_inference-master/run_onnx_long_inference.py)
- Delete: [run_onnx_streaming_inference.py](f:/GPT-SoVITS_minimal_inference-master/run_onnx_streaming_inference.py)
- Delete: [run_trt_inference.py](f:/GPT-SoVITS_minimal_inference-master/run_trt_inference.py)
- Delete: [export_onnx.py](f:/GPT-SoVITS_minimal_inference-master/export_onnx.py)
- Delete: [onnx_to_fp16.py](f:/GPT-SoVITS_minimal_inference-master/onnx_to_fp16.py)
- Delete: [onnx_validation.py](f:/GPT-SoVITS_minimal_inference-master/onnx_validation.py)
- Delete: [onnx2trt.py](f:/GPT-SoVITS_minimal_inference-master/onnx2trt.py)
- Modify: [pyproject.toml](f:/GPT-SoVITS_minimal_inference-master/pyproject.toml)
- Modify: [requirements.txt](f:/GPT-SoVITS_minimal_inference-master/requirements.txt)
- Modify: [README.md](f:/GPT-SoVITS_minimal_inference-master/README.md)
- Modify: [README_zh.md](f:/GPT-SoVITS_minimal_inference-master/README_zh.md)

- [ ] **Step 1: 在新后端与新前端通过验证前，不要删除旧文件**

Expected: 只在新架构稳定后执行本任务，避免失去回归参照。

- [ ] **Step 2: 移除 ONNX/TRT 默认依赖与说明**

Expected: `pyproject.toml`、`requirements.txt`、README 中不再把 ONNX/TensorRT 作为现行主方案。

- [ ] **Step 3: 删除旧推理入口与工具脚本**

Expected: 仓库不再保留会误导为“当前主流程”的 ONNX/TRT 入口。

- [ ] **Step 4: 清理测试与产物目录**

Expected: 删除仅面向 ONNX 的测试与说明，保留必要的历史基线文件仅当它们仍用于 PyTorch 回归对照。

### Task 11: 建立最终验证基线并同步文档

**Files:**
- Modify: [README.md](f:/GPT-SoVITS_minimal_inference-master/README.md)
- Modify: [README_zh.md](f:/GPT-SoVITS_minimal_inference-master/README_zh.md)
- Modify: [docs/superpowers/specs/2026-03-20-architecture-rebuild-design.md](f:/GPT-SoVITS_minimal_inference-master/docs/superpowers/specs/2026-03-20-architecture-rebuild-design.md)
- Create: `output/benchmarks/architecture_rebuild_baseline/README.md`

- [ ] **Step 1: 跑完整后端测试**

Run: `.venv\\Scripts\\python.exe -m pytest backend\\tests -v`
Expected: PASS。

- [ ] **Step 2: 跑前端构建验证**

Run: `npm run build --prefix frontend`
Expected: PASS。

- [ ] **Step 3: 跑一次端到端手工冒烟**

Run: `.venv\\Scripts\\python.exe -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000`
Expected: 配合前端页面可完成一次语音生成、播放和下载。

- [ ] **Step 4: 记录迁移后性能基线**

Expected: 记录首包时延、RTF、输出时长、显存占用和测试输入，写入 `output/benchmarks/architecture_rebuild_baseline/README.md`。

- [ ] **Step 5: 覆写旧文档中的过时描述**

Expected: 文档只反映新架构现状，不追加“更新说明式补丁文字”，避免留下僵尸文档。

## Execution Notes

1. 实施顺序必须保持为：
   先统一 PyTorch 推理内核，再重建 FastAPI，再接入 Vue，最后清理 ONNX/TRT。

2. 不要把“结构重构”和“激进性能优化”绑在同一次提交里完成。
   先保证结构与语义稳定，再单独验证 `half`、warmup、缓存、`torch.compile` 等优化项。

3. 若在 PyTorch 多入口合并过程中发现行为分歧，优先以 [run_optimized_inference.py](f:/GPT-SoVITS_minimal_inference-master/run_optimized_inference.py) 为主链路，但要明确记录与 [run_streaming_inference.py](f:/GPT-SoVITS_minimal_inference-master/run_streaming_inference.py)、[run_long_inference.py](f:/GPT-SoVITS_minimal_inference-master/run_long_inference.py) 的差异。

4. 若需要删除大体量产物目录或重写依赖文件，先确认新架构验证已经完成，再执行清理。
