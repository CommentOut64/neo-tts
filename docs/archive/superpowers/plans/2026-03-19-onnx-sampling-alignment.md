# ONNX Sampling Alignment Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修正 ONNX 推理链路中 `top_k` 采样未生效的问题，并重新跑同一段 Neuro1 基准，比较音频时长、耗时和主观音质是否更贴近 PyTorch。

**Architecture:** 保持现有 ONNX 推理架构不变，只在 [`run_onnx_inference.py`](f:/GPT-SoVITS_minimal_inference-master/run_onnx_inference.py) 中做最小修改：让 `sample_topk()` 真正裁剪候选集合，并把 `infer()` 的 `top_k` 传入采样函数。使用轻量单元测试锁住回归，再重跑与上轮完全相同的 benchmark。

**Tech Stack:** Python 3.11, pytest, NumPy, ONNX Runtime, PowerShell

---

## Chunk 1: Regression Test

### Task 1: 为 ONNX 采样新增失败测试

**Files:**
- Create: `tests/test_onnx_sampling.py`
- Test: `tests/test_onnx_sampling.py`

- [ ] **Step 1: Write the failing test**

```python
import numpy as np
from run_onnx_inference import sample_topk

def test_sample_topk_respects_requested_top_k():
    np.random.seed(0)
    topk_values = np.array([[10.0, 9.0, 8.0, 7.0]], dtype=np.float32)
    topk_indices = np.array([[100, 200, 300, 400]], dtype=np.int64)

    seen = set()
    for _ in range(50):
        sample = sample_topk(topk_values, topk_indices, temperature=1.0, top_k=2)
        seen.add(int(sample[0, 0]))

    assert seen <= {100, 200}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python.exe -m pytest tests/test_onnx_sampling.py -q`
Expected: FAIL，因为 `sample_topk()` 还不接受 `top_k` 或不约束采样范围。

## Chunk 2: Minimal Fix

### Task 2: 让 ONNX 采样逻辑真正使用 top_k

**Files:**
- Modify: `run_onnx_inference.py`
- Test: `tests/test_onnx_sampling.py`

- [ ] **Step 1: Write minimal implementation**

目标修改：
- `sample_topk()` 增加 `top_k` 参数
- 在概率归一化前裁剪 `topk_values/topk_indices` 到前 `top_k` 个候选
- `infer()` 中两处调用都传入当前 `top_k`

- [ ] **Step 2: Run test to verify it passes**

Run: `.venv\Scripts\python.exe -m pytest tests/test_onnx_sampling.py -q`
Expected: PASS

## Chunk 3: Re-run Benchmark

### Task 3: 重新跑相同 TTS 并记录数据

**Files:**
- Create: `output/benchmarks/20260319_neuro1_compare_after_topk_fix/`

- [ ] **Step 1: 使用与上轮相同输入重跑 PyTorch 基线或复用上轮结果**

Run: 复用 `output/benchmarks/20260319_neuro1_compare/pytorch.log` 与 `pytorch_neuro1.wav`
Expected: 作为对照组不变。

- [ ] **Step 2: 重跑 ONNX**

Run: `.venv\Scripts\python.exe .\run_onnx_inference.py --onnx_dir "onnx_export\neuro1_v2pro" --bert_path "pretrained_models\chinese-roberta-wwm-ext-large" --ref_audio "pretrained_models\neuro1_ref.wav" --ref_text "Then tomorrow we can celebrate her birthday, and maybe even get her a lava lamp." --ref_lang en --text "<cleaned test text>" --lang zh --output ".\output\benchmarks\20260319_neuro1_compare_after_topk_fix\onnx_neuro1.wav" --pause_length 0.3`
Expected: 成功生成新音频和日志。

- [ ] **Step 3: 提取并对比关键指标**

记录：
- 总推理时间
- 首段延迟
- GPT tokens/s
- 输出音频时长
- RTF

Expected: 若根因判断正确，ONNX 结果应更接近 PyTorch，尤其是输出音频时长和总耗时应收敛。
