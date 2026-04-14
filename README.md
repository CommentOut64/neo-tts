# Neo TTS

> **基于 GPT-SoVITS 的段级可编辑语音合成工作站**

传统的长文本语音合成工具往往以“整篇一次性生成”为主要运行模式，一旦需要修改其中的某句拼音或参数，往往需要对整篇内容重新推理，耗时且难以微调。Neo TTS 围绕这一痛点重新设计了底层架构：将长文本拆分为独立管理的语音段，每段可进行独立推理、编辑和局部重绘，并通过底层的边界融合算法保持段间声学特征的自然衔接，最终高效组装为完整的音频导出。

![License](https://img.shields.io/badge/license-Apache--2.0-blue.svg)
![Version](https://img.shields.io/badge/version-v0.0.1-brightgreen.svg)
![Vue](https://img.shields.io/badge/Vue-3.5+-4FC08D?logo=vue.js&logoColor=white)
![Python](https://img.shields.io/badge/Python-3.11+-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688?logo=fastapi&logoColor=white)
[![GPT-SoVITS](https://img.shields.io/badge/GPT--SoVITS-v2%2Fv2Pro-6A5ACD)](https://github.com/RVC-Boss/GPT-SoVITS)

<p align="center">
  <img src="assets/main1.png" width="100%" />
</p>


## 产品特性

### 段级编辑与局部重推理

像编辑文本一样编辑语音。支持对独立段落进行插入、修改、删除和位置重排。每次编辑仅重新渲染受影响的最小片段（目标段与相邻边界），从此告别漫长的整篇重推等待。

### 丝滑的段落衔接控制

相邻段之间的停顿时长不仅可精准调节，系统还在底层支持声学特征的交叉融合，无需手动对齐音频波形，即可自动处理句子间的平滑过渡，确保听感自然不断层。

### 多音色与参数混合编排

在同一篇文档中，支持为不同的段落绑定不同的音色，并独立调控语速、参考和生成参数。复杂的角色对话场面也能在一个工程界面中轻松组织。

### 灵活的工作区双视图

引入双视图协作模式。**列表视图**专注于单句的精细化修改与反复打磨；**组合视图**提供类似富文本的整体排版体验。工作区内置语法高亮与拖拽重排功能。

### 毫秒级视听反馈

内置高性能流媒体播放器，精准同步波形可视化与当前播放游标。支持点击段落直接跳转播放、拖拉进度条实时跟随，做到所见即所听。

### 配音与字幕一键生成

完美适配解说与二创剪辑场景。只需将视频长文稿输入工作站，不仅能全自动生成 AI 配音，更能导出极高匹配度的段级关联字幕文件。简化后期打轴对齐工作，助力音视频管线效率最大化。

## 快速上手

我们提供免配置的开箱即用版本。
- **系统要求**：Windows 10 / 11
- **硬件要求**：NVIDIA GPU（建议 8GB 显存以上以运行 V2Pro 模型）；至少 8GB 磁盘空间。
- **获取方式**：请前往项目的 Release 页面使用链接下载对应的 `.zip` 便携包，解压后双击 `NeoTTS.exe` 即可运行。

## 重要提醒

- **仅专注推理与编辑**：Neo TTS 是一个专注声音推理生成、组合编辑与精修的后期工作站，**不包含**任何模型训练或微调模块。您可以使用打包好的内置模型，或自行导入符合规范的模型；如需训练或微调新的音色模型，请移步至 [GPT-SoVITS 官方仓库](https://github.com/RVC-Boss/GPT-SoVITS)。
- **模型版本限制**：当前项目的底层推理引擎仅严格适配 **GPT-SoVITS v2 / v2Pro** 版本模型，暂不支持 v3 / v4 等新版模型。

---

## 核心技术

Neo TTS 在工程实现层面进行了大量重构与创新，旨在解决超长文本 TTS 的调度困境与视听局部割裂感。

### Latent Overlap 边界增强

传统的音频拼接手段多采用波形级的交叉淡化（Cross-fade），但不同句子的波尾与波头强行叠加容易出现相位抵消或突兀的频率割裂。
Neo TTS 深度定制了内部的推理管线，在 GPT-SoVITS 的解码阶段保留了左段音频的有效隐空间特征（Latent Frame），将其作为“声学上下文”注入下一段的前缀生成中。这使得在模型底层直接生成了带有自然过渡语气的波形。

### 基于会话快照的最小化重绘机制
Neo TTS 将整个文档抽象为由 **Segment（段）** 与 **Edge（边）** 构成的拓扑图结构。
每次对文档的修改（如切分语句、更换参数）都会生成全新的数据快照。后端的 `RenderPlanner` 引擎会高频对比修改前后的快照差异，精准剥离出本次操作波及的“最小改动半径”（即被修改的语句本身以及受直接影响的相邻过渡带），仅对这部分发起热重载更新，极大地提升了二次编辑的响应速度。

### 分层音频组装与真源流媒体时间线
如果将长达几十分钟的音频直接合成为单一超大文件或压入内存，不仅渲染阻塞，前端的进度条拖放操作也会变得迟缓卡顿。
Neo TTS 创新出 `段落(Segment) -> 分块(Block) -> 全局时间线(Timeline)` 的三级数据级联架构。后端自动根据时间阈值将音频切片打包分块；前端则重构了基于 Web Audio API 的底层缓冲调度器，实现按需流式加载。统一的时间线管理器能够将底层混音调度时刻逆向映射回 DOM 树内的具体文本节点，实现复杂混排场景下的声画严格同步与毫秒级 Seek。

## 技术栈

| 层 | 技术 |
|---|---|
| 后端 | Python 3.11、FastAPI、Pydantic、Uvicorn |
| 前端 | TypeScript、Vue 3、Vite、Tiptap、Element Plus、Nuxt UI |
| 推理 | GPT-SoVITS（PyTorch）、CNHubert、BERT / transformers |
| 多语言 | pypinyin、opencc、pyopenjtalk、g2p_en、g2pk2、ToJyutping |

## 本地开发部署

如果您希望基于源码进行二次开发，请确保已经准备好 Node.js (18+)、Python (3.11)、包管理器 `uv`，以及项目根目录下可用的 `launcher-dev.exe`。

```powershell
# 1. 安装后端依赖
uv sync --group dev

# 2. 安装前端依赖
cd frontend
npm install
cd ..

# 3. 启动本地开发全栈服务（在项目根目录执行）
.\launcher-dev.exe --runtime-mode dev --frontend-mode web
```
启动成功后，您可以通过以下地址访问：
- **开发界面**：`http://localhost:5175`
- **接口文档**：`http://127.0.0.1:18600/docs`

> **Note**: 首次本地启动前，需要预配基础声学模型权重，请参阅 `config/voices.json` 中的各路径指向结构进行存放。

## 开源协议

本项目使用 [Apache-2.0 license](LICENSE)。

## 致谢

- [GPT-SoVITS](https://github.com/RVC-Boss/GPT-SoVITS)：本项目的核心语音推理能力基于该开源项目构建，感谢其团队与社区的持续贡献。
