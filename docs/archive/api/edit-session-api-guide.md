# Edit Session API 接入指南（归档）

> Archived: 2026-04-10
> Current Entry:
> - `/llmdoc/architecture/api-routing-and-dependency-wiring.md`
> - `/llmdoc/guides/export-workflow.md`
> - `/llmdoc/guides/voice-config-setup.md`

本文档面向前端接入方，说明 `edit-session` 后端接口的推荐使用方式、状态语义与常见约束。

Swagger / OpenAPI 负责提供结构化接口定义：

- 在线文档：`/docs`
- OpenAPI JSON：`/openapi.json`

本文件负责补充 Swagger 不擅长完整表达的业务语义：

- 推荐调用顺序
- render job / export job 生命周期
- SSE 事件消费方式
- `timeline`、`playback-map`、`composition` 的关系
- export 目录约束

---

## 0. 接口范围

本文档现在纳入三类接口，而不只限于主编辑路由：

- 会话主接口：`/v1/edit-session/*`
- 前置依赖接口：`/v1/voices*`
- 服务探活接口：`/health`

其中：

- `voices` 负责给前端提供可选音色与模型元信息，通常是发起 initialize 之前的依赖接口
- `health` 负责应用启动探活，不参与编辑流程本身

如果只是实现 edit-session 播放与编辑，不需要依赖 `/v1/audio/*` 旧 TTS 接口。

---

## 1. 总体原则

### 1.1 事实源

`/v1/edit-session/timeline` 是当前版本的权威播放对象。

前端新链路应优先依赖：

- `/v1/edit-session/snapshot`
- `/v1/edit-session/timeline`
- `/v1/edit-session/render-jobs/{job_id}`
- `/v1/edit-session/render-jobs/{job_id}/events`

兼容接口：

- `/v1/edit-session/playback-map`
- `/v1/edit-session/composition`

其中：

- `playback-map` 是从 `TimelineManifest` 派生出的兼容视图
- `composition` 不再是编辑成功的默认产物，只有在当前版本已经完成 composition export 后才会返回 200

### 1.2 版本语义

只要一次 mutation 成功提交，就会生成新的 `document_version`。

典型会产生新版本的接口包括：

- initialize
- append
- insert / update / delete segment
- swap / move-range / split / merge
- update edge
- session / group / segment / batch profile patch
- session / group / segment / batch voice-binding patch
- restore-baseline
- resume

export 不会创建新的 `document_version`。

### 1.3 异步语义

大多数写接口不是同步完成，而是：

1. 返回 `202 Accepted`
2. 响应体中带一个 `job`
3. 前端继续轮询或订阅该 job
4. 作业进入终态后，再读取最新 `snapshot` 或 `timeline`

---

## 2. 推荐调用顺序

### 2.0 初始化前的准备接口

前端通常会先调用：

- `GET /health`
- `GET /v1/voices`

常见用途：

- `GET /health`
  - 判断服务是否可用
- `GET /v1/voices`
  - 获取可选 `voice_id`
  - 构建初始化表单默认值

如果页面需要展示单个音色详细配置，还可以调用：

- `GET /v1/voices/{voice_name}`

## 2.1 初始化一个会话

调用：

- `POST /v1/edit-session/initialize`
- `POST /v1/edit-session/render-jobs`

然后：

1. 记录返回的 `job.job_id`
2. 轮询 `GET /v1/edit-session/render-jobs/{job_id}`，或订阅 `GET /v1/edit-session/render-jobs/{job_id}/events`
3. 优先消费 job 状态里自带的 committed 元数据：
   - `committed_document_version`
   - `committed_timeline_manifest_id`
   - `committed_playable_sample_span`
   - `changed_block_asset_ids`
4. 等待作业进入 `completed`
5. 再读取：
   - `GET /v1/edit-session/snapshot`
   - `GET /v1/edit-session/timeline`

初始化完成后，前端通常以 `snapshot + timeline` 进入编辑界面。

说明：

- `/v1/edit-session/render-jobs` 是初始化接口的兼容别名
- 新前端推荐统一使用 `/v1/edit-session/initialize`

## 2.2 进行一次编辑

无论是段编辑、边编辑、append，还是 profile / binding patch，推荐流程都一样：

1. 调用对应 mutation 接口
2. 获取返回的 `job_id`
3. 订阅 render job SSE 或轮询 job 状态
4. 以 job 状态中的 committed 元数据作为“可以刷新正式状态”的正式信号，而不是依赖瞬时 SSE 事件一定先到
5. 作业完成后重新读取 `snapshot`
6. 如果界面依赖精确播放结构，再重新读取 `timeline`

推荐不要假设前端本地能自行推导最终时间线，统一以后端返回为准。

## 2.3 导出

当前有两个独立导出接口：

- `POST /v1/edit-session/exports/segments`
- `POST /v1/edit-session/exports/composition`

二者是独立入口、独立 job，不会互相隐式触发。

导出推荐流程：

1. 取当前 `snapshot.document_version`
2. 发起 export job
3. 轮询 `GET /v1/edit-session/exports/{export_job_id}` 或订阅 `GET /v1/edit-session/exports/{export_job_id}/events`
4. 等待 job 进入 `completed`
5. 读取 `output_manifest`

如果 composition export 成功完成，那么当前版本的：

- `/v1/edit-session/composition`
- `snapshot.composition_manifest_id`
- `playback-map.composition_manifest_id`

都会反映这份已存在的整条音频资产。

---

## 3. 读取接口怎么选

### 3.1 `/snapshot`

用途：

- 获取当前编辑会话摘要
- 获取当前 `document_version`
- 获取当前活动作业
- 在文档较小时直接拿到内联 `segments` / `edges`

适合页面初始化、状态栏、版本同步。

### 3.1.1 `/baseline`

接口：

- `GET /v1/edit-session/baseline`

用途：

- 读取当前 baseline 快照
- 给“恢复到基线”之前的确认弹窗或 diff 视图使用

### 3.1.2 `/checkpoints/current`

接口：

- `GET /v1/edit-session/checkpoints/current`

用途：

- 读取当前最新 checkpoint
- 判断界面是否应该展示“恢复继续”入口
- 展示 paused / cancelled_partial 后的恢复信息

### 3.2 `/timeline`

用途：

- 获取权威播放结构
- 获取 block、segment、edge 的绝对 sample 范围
- 获取 marker，用于波形定位、seek 和时间轴标记

这是前端播放与时间轴的主接口。

### 3.3 `/playback-map`

用途：

- 兼容旧逻辑
- 快速调试段级 sample span

不建议作为新播放器的主数据源。

### 3.4 `/composition`

用途：

- 读取当前版本已存在的整条音频

注意：

- 该接口不会因为 render job 成功就自动可用
- 当前版本未做 composition export 时，返回 `404`
- 新前端不应依赖它作为播放主入口

### 3.5 组与配置读取接口

接口：

- `GET /v1/edit-session/groups`
- `GET /v1/edit-session/render-profiles`
- `GET /v1/edit-session/voice-bindings`

用途：

- 展示当前文档已有 group
- 展示 profile / binding 继承关系
- 为段级、组级、会话级配置面板提供读模型

### 3.6 资产读取接口

接口：

- `GET /v1/edit-session/assets/segments/{render_asset_id}`
- `GET /v1/edit-session/assets/segments/{render_asset_id}/audio`
- `GET /v1/edit-session/assets/boundaries/{boundary_asset_id}`
- `GET /v1/edit-session/assets/boundaries/{boundary_asset_id}/audio`
- `GET /v1/edit-session/assets/blocks/{block_asset_id}/audio`
- `GET /v1/edit-session/assets/compositions/{composition_manifest_id}/audio`
- `GET /v1/edit-session/assets/previews/{preview_asset_id}/audio`

用途：

- 元信息接口用于读取正式资产的 `audio_url`、`etag`、采样率等信息
- `/audio` 接口用于真正下载 wav 数据
- `segments / boundaries / blocks / compositions` 为正式资产
- `previews` 为临时资产，可能过期

### 3.7 `/preview`

接口：

- `GET /v1/edit-session/preview`

用途：

- 申请临时预览音频
- 支持三选一查询参数：
  - `segment_id`
  - `edge_id`
  - `block_id`

注意：

- 该接口本身返回的是 preview 资源描述，而不是音频二进制
- 真正播放时要再请求返回体里的 preview `audio_url`

---

## 4. Render Job 状态机

常见状态：

- `queued`
- `preparing`
- `rendering`
- `composing`
- `committing`
- `pause_requested`
- `paused`
- `cancel_requested`
- `cancelled_partial`
- `completed`
- `failed`

前端一般可按下面方式处理：

- `queued` / `preparing` / `rendering` / `composing` / `committing`
  - 展示进行中状态
- `pause_requested` / `cancel_requested`
  - 展示“已请求，等待安全边界处理”
- `paused`
  - 展示可恢复状态
- `cancelled_partial`
  - 展示 partial 结果，并允许用户决定是否继续
- `completed`
  - 刷新 snapshot/timeline
- `failed`
  - 展示错误消息，保留当前已提交版本

### 4.1 作业控制接口

接口：

- `GET /v1/edit-session/render-jobs/{job_id}`
- `POST /v1/edit-session/render-jobs/{job_id}/pause`
- `POST /v1/edit-session/render-jobs/{job_id}/cancel`
- `POST /v1/edit-session/render-jobs/{job_id}/resume`

建议：

- `pause` 与 `cancel` 都是“请求型”接口，不代表调用返回时作业已经真正停下
- 真实终态应以后续 job 查询或 SSE 事件为准
- `resume` 会创建一个新的 render job，而不是把旧 job 重新变回运行中

### 4.2 恢复基线接口

接口：

- `POST /v1/edit-session/restore-baseline`

用途：

- 以 baseline 内容创建一个新的 head 版本
- 适合“放弃当前修改并回到起点”的操作

---

## 5. SSE 事件流

### 5.1 Render Job SSE

接口：

- `GET /v1/edit-session/render-jobs/{job_id}/events`

常见事件包括：

- `job_state_changed`
- `segments_initialized`
- `segment_completed`
- `block_completed`
- `timeline_committed`
- `job_paused`
- `job_cancelled_partial`
- `job_resumed`

其中 `timeline_committed` 的 payload 会携带：

- `document_version` / `timeline_version` / `timeline_manifest_id`
- `playable_sample_span`
- `changed_block_asset_ids`

`changed_block_asset_ids` 表示本次提交后需要重新预热或替换的 block 资产集合。对于 compose-only 的停顿编辑，它只包含真正重新拼接出的脏 block，而不是整条 timeline 的全量 block。

同一批 committed 元数据也会被写入 render job 正式状态，并出现在：

- `GET /v1/edit-session/render-jobs/{job_id}`
- SSE / replay 的 `job_state_changed`

对应字段为：

- `committed_document_version`
- `committed_timeline_manifest_id`
- `committed_playable_sample_span`
- `changed_block_asset_ids`

建议前端策略：

1. 以 `job_state_changed` 更新通用状态与进度
2. 以 `segment_completed` 更新更细粒度的段进度 UI
3. 以 job 状态中的 committed 字段作为 hydrate / 刷新 `timeline` 的正式信号
4. `timeline_committed` 可继续作为补充事件使用，但不应成为唯一事实来源
5. SSE 中断时可退回到 job 轮询；只要 job 已携带 committed 字段，前端仍可继续完成 hydrate
6. hydrate 与音频预热完成后，仍应再用 `GET /render-jobs/{job_id}` 或同等正式状态查询对账一次 terminal 状态；只有 render job 已真正进入 `completed` / `failed` / `paused` / `cancelled_partial`，前端才应清理运行态锁与完成提示

### 5.2 Export Job SSE

接口：

- `GET /v1/edit-session/exports/{export_job_id}/events`

常见事件：

- `job_state_changed`
- `export_progress`
- `export_completed`

导出进度通常只需要显示整体进度和当前文件名。

---

## 6. 写接口清单

### 6.1 段与边编辑

接口：

- `POST /v1/edit-session/segments`
- `PATCH /v1/edit-session/segments/{segment_id}`
- `DELETE /v1/edit-session/segments/{segment_id}`
- `POST /v1/edit-session/segments/swap`
- `POST /v1/edit-session/segments/move-range`
- `POST /v1/edit-session/segments/split`
- `POST /v1/edit-session/segments/merge`
- `POST /v1/edit-session/append`
- `PATCH /v1/edit-session/edges/{edge_id}`

### 6.2 配置与绑定编辑

接口：

- `PATCH /v1/edit-session/session/render-profile`
- `PATCH /v1/edit-session/session/voice-binding`
- `PATCH /v1/edit-session/groups/{group_id}/render-profile`
- `PATCH /v1/edit-session/groups/{group_id}/voice-binding`
- `PATCH /v1/edit-session/segments/{segment_id}/render-profile`
- `PATCH /v1/edit-session/segments/{segment_id}/voice-binding`
- `PATCH /v1/edit-session/segments/render-profile-batch`
- `PATCH /v1/edit-session/segments/voice-binding-batch`

说明：

- 这些接口都会返回 `202`
- 实际变更结果以新 render job 完成后的 `snapshot` 和 `timeline` 为准

### 6.3 会话删除

接口：

- `DELETE /v1/edit-session`

用途：

- 清空当前活动会话及相关本地资产
- 一般只在“关闭当前文档并重新开始”场景使用

### 6.4 Voice 管理接口

接口：

- `GET /v1/voices`
- `GET /v1/voices/{voice_name}`
- `POST /v1/voices/reload`
- `POST /v1/voices/upload`
- `DELETE /v1/voices/{voice_name}`

说明：

- `GET /v1/voices` 是 edit-session 初始化前最常用的前置接口
- `reload / upload / delete` 更偏模型管理页面，不属于 edit-session 编辑主链路
- 如果前端同时承担 voice 管理页面，这些接口也应纳入联调文档

---

## 7. Export 约束

`target_dir` 表示用户选择的导出根目录。

规则如下：

- 必须是绝对路径
- 若目录不存在，后端会按需创建
- 整条导出会直接把产物写入该根目录，文件名为 `neo-tts-export-时间戳.wav`
- 分段导出会在该根目录下自动创建 `neo-tts-export-时间戳/`，内部段文件命名为 `segments-N.wav`
- `manifest_file` 仍会保留，但它是后端内部元数据文件，不会出现在用户导出目录中

因此，前端应把 `target_dir` 当成“导出根目录”，而不是“必须不存在的最终导出目录名”。

---

## 8. 常见前端接入建议

### 8.1 页面初始化

推荐顺序：

1. 调 `GET /v1/edit-session/snapshot`
2. 若 `session_status == empty`，提示先初始化
3. 若 `session_status == initializing` 或存在 `active_job`，自动接入 render job 状态
4. 若 `session_status == ready`，再调 `GET /v1/edit-session/timeline`

### 8.2 写操作后的刷新

不要在 mutation 返回 202 后立刻假设界面可用最新时间线。

更稳妥的方式是：

1. 等待 job `completed`
2. 刷新 `snapshot`
3. 刷新 `timeline`

### 8.3 预览与正式资产

正式资产：

- segment / boundary / block / composition
- 通常无过期时间

预览资产：

- 来自 `/preview`
- 带 `expires_at`
- 过期后再访问会失效，需要重新申请

### 8.4 分页列表

接口：

- `GET /v1/edit-session/segments`
- `GET /v1/edit-session/edges`

注意：

- 两个接口都支持 `limit` 和 `cursor`
- 大文档场景下，不应依赖 `snapshot.segments` / `snapshot.edges` 一定完整返回
- 更稳妥的做法是优先用分页接口拉全量实体，再用 `timeline` 做播放与定位

---

## 9. 与 Swagger 的配合方式

建议前端接入时这样使用文档：

1. 先读本文件，理解流程和语义
2. 再去 `/docs` 查看具体字段和响应 schema
3. 若需要自动生成类型或 client，使用 `/openapi.json`

也就是说：

- Swagger 解决“接口长什么样”
- 本文档解决“接口应该怎么串起来用”
