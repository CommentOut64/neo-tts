# GPT-SoVITS Minimal Inference 架构设计与当前状态（归档）

> Archived: 2026-04-10
> Reason:
> - 文档仍以 `TtsStudioView` 作为前端主线页面，不再代表当前 `TextInput + Workspace + legacy /studio` 的实际结构
> Current Entry:
> - `/llmdoc/overview/backend-overview.md`
> - `/llmdoc/overview/edit-session-domain-overview.md`

**日期：** 2026-03-20  
**最近同步：** 2026-04-02

## 1. 当前结论

本仓库的主线架构已经收敛完成，当前唯一后端主线为 `backend/app`，唯一前端主线为 `frontend`，唯一推理主线为 PyTorch。

旧的根目录运行脚本、ONNX/TensorRT 工具链和实验目录不再属于当前主流程，已统一归档到 `legacy/`。后续开发应默认视 `legacy/` 为历史资料区，而不是可继续演进的实现区。

## 2. 当前主线结构

```text
repo/
  backend/
    app/
      api/
      core/
      inference/
      repositories/
      schemas/
      services/
      main.py
      cli.py
    tests/
  frontend/
    src/
      api/
      components/
      composables/
      router/
      types/
      views/
  config/
  storage/
  legacy/
    root_entrypoints/
    onnx_trt/
    experiments/
    artifacts/
```

## 3. 后端职责划分

### 3.1 `backend/app/api`

负责 FastAPI 路由接入，只处理请求解析、响应返回和状态码映射。

当前主接口包括：

- 健康检查
- voice 列表 / 详情 / reload / 上传 / 删除
- TTS 合成
- 推理进度查询与 SSE 推送
- 推理残留清理
- 参数缓存读写
- 结果文件删除

### 3.2 `backend/app/services`

负责业务编排，包括：

- 语音合成请求参数合并
- voice 配置消费
- 推理运行时状态管理
- 推理参数缓存
- 合成结果文件管理

### 3.3 `backend/app/inference`

负责当前唯一的 PyTorch 推理主链路。

关键模块：

- `pytorch_optimized.py`：当前运行时实现来源
- `model_cache.py`：模型缓存与路径归一化
- `engine.py`：统一推理入口
- `pipeline.py`：推理流水线编排
- `text_processing.py`：文本切分与特征准备
- `audio_processing.py`：参考音频和输出音频处理

### 3.4 `backend/app/repositories`

负责 voice 配置读取、校验、写回、托管文件管理。

## 4. 前端状态

当前前端已经不是占位工程，而是可联调的正式界面，位于 `frontend/`。

现有主页面：

- `TtsStudioView.vue`
- `VoiceAdminView.vue`

现有关键能力：

- voice 选择与管理
- 文本输入与参数控制
- 推理进度展示
- 结果播放、下载、删除
- 参数缓存
- 主题切换

开发代理默认指向 `http://127.0.0.1:8000`。

## 5. Legacy 边界

以下内容已明确退出主线：

### 5.1 `legacy/root_entrypoints`

保存原根目录 API / PyTorch 入口，仅作历史归档，不再作为运行入口。

### 5.2 `legacy/onnx_trt`

保存 ONNX/TensorRT 相关脚本，仅作历史归档，不再承接新功能。

### 5.3 `legacy/experiments`

保存历史实验代码，不再参与当前主流程。

### 5.4 其他历史资产

`onnx_export/` 与旧 benchmark 输出目前仍保留在仓库中，视为历史参考资产，不属于当前主线。

## 6. 当前开发约束

1. 新功能默认只落在 `backend/app` 和 `frontend/`。
2. 不再新增根目录运行脚本。
3. 不再为 ONNX/TensorRT 归档代码增加新能力。
4. 需要保留的历史代码统一进入 `legacy/`，不允许重新散落回根目录。
5. 文档描述必须反映当前主线状态，不能继续以“迁移中”表述已完成部分。

## 7. 验证基线

当前主线验证命令：

```bash
python -m pytest backend/tests -q
```

```bash
cd frontend
npm run build
```

FastAPI 启动命令：

```bash
python -m backend.app.cli --host 127.0.0.1 --port 8000
```

## 8. 后续清理方向

本轮收尾后，后续若继续整理仓库，优先级如下：

1. 评估是否将 `onnx_export/` 进一步并入 `legacy/`
2. 继续收敛历史 benchmark 与输出目录
3. 在不影响当前主线的前提下，减少根目录残留的非主线文件
