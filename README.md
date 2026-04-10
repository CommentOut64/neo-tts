# Neo TTS

> **基于 GPT-SoVITS 的推理和编辑工具。**

> 围绕长文本生成、逐段编辑、局部重推理和导出的一套完整工作流。

![License](https://img.shields.io/badge/license-MIT-blue.svg)
![Status](https://img.shields.io/badge/status-active%20development-orange.svg)

## 功能特点

### 核心亮点

- **完整工作流**：从输入文本、选择音色、生成首版语音，到进入工作区逐段修改、按需重做、最终导出，TTS主流水线已完整实现
- **高精度段切分**：可独立管理语音段，为每段维护独立顺序、版本和时间线位置，便于长文本逐段修正
- **完整编辑能力**：支持插入、追加、修改、删除、交换位置和区间重排
- **段级重推理**：可以只重做单个段，或只重做本次修改真正影响到的目标集合，避免每次小改动都整篇重跑
- **停顿可调**：相邻语音段之间的停顿时长可以单独调整
- **Overlap 边界控制**：智能交叉淡化允许段间保持自然的气息连贯
- **高效的编辑体验**：可播放、可选段、可切换布局、可持续修改

### 工作区能力

- **双布局工作区**：同一份文本可以在列表式与组合式两种视图之间切换，兼顾逐段操作和整体排布观察
- **文本标准化与句末标点控制**：输入页预览、工作区编辑和正式生成统一按句尾胶囊方案组织，句尾信息、显示文本和实际生成文本分层处理，面向长文本场景保持一致口径
- **段级参数调整**：生成参数支持会话级、组级、段级和批量段级调整，可覆盖语速、`top_k`、`top_p`、`temperature`、`noise_scale` 以及参考音频与参考文本
- **段级模型切换**：音色和模型绑定支持会话级、组级、段级和批量段级切换，允许在一次编辑中使用多种模型/音色
- **统一播放结构**：支持点击跳转和定位高亮，文本与音频高度绑定

### 生产能力

- **多种导出方式**：支持整条成品导出和分段导出，同时覆盖最终交付和素材回收场景
- **模型导入与集中管理**：支持查看现有音色、刷新配置、上传托管模型、删除托管模型；静态配置音色与托管音色可以共存

## 系统要求

### 基础环境

- **操作系统**：Windows 10 / 11
- **GPU**：NVIDIA GPU（显存要求因模型而异，具体请参照官方说明；8GB 显存可轻松跑 V2Pro）

## 快速开始

### 1. 安装后端依赖

```powershell
uv sync --group dev
```

### 2. 安装前端依赖

```powershell
Set-Location frontend
npm install
Set-Location ..
```

### 3. 准备模型与音色配置

编辑 [config/voices.json](config/voices.json)，最小结构如下：

```json
{
  "voice_id": {
    "gpt_path": "pretrained_models/GPT_weights/model.ckpt",
    "sovits_path": "pretrained_models/SoVITS_weights/model.pth",
    "ref_audio": "pretrained_models/reference.wav",
    "ref_text": "参考音频对应文本",
    "ref_lang": "zh",
    "description": "音色描述",
    "defaults": {
      "speed": 1.0,
      "top_k": 15,
      "top_p": 1.0,
      "temperature": 1.0,
      "pause_length": 0.3
    }
  }
}
```

说明：

- 手动维护的静态音色由 `config/voices.json` 管理
- 上传到管理页的托管音色会写入 `storage/managed_voices/`

### 4. 启动后端

```powershell
uv run python -m backend.app.cli --port 8000
```

### 5. 启动前端

```powershell
Set-Location frontend
npm run dev
```

### 6. 打开页面

- 前端开发地址：`http://127.0.0.1:5175`
- 后端接口文档：`http://127.0.0.1:8000/docs`

### 7. 一键开发启动

仓库提供了 `start_dev.bat`：

```powershell
.\start_dev.bat
```

它会完成以下操作：

- 检查 `.venv\Scripts\python.exe`
- 启动后端到 `8000`
- 在 `frontend/` 下启动前端开发服务器

## 技术栈

### 后端

- **Python**
- **FastAPI**
- **Pydantic**
- **Uvicorn**

### 前端

- **TypeScript**
- **Vue 3**
- **Vite**
- **Vue Router**
- **Element Plus**
- **Nuxt UI**

### 推理与文本处理

- **GPT-SoVITS**
- **PyTorch**
- **CNHubert**
- **BERT / transformers**
- **多语言文本处理依赖**：`pypinyin`、`opencc`、`pyopenjtalk`、`g2p_en`、`g2pk2`、`ToJyutping` 等

## 核心架构

### 产品结构

- **输入页**：负责准备全文、导入文件、维护输入稿，并把初始化参数送入正式生成流程
- **工作区**：负责后续正式编辑，包括段文本修改、停顿调整、参数补丁、模型切换、局部重推理、播放与导出
- **模型管理页**：负责查看、上传、删除和刷新音色配置

### 会话与版本结构

- 当前主线围绕 `edit-session` 组织
- 一次初始化会创建活动会话，并进入异步生成流程
- 每次正式提交都会生成新的 `document_version`
- 正式结果同时维护全文、段列表、边列表和时间线对象
- 导出基于指定版本进行，不会隐式改变当前正式版本

这套结构的目标不是把所有状态都压成一次同步请求，而是把长文本生成拆成可持续编辑、可恢复和可导出的正式工作流。

### 段与边的编辑模型

- **段** 是当前系统的核心编辑单元，维护文本、顺序、语言、版本、正式音频资产和段级覆盖项
- **边** 负责描述相邻段之间的停顿与拼接方式，维护 `pause_duration_seconds` 与 `boundary_strategy`
- 当前边界策略默认支持：
  - `latent_overlap_then_equal_power_crossfade`
  - `crossfade`
  - `hard_cut`
- 当左右相邻段使用不同音色或不同模型时，系统会把边界策略解析为兼容的 `crossfade_only`

这使得“段内内容”和“段间衔接”可以分别控制，而不是把所有变化都揉进一次整条音频重算。

### 参数与模型绑定层级

- **渲染参数** 支持会话级、组级、段级和批量段级
- **音色/模型绑定** 同样支持会话级、组级、段级和批量段级
- 段级参数可以覆盖语速、采样参数、噪声参数、参考音频、参考文本和参考语言
- 段级模型绑定可以覆盖 `voice_id`、`model_key`、`gpt_path`、`sovits_path`

因此，同一篇文档内部可以形成细粒度的参数差异和模型差异，而不需要强制所有段共享一套完全相同的配置。

### 推理运行时结构

- 推理主线采用 PyTorch-first 的 GPT-SoVITS 运行时
- 模型引擎按 `gpt_path + sovits_path` 维度缓存，避免重复初始化
- 文本、参考音频、参数配置和模型绑定会在正式生成前被解析成统一的渲染上下文
- 正式段资产、边界资产和时间线装配结果分别持久化，供播放、重推理和导出复用

### 导出与资产组织

- 分段导出与整条导出是两个独立入口
- 正式段资产、边界资产、块资产、整条 composition 和临时 preview 音频分开管理
- 工作区播放依赖正式时间线，而不是仅依赖零散的段音频返回值


## 项目结构

```text
neo-tts/
├─ backend/
│  ├─ app/
│  │  ├─ api/               # FastAPI 路由
│  │  ├─ core/              # settings、lifespan、日志、异常
│  │  ├─ inference/         # GPT-SoVITS 推理运行时
│  │  ├─ repositories/      # voice / edit-session 存储访问
│  │  ├─ schemas/           # Pydantic schema
│  │  └─ services/          # segment、edge、render、timeline、export 核心服务
│  └─ tests/                # 单元、集成、E2E 测试
├─ frontend/
│  ├─ src/
│  │  ├─ api/               # 前端 API client
│  │  ├─ components/        # 输入页、工作区、模型管理组件
│  │  ├─ composables/       # 状态与工作流逻辑
│  │  ├─ router/            # 路由
│  │  ├─ utils/             # 文本与编辑辅助
│  │  └─ views/             # TextInput / Workspace / Studio / VoiceAdmin
│  └─ tests/                # 前端行为测试
├─ GPT_SoVITS/              # 上游模型与文本处理代码
├─ config/                  # 音色配置
├─ storage/                 # 托管音色、结果与会话资产
├─ docs/                    # 接口与系统文档
├─ devdoc/                  # 分版本设计方案
├─ llmdoc/                  # 局部实现说明
├─ legacy/                  # 归档旧入口
└─ start_dev.bat            # Windows 开发启动脚本
```

## 开源协议

本项目使用 [MIT License](LICENSE)。
