# ONNX Top-K Fix Benchmark Report

## 本轮变更

- 文件: `run_onnx_inference.py`
- 修改: 让 `sample_topk()` 真正尊重传入的 `top_k`
- 回归测试: `tests/test_onnx_sampling.py`

## 回归测试结果

- 命令: `.venv\Scripts\python.exe -m unittest discover -s tests -p test_onnx_sampling.py -v`
- 结果: `PASS`

## 与上轮 ONNX 的对比

| 指标 | 上轮 ONNX | 本轮 ONNX | 差值 |
|---|---:|---:|---:|
| 首段延迟 | 2.252s | 2.239s | -0.013s |
| GPT Semantic Gen | 70.148s | 81.813s | +11.665s |
| GPT tokens/s | 128.93 | 113.27 | -15.66 |
| SoVITS Audio Decode | 11.943s | 12.183s | +0.240s |
| 总推理时间 | 84.964s | 96.931s | +11.967s |
| 墙钟时间 | 103.321s | 115.668s | +12.347s |
| 输出音频时长 | 370.860s | 379.900s | +9.040s |
| RTF | 0.2291 | 0.2551 | +0.0260 |
| token 总数 | 7448 | 7674 | +226 |

## 结论

- 这次最小修补 **没有改善** ONNX 结果，反而让输出更长、总耗时更高。
- 说明“`top_k` 未生效”虽然是一个真实缺陷，但 **不是当前浑浊/偏慢问题的主根因**。
- 更可能的主因仍然是：
  - ONNX 与 PyTorch 的采样/停止条件整体不一致
  - ONNX 自回归循环仍然在 CPU 上做采样
  - ONNX 当前仍是 `CUDAExecutionProvider + float32`

## 相关文件

- `onnx.log`
- `onnx_neuro1.wav`
- `compare_with_previous.json`
