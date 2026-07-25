# CAD Studio 本地自动化队列协议

## 目标

CAD Studio 桌面端通过 Tauri 把任务保存为本机 JSON 文件，Python worker 读取队列并执行。第一版 worker 使用 mock handler，后续把 handler 替换为 SolidWorks / AutoCAD 自动化即可。

## 队列目录

Rust 侧以 `app.path().app_data_dir()/queue` 为准。当前 Tauri 标识为:

```text
com.wzyn.cadstudio
```

Windows 常见路径:

```text
%APPDATA%\com.wzyn.cadstudio\queue
```

worker 默认也会读取该目录。调试时可以显式指定:

```powershell
python -m apps.desktop.cad_workbench.queue_worker --queue-dir "<队列目录>"
```

持续监听:

```powershell
python -m apps.desktop.cad_workbench.queue_worker --watch --queue-dir "<队列目录>"
```

## 任务 JSON

每个任务一个文件，文件名来自安全化后的 `id`:

```text
{id}.json
```

字段:

```json
{
  "schemaVersion": "1.0",
  "id": "job-1721900000000-a1b2c3",
  "runId": "run-1721900000000-a1b2c3",
  "kind": "create_shell",
  "title": "新建外壳",
  "detail": "生成参数化壳体、开孔和基础检查任务",
  "status": "queued",
  "progress": 0,
  "createdAt": "2026-07-25T12:00:00.000Z",
  "updatedAt": "2026-07-25T12:00:00.000Z",
  "requestedBy": "local-user",
  "createdByAppVersion": "0.1.0",
  "policy": {
    "sandbox": "workspace-write",
    "approval": "never",
    "requireSkillRead": true,
    "requireTests": true,
    "requireCommit": true,
    "requirePush": false,
    "requireReviewerPass": true
  },
  "projectPath": "D:/demo/demo_shell.step"
}
```

机器可读 Schema:

```text
apps/desktop/cad_workbench/schemas/automation_job.schema.json
```

任务类型:

- `create_shell`: 新建参数化外壳、开孔和基础检查。
- `import_model`: 导入本地 CAD 模型并建立项目上下文。
- `delivery_package`: 生成 STEP、STL、PDF、DWG 等交付包。
- `codex_task`: 图形化配置生成的 Codex 非交互执行任务。

Codex Bridge 扩展字段:

```json
{
  "executor": "codex",
  "objective": "根据当前配置生成可 3D 打印外壳",
  "target": "3D 打印外壳建模",
  "expectedOutput": "SLDPRT / STEP / STL",
  "strictRules": ["3D 打印开孔必须真实切除", "必须按中国机械制图常用格式复核 CAD 图纸"],
  "prompt": "你是 Codex，请执行由 CAD Studio 图形化界面生成的任务...",
  "cwd": "C:/Users/23201/.codex/skills/solidworks-automation",
  "skillPath": "C:/Users/23201/.codex/skills/solidworks-automation/SKILL.md"
}
```

状态流转:

```text
queued -> running -> passed
queued -> running -> failed
queued -> cancelled
queued -> approval_required -> queued
```

约定:

- UI 只创建任务和取消任务。
- worker 只处理 `status == "queued"` 的任务。
- `passed`、`failed`、`cancelled` 是终态。
- worker 回写 `workerLog`、`lastMessage`、`result` 或 `error`，前端可以直接展示这些字段。
- 真实 CAD handler 必须在写入 `passed` 前完成文件存在性检查，不能把占位文件标为可制造交付。

## 可靠队列状态机

当前仍使用本地 JSON 文件队列，但 worker 已具备最小可靠性语义:

- 领取任务前创建 `{job}.json.lock`，使用原子创建避免多 worker 重复接单。
- 领取后写入 `runnerId`、`workerPid`、`attempt`、`heartbeatAt`、`leaseUntil`。
- 运行中 worker 会定期刷新 `heartbeatAt` 和 `leaseUntil`，防止长任务被误判为 stale。
- worker 结束后释放 `.lock`。
- UI 可把任务写为 `status: "cancelled"` 或 `cancelRequested: true`，worker 会终止托管中的 Codex 子进程。
- 启动或轮询时会恢复 `leaseUntil` 过期的 `running` 任务，将其重新置为 `queued`。
- 损坏 JSON 会被移动到 `queue/quarantine`，并生成同名 `.error.txt`，不会中断 watch 循环。
- 每个任务会写入 `queue/events/{job_id}.jsonl` 事件流。
- 托管子进程 stdout/stderr 会写入 `queue/logs/{job_id}.stdout.log` 与 `queue/logs/{job_id}.stderr.log`。

这些字段是 worker 管理字段，UI 可展示但不要手动修改。

## Codex Bridge

软件定位是“AI 辅助 CAD 自动化控制台”:

```text
图形化配置 -> 结构化任务 JSON -> Python worker -> codex exec -> 回写队列结果
```

启用 Codex 执行:

```powershell
python -m apps.desktop.cad_workbench.queue_worker --watch --enable-codex --queue-dir "<队列目录>"
```

worker 会调用:

```powershell
codex exec -C "<cwd>" -a never -s workspace-write -o "<输出文件>" --output-schema "<schema>" "<prompt>"
```

注意:

- `--enable-codex` 是显式开关，避免普通 mock 调试误触发真实 Codex 执行。
- 默认只允许 `workspace-write`，若确需全权限，必须额外传 `--codex-full-access`。
- worker 会校验 `cwd` 必须位于仓库白名单内，并强制输出到 `<cwd>/ai_team/{job_id}_codex_result.md`。
- UI 负责生成 prompt 和执行约束，Codex 负责实际读写文件、调用 skill、运行验证、提交推送。
- Codex 输出会写入 `ai_team/{job_id}_codex_result.md`，同时在任务 JSON 的 `result.outputPath` 中回写路径。

## 接入真实执行器

Python worker 的扩展点在:

```text
apps/desktop/cad_workbench/queue_worker.py
```

替换或注入 handler:

- `create_shell` -> SolidWorks 建模、实体开孔、STL/STEP 导出。
- `import_model` -> 文件解析、缩略图、项目目录初始化。
- `delivery_package` -> AutoCAD 图纸导出、PDF/DWG/DXF、交付清单和规范复核。

执行器必须遵守 P0 门禁:

- 3D 打印开孔必须是真实几何切除，不允许只画线或只写注释。
- 图纸必须保留完整尺寸链、孔表、技术要求、图框标题栏和 GB/T 风格标注。
- 失败时写回 `failed` 和明确 `error`，不要静默跳过。
