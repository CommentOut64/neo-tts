# Neuro1 TTS Benchmark Report

## 基准输入

- 参考音频: `pretrained_models/neuro1_ref.wav`
- 参考文本: `Then tomorrow we can celebrate her birthday, and maybe even get her a lava lamp.`
- 参考语言: `en`
- 目标文本: `test.txt` 去空行并合并为空格分隔单段文本
- 目标语言: `zh`
- 清洗后文本长度: `1692` 字符

## 结果总览

| 模式 | 状态 | 输出音频 | 首段延迟 | 总推理时间 | 墙钟时间 | 输出音频时长 | RTF | GPT tokens/s |
|---|---|---|---:|---:|---:|---:|---:|---:|
| PyTorch | 成功 | `pytorch_neuro1.wav` | 4.098s | 68.031s | 86.174s | 330.220s | 0.2060 | 137.25 |
| ONNX | 成功 | `onnx_neuro1.wav` | 2.252s | 84.964s | 103.321s | 370.860s | 0.2291 | 128.93 |
| TensorRT | 失败 | 无 | - | - | 0.300s | - | - | - |

## 细项

### PyTorch

- Reference Processing: `3.123s`
- Target Text Cleaning: `1.616s`
- GPT Semantic Gen: `57.800s`
- SoVITS Audio Decode: `5.414s`
- 输出: `pytorch_neuro1.wav`
- 输出格式: `WAV / PCM_16 / 32000 Hz / mono`
- 输出大小: `21,134,124 bytes`

### ONNX

- Reference Processing: `1.063s`
- Target Text Cleaning: `1.630s`
- GPT Semantic Gen: `70.148s`
- SoVITS Audio Decode: `11.943s`
- 输出: `onnx_neuro1.wav`
- 输出格式: `WAV / PCM_16 / 32000 Hz / mono`
- 输出大小: `23,735,084 bytes`
- 观察: 输出音频时长比 PyTorch 长 `40.64s`，Shape Profile 里 `gpt_step.generated_tokens max = 1500`，说明至少有一段命中了步进解码上限，结果不能视作与 PyTorch 完全同分布。

### TensorRT

- 执行命令后直接失败
- 错误: `ModuleNotFoundError: No module named 'tensorrt'`
- 当前环境未安装 TensorRT Python 包，也没有现成 `.engine` 产物

## 当前可得结论

- 在本机当前环境下，`PyTorch` 这次比 `ONNX` 更快，`RTF` 更低。
- `ONNX` 的首段延迟更低，但整句总耗时和 SoVITS 解码耗时都更高。
- `TensorRT` 当前不具备运行条件，因此本轮无法纳入速度对比。
- 由于推理过程含采样，且 ONNX 至少有一段命中 `1500` token 上限，本轮数据适合做“当前工程落地表现”对比，不适合当作严格的逐 token 公平基准。

## 相关文件

- `input_text_cleaned.txt`
- `pytorch.log`
- `onnx.log`
- `trt.log`
- `summary.json`
- `pytorch_neuro1.wav`
- `onnx_neuro1.wav`
