# SolidWorks 实时可视化执行流设计

日期：2026-11-06
状态：设计已确认，待实现

## 1. 背景与目标

目标是在现有 CAD Studio 中加入类似参考视频的可视化执行体验：

- 用户在一个对话窗口中提交图纸或建模任务。
- SolidWorks 在前台可见地逐步创建草图、特征、装配和交付文件。
- 桌面右上角的原创机械鱼助手持续显示当前阶段和状态。
- 主窗口同步显示步骤时间线、SolidWorks 快照、进度和最终交付卡。
- 所有状态来自真实执行事件，不使用随机文案或预设演出冒充执行过程。

本功能是现有 Queue、Codex、SolidWorks MCP、Artifact Ledger 和 Reviewer Gate
之上的可视化层，不替代执行核心。

## 2. 非目标

- 不复刻参考视频中的角色、品牌或素材。
- 不引入云端事件服务。
- 不改变 SolidWorks COM 串行执行约束。
- 不把 `pilot`、`review_required` 或 `blocked` 结果展示为正式完成。
- 不在首个版本中实现完整时间轴录像或视频导出。

## 3. 用户流程

1. 用户在现有 AI 执行对话中提交任务。
2. 用户启用“可视化执行”。
3. 主窗口创建可视化任务，Queue Worker 以可见模式启动 SolidWorks。
4. 执行器围绕关键 CAD 操作写出结构化事件并保存快照。
5. `live-hud` 根据当前事件更新助手状态、步骤和进度。
6. 主窗口对话区同步显示当前步骤、最近快照和交付结果。
7. 完成后显示输出文件、耗时、模型体积、特征数、复核状态和文件入口。

## 4. 架构

```text
用户任务
  -> CAD Studio 主窗口
  -> Queue Worker
  -> Codex / SolidWorks MCP
  -> sw_visual_trace 写入事件
  -> queue/events/{job_id}.jsonl
  -> Tauri queue-changed
  -> 主窗口 + live-hud
```

### 4.1 主窗口

主窗口继续负责对话、任务配置、队列、人工复核和交付页。

新增内容：

- “可视化执行”开关。
- “显示桌宠 / 隐藏桌宠”操作。
- 当前步骤条、最近三张执行快照。
- 可视化交付卡。

### 4.2 live-hud 窗口

新增独立 Tauri 窗口，标签为 `live-hud`。

约束：

- 透明、无边框、始终置顶、默认不进入任务栏。
- 默认宽度 420，高度 300，位于当前屏幕右上角。
- 支持展开、收起、拖动和位置持久化。
- 非交互区域可鼠标穿透，按钮和折叠区域保持可点击。
- 窗口只读取当前活动任务的可视化数据，不直接执行 CAD 命令。

### 4.3 可视化事件写入器

新增 `scripts/sw_visual_trace.py`。

职责：

- 从环境变量读取当前任务的事件文件、快照目录和 `jobId`。
- 对同一进程内的连续写入做线程锁保护。
- 以单行 JSON 原子追加到现有 Queue 事件流。
- 在事件写入失败时保持 CAD 执行继续，并记录本地诊断。
- 对文本、路径和统计字段做长度与类型校验。

环境变量：

```text
CADSTUDIO_JOB_ID
CADSTUDIO_VISUAL_EVENT_FILE
CADSTUDIO_VISUAL_FRAME_DIR
```

### 4.4 SolidWorks 自动埋点

首个版本覆盖以下高层操作：

- `SolidWorksSession.new/open`
- `SolidWorksSession.save/export/close`
- 草图的开始与结束
- 拉伸、旋转、切除、孔、圆角等核心特征
- 装配、工程图、复核和交付

埋点必须位于真实 COM 调用前后。调用失败时写失败事件，不用模拟进度补足。

### 4.5 快照捕获

新增 `scripts/sw_window_capture.py`。

优先顺序：

1. 捕获 SolidWorks 主窗口客户区。
2. 捕获活动文档视口。
3. 使用 `sw_review` 生成模型预览。
4. 使用静态线框占位，并明确标记“快照不可用”。

快照保存规则：

```text
queue/visual/{job_id}/step-{sequence}-{step_id}.png
```

单张快照最大 8 MiB，单任务最多保留 80 张。超出后保留每个阶段的首尾帧和最近 20 帧。

## 5. 事件协议

视觉事件复用现有 Queue JSONL，不新增并行事件总线。

示例：

```json
{
  "type": "visual.step.completed",
  "jobId": "job-...",
  "at": "2026-11-06T12:00:00.000Z",
  "progress": 42,
  "data": {
    "stepId": "feature-main-shaft",
    "sequence": 3,
    "total": 7,
    "phase": "feature",
    "title": "生成主体阶梯轴",
    "message": "旋转特征已重建成实体",
    "snapshotPath": "queue/visual/job-.../step-003-feature-main-shaft.png",
    "stats": {
      "featureCount": 6,
      "volumeMm3": 28378.5
    }
  }
}
```

事件类型：

- `visual.session.started`
- `visual.plan.ready`
- `visual.step.started`
- `visual.step.completed`
- `visual.step.failed`
- `visual.review.started`
- `visual.review.completed`
- `visual.delivery.ready`
- `visual.session.failed`

`phase` 枚举：

- `planning`
- `sketch`
- `feature`
- `assembly`
- `drawing`
- `review`
- `delivery`

事件字段只保存执行事实。API Key、用户凭据、完整 Prompt 和隐私文本不写入视觉事件。

## 6. 助手状态

助手使用原创蓝灰机械鱼，不复刻参考视频角色。

| 状态 | 触发条件 | 视觉表现 |
| --- | --- | --- |
| `thinking` | 接单、规划、等待下一步 | 轻度浮动，眼角扫描线 |
| `working` | `visual.step.started` | 环形进度、机械鳍摆动 |
| `checking` | 复核和门禁阶段 | 放大镜、扫描网格 |
| `complete` | `visual.delivery.ready` | 高亮、交付卡展开 |
| `warning` | 失败、阻断、待人工复核 | 琥珀色状态、错误摘要 |

状态文案直接来自当前事件的 `title` 和 `message`。没有事件时显示“等待执行事件”。

## 7. 主窗口可视化

对话区下方新增紧凑的实时执行条：

- 当前阶段标题。
- 当前步骤序号。
- 总进度。
- 最近三张快照缩略图。
- 展开完整时间线按钮。

完成消息使用结构化交付卡：

- 输出文件名称和路径。
- 本轮耗时。
- 模型体积。
- 特征数量。
- 复核状态。
- 文件定位按钮。
- 查看交付页按钮。

交付卡数据来自任务结果、Artifact Ledger 和 Review Gate。字段缺失时显示“未提供”，不以推测值补齐。

## 8. 异常处理

- 事件文件缺失：HUD 回退到 `job.stage`、`job.progress` 和 `job.lastMessage`。
- 视觉事件损坏：跳过该行，保留诊断，不影响任务执行。
- 快照失败：显示线框占位和失败原因。
- SolidWorks 未启动：助手进入 `warning`，给出环境诊断入口。
- 步骤超时：助手显示当前步骤和已持续时间。
- 任务失败：冻结最后有效画面，显示错误和日志入口。
- 任务取消：显示取消状态，不继续播放动画。
- 多任务并发：HUD 只订阅当前 `activeVisualJobId`。

## 9. 安全与数据边界

- HUD 只读取 Queue 目录内的事件和快照。
- Tauri 资源协议只放行当前应用数据目录下的 `queue/visual/**`。
- 快照路径必须经过规范化，拒绝目录穿越。
- 快照文件只允许 PNG 和 JPEG。
- 不捕获其他窗口、桌面区域或操作系统敏感界面。
- 单个事件总大小限制为 64 KiB。
- 日志中只记录快照相对路径，不记录用户凭据。

## 10. 测试

### 单元测试

- 事件写入顺序、JSON 结构和失败降级。
- 状态映射、进度边界和文案选择。
- 快照路径白名单、大小上限和保留策略。
- SolidWorks 失败时不产生完成事件。

### React 测试

- HUD 五种助手状态。
- 展开、收起、拖动状态和位置持久化。
- 主窗口实时执行条和交付卡。
- 事件缺失、快照缺失和长文本截断。

### Tauri 测试

- `live-hud` 窗口配置和权限。
- 可视化资源路径解析。
- 队列事件通知和多任务绑定。

### 端到端测试

1. 启动 CAD Studio。
2. 启用可视化执行并提交阶梯轴任务。
3. 确认 SolidWorks 可见启动。
4. 确认草图、旋转、切除、保存和导出分别产生事件和快照。
5. 确认 HUD 状态依次变化。
6. 确认完成后显示约 28,378 mm³ 体积、特征数和 `SLDPRT/STEP` 文件。
7. 确认 Reviewer Gate 为 `review_required` 时显示人工复核，不显示正式完成。

### 视觉验收

- 1440x980 主窗口和 420x300 HUD 均无文字溢出。
- HUD 不遮挡 SolidWorks 特征树、绘图区中心和常用工具栏。
- 展开状态不超出屏幕边界。
- 快照缩略图缺失时布局不跳动。
- 五类状态的颜色、图标和文案清晰可辨。

## 11. 验收标准

- 用户只通过一次任务提交即可看到 SolidWorks 前台逐步建模。
- 每个完成事件都能关联真实操作、时间和结果。
- HUD 状态与队列事件一致。
- 任务结束后可看到文件、耗时、体积、特征数和复核状态。
- 失败和待复核任务不会被展示为成功。
- 关闭 HUD 不影响任务执行。
- 关闭主窗口后，重新打开能够恢复当前活动任务的视觉状态。

## 12. 实施边界

首个版本只覆盖 SolidWorks 原生执行和现有 Queue 工作流。

后续扩展位置：

- AutoCAD 视觉执行。
- 时间轴回顾和短视频导出。
- 多助手皮肤。
- 自定义角色素材。
- 远程 MCP 的只读视觉镜像。

