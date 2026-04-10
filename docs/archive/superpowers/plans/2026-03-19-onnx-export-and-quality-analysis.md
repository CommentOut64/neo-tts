# ONNX Export And Quality Analysis Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 导出本地 `Neuro1` 的 GPT/SoVITS 相关 ONNX 模型，记录导出前后关键指标，并分析 ONNX 图与数值输出是否存在算子语义破坏。

**Architecture:** 复用仓库现有 [`export_onnx.py`](f:/GPT-SoVITS_minimal_inference-master/export_onnx.py) 与 [`onnx_validation.py`](f:/GPT-SoVITS_minimal_inference-master/onnx_validation.py) 作为主链路，先拿到可执行结果与校验报告，再基于 ONNX 图做静态分析。若出现局部兼容性问题，仅做最小修补，避免先行重构。

**Tech Stack:** Python 3.11, PyTorch 2.6, ONNX, ONNX Runtime, PowerShell, ripgrep

---

## Chunk 1: Baseline And Environment

### Task 1: 记录环境与模型基线

**Files:**
- Modify: `README.md`（如后续需要补充说明）
- Create: `onnx_export/neuro1_v2pro/metrics/baseline_metrics.json`

- [ ] **Step 1: 记录 Python 与依赖版本**

Run: `.venv\Scripts\python.exe -c "import sys, torch, transformers, onnx, onnxruntime; print(sys.version); print(torch.__version__); print(transformers.__version__); print(onnx.__version__); print(onnxruntime.__version__)"`
Expected: 成功输出版本信息。

- [ ] **Step 2: 记录本地权重基线**

Run: `Get-ChildItem .\pretrained_models -Recurse -File -Include *.ckpt,*.pth,*.pt | Select-Object FullName,Length`
Expected: 成功列出 GPT、SoVITS、SV、BERT、CNHubert 权重与大小。

- [ ] **Step 3: 记录 SoVITS 版本识别结果**

Run: `.venv\Scripts\python.exe -c "from GPT_SoVITS.process_ckpt import get_sovits_version_from_path_fast; print(get_sovits_version_from_path_fast(r'pretrained_models/SoVITS_weights_v2Pro/Neuro1_e8_s400.pth'))"`
Expected: 输出模型版本识别元组。

## Chunk 2: Export And Validation

### Task 2: 执行 ONNX 导出

**Files:**
- Modify: `export_onnx.py`（仅在导出失败且可局部修补时）
- Create: `onnx_export/neuro1_v2pro/*.onnx`
- Create: `onnx_export/neuro1_v2pro/config.json`

- [ ] **Step 1: 先直接运行现有导出命令**

Run: `.venv\Scripts\python.exe .\export_onnx.py --gpt_path "pretrained_models\GPT_weights_v2Pro\Neuro1-e5.ckpt" --sovits_path "pretrained_models\SoVITS_weights_v2Pro\Neuro1_e8_s400.pth" --cnhubert_base_path "pretrained_models\chinese-hubert-base" --bert_path "pretrained_models\chinese-roberta-wwm-ext-large" --output_dir "onnx_export\neuro1_v2pro" --max_len 1000 --validate --validation_device cpu`
Expected: 导出 `ssl.onnx`、`bert.onnx`、`vq_encoder.onnx`、`gpt_encoder.onnx`、`gpt_step.onnx`、`sovits.onnx`、`spectrogram.onnx`、`sv_embedding.onnx`，并生成校验摘要。

- [ ] **Step 2: 如果失败，定位失败阶段**

Run: `rg -n "Exporting|校验模型|❌|Traceback|RuntimeError" onnx_export\neuro1_v2pro\*`
Expected: 能定位失败模块。

- [ ] **Step 3: 仅在必要时做最小修补并重跑**

Run: 重复 Step 1
Expected: 至少完成 GPT/SoVITS 主链路导出，失败点有明确归因。

### Task 3: 保存导出校验结果

**Files:**
- Create: `onnx_export/neuro1_v2pro/metrics/export_summary.json`
- Create: `onnx_export/neuro1_v2pro/validation_report.json`（由现有脚本生成或保留）

- [ ] **Step 1: 收集 ONNX 文件大小**

Run: `Get-ChildItem .\onnx_export\neuro1_v2pro\*.onnx | Select-Object Name,Length`
Expected: 每个 ONNX 模型都有文件大小记录。

- [ ] **Step 2: 收集验证报告**

Run: `Get-Content .\onnx_export\neuro1_v2pro\validation_report.json`
Expected: 能读到各模块误差指标，尤其是 `max_abs_diff`、`mean_abs_diff`、`cosine_similarity`。

## Chunk 3: ONNX Operator Analysis

### Task 4: 分析 ONNX 图与潜在算子破坏

**Files:**
- Create: `onnx_export/neuro1_v2pro/metrics/onnx_operator_analysis.json`

- [ ] **Step 1: 统计各 ONNX 图的算子类型与数量**

Run: `.venv\Scripts\python.exe -c "import json, onnx, collections, pathlib; root=pathlib.Path(r'onnx_export/neuro1_v2pro'); out={};\nfor p in root.glob('*.onnx'):\n m=onnx.load(str(p)); c=collections.Counter(n.op_type for n in m.graph.node); out[p.name]={'op_count':sum(c.values()),'ops':dict(sorted(c.items()))};\nprint(json.dumps(out, ensure_ascii=False, indent=2))"`
Expected: 输出每个 ONNX 文件的算子分布。

- [ ] **Step 2: 重点检查高风险算子**

Run: `.venv\Scripts\python.exe -c "import json, onnx, pathlib; risk={'Loop','If','Scan','NonZero','TopK','ScatterND','GridSample','STFT'}; root=pathlib.Path(r'onnx_export/neuro1_v2pro');\nfor p in root.glob('*.onnx'):\n m=onnx.load(str(p)); ops=sorted({n.op_type for n in m.graph.node}); print(p.name, [x for x in ops if x in risk])"`
Expected: 得到高风险算子清单。

- [ ] **Step 3: 结合验证报告判断是否存在“算子破坏”**

Expected: 若 ONNX 可运行且输出误差在可接受范围，视为“未发现明显语义破坏”；若形状错误、ORT 无法执行、误差异常放大，则标记为“疑似算子破坏”。

## Chunk 4: TTS Quality Proxy Metrics

### Task 5: 形成可用于后续语音质量对比的指标结论

**Files:**
- Create: `onnx_export/neuro1_v2pro/metrics/tts_quality_notes.md`

- [ ] **Step 1: 总结可落地的客观指标**

Expected: 输出 `WER/CER`、说话人相似度、MCD、F0 RMSE、时长偏差、响度/静音比例 等说明。

- [ ] **Step 2: 给出本仓库当前最现实的对比方案**

Expected: 说明在没有严格真值语音的前提下，优先用 `ASR 回写 + SV 相似度 + ONNX/PyTorch 中间张量误差 + RTF` 作为代理指标。
