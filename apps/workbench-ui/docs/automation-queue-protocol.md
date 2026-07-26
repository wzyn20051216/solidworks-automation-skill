# CAD Studio 本地自动化队列协议

## 目标

CAD Studio 桌面端通过 Tauri 把任务保存为本机 JSON 文件，Python worker 读取队列并调用本机 Codex。正式桌面启动只启用 Codex handler；mock handler 仅供显式开发测试。

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

桌面集成测试可在启动前设置 `CAD_STUDIO_QUEUE_DIR` 覆盖 Tauri 队列目录；正式运行不设置时仍使用应用数据目录。

持续监听:

```powershell
python -m apps.desktop.cad_workbench.queue_worker --watch --queue-dir "<队列目录>"
```

桌面端也提供 Worker Control，队列面板右上角可以启动/停止由软件托管的 Python worker。浏览器预览模式不会启动 worker。

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
  "title": "新建 CAD 任务",
  "detail": "生成零件、装配、外壳、孔槽和基础检查任务",
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
  "capabilities": [],
  "projectPath": "D:/demo/demo_shell.step"
}
```

机器可读 Schema:

```text
apps/desktop/cad_workbench/schemas/automation_job.schema.json
```

任务类型:

- `create_shell`: 兼容旧命名的新建 CAD 任务，覆盖零件、装配、外壳、孔槽和基础检查。
- `import_model`: 导入本地 CAD 模型并建立项目上下文。
- `delivery_package`: 生成 STEP、STL、PDF、DWG 等交付包。
- `codex_task`: 图形化配置生成的 Codex 非交互执行任务。

Codex Bridge 扩展字段:

```json
{
  "executor": "codex",
  "objective": "根据用户输入自动判断最佳 CAD 任务类型、制造方式、材料和交付格式",
  "target": "AI 自动判断",
  "expectedOutput": "AI 自动选择输出",
  "strictRules": ["未指定字段由 AI 自动选择最佳工程方案", "孔槽必须真实几何切除", "必须按中国机械制图常用格式复核 CAD 图纸"],
  "prompt": "你是 Codex，请执行由 CAD Studio 图形化界面生成的任务...",
  "cwd": "C:/path/to/solidworks-automation-skill",
  "skillPath": "C:/path/to/solidworks-automation-skill/SKILL.md",
  "uiConfig": {
    "selection": {
      "mode": "auto_best",
      "autoTarget": true,
      "autoOutput": true,
      "autoProcess": true,
      "autoMaterial": true,
      "instruction": "未指定字段由 AI 自动选择最佳工程方案，并说明理由。"
    }
  }
}
```

默认选择语义:

- 用户没有指定任务类型、工艺、材料、输出格式或尺寸细节时，UI 会写入 `selection.mode = "auto_best"`。
- Codex 必须根据工程目标、输入文件、制造方式、成本、强度、可加工性和交付要求自动选择最佳方案。
- 自动选择后必须在最终结果中说明选择理由和残余风险。
- 用户点击具体模板或具体选项后，该字段视为用户指定，Codex 应优先遵守。

状态流转:

```text
queued -> running -> passed | review_required | failed | cancelled
queued -> running -> failed
queued -> cancelled
queued -> approval_required -> queued | cancelled
review_required -> passed | failed
```

约定:

- UI 通过只创建接口写入新任务；取消、执行前审批和执行后人工复核分别走专用命令，不能用通用保存覆盖任务状态。
- worker 只处理 `status == "queued"` 的任务。
- `passed`、`failed`、`cancelled` 是终态；`review_required` 必须由用户明确“通过复核”或“驳回”。
- worker 回写 `workerLog`、`lastMessage`、`result` 或 `error`，前端可以直接展示这些字段。
- 成功任务会回写 `artifactLedgerPath` 和 `artifacts`，用于展示交付物存在性、大小和 hash。
- 成功任务会回写 `reviewGatePath` 和 `reviewGate`，用于展示交付物复核状态。
- Reviewer Gate 为 `warning` 时写入 `review_required`，不能显示“完成”；只有门禁为 `pass` 才写入 `passed`。
- 真实 CAD handler 必须在写入 `passed` 前完成文件存在性检查，不能把占位文件、AI JSON 回执或旧文件标为可制造交付。
- `save_queue_job` 仅接受不存在的 `queued` 新任务；已存在任务一律拒绝覆盖。

人工复核通过前必须填写具体说明并完成当前任务要求的复核清单。通过后会写入 `reviewedBy`、`reviewedAt`、`reviewDecision = "approved"`，并把人工检查项、告警列表及交付物路径/大小/SHA-256 快照写入 `reviewGate.manualReview` 和审计事件 `review.manual_approved`；驳回必须填写问题说明，并写入 `reviewDecision = "rejected"`、明确错误和 `review.manual_rejected`。

## Policy Gate

Policy Gate 是 worker/control-plane 层的强制门禁，不能只依赖前端提示。Codex 任务在执行前会先检查策略和能力声明，命中风险则写回:

```json
{
  "status": "approval_required",
  "approvalReasons": ["任务请求 Git push，需要人工审批。"],
  "lastMessage": "任务需要人工审批: ..."
}
```

当前会要求人工审批的情况:

- `policy.approval == "manual-required"`。
- `policy.requirePush == true` 或 `uiConfig.gates.commitAndPush == true`。
- `policy.sandbox == "danger-full-access"`。
- `capabilities` 包含 `git_push`、`full_access`、`cad_macro`、`external_network`、`cross_workspace`、`delete_files`。

桌面端点击“批准”后，会写入:

```json
{
  "approvedAt": "unix:1784970000",
  "approvedBy": "local-user",
  "approvedPolicyReasons": ["任务请求 Git push，需要人工审批。"],
  "status": "queued"
}
```

worker 会重新计算当前任务的审批原因，并要求它与 `approvedPolicyReasons` 完全一致；如果批准后又把任务改成全权限、CAD 宏或其他危险能力，审批会失效并重新进入 `approval_required`。这不是最终的防篡改方案，后续 Artifact Ledger 会补 HMAC 签名和不可变审计记录。

## 可靠队列状态机

当前仍使用本地 JSON 文件队列，但 worker 已具备最小可靠性语义:

- 领取任务前打开 `{job}.json.lock`，Windows 使用 `msvcrt.locking`、Unix 使用 `fcntl.flock` 获取操作系统排他锁，避免多 worker 重复接单。
- 领取后写入 `runnerId`、`workerPid`、`attempt`、`heartbeatAt`、`leaseUntil`。
- 运行中 worker 会定期刷新 `heartbeatAt` 和 `leaseUntil`，防止长任务被误判为 stale。
- worker 结束后释放操作系统锁；`.lock` 文件作为诊断记录保留，进程异常退出时操作系统也会自动释放锁。
- UI 可把任务写为 `status: "cancelled"` 或 `cancelRequested: true`，worker 会终止托管中的 Codex 子进程。
- 启动或轮询时会恢复 `leaseUntil` 过期的 `running` 任务，将其重新置为 `queued`。
- 软件主动停止 Worker、Alt+F4、系统关闭或原生退出时，会先终止 Worker 进程树，再按 `workerPid` 把该 Worker 未完成的 `running` 任务立即恢复为 `queued`；已有取消请求的任务保持 `cancelled`。
- 损坏 JSON 会被移动到 `queue/quarantine`，并生成同名 `.error.txt`，不会中断 watch 循环。
- 每个任务会写入 `queue/events/{job_id}.jsonl` 事件流。
- 托管子进程 stdout/stderr 会写入 `queue/logs/{job_id}.stdout.log` 与 `queue/logs/{job_id}.stderr.log`。
- 成功任务会写入 `queue/ledgers/{job_id}.ledger.json` 交付物账本。
- 成功任务会写入 `queue/reviews/{job_id}.review.json` Reviewer Gate 报告。
- worker 会写入 `queue/worker_health.json` 健康心跳。

这些字段是 worker 管理字段，UI 可展示但不要手动修改。

## Worker Health

worker 每轮队列扫描后会写入:

```text
queue/worker_health.json
```

字段包括:

- `status`: `healthy`、`attention`、`warning` 或 `error`。
- `heartbeatAt`: 最近一次心跳时间。
- `processedCount`: 本轮处理任务数量。
- `recoveredCount`: 本轮恢复 stale running 任务数量。
- `queue`: 按任务状态统计的队列数量。

桌面端 `worker_status` 会同时返回托管进程 PID 和最近健康心跳。浏览器预览模式不会启动 worker。

## Artifact Ledger

Artifact Ledger 用于把 Agent 交付结果变成可审计的机器记录。worker 在任务成功后收集 `result.outputPath`、`result.outputs`、`result.artifacts` 和任务自身 `artifacts` 字段，生成:

```json
{
  "schemaVersion": "1.0",
  "jobId": "job-1721900000000-a1b2c3",
  "runId": "run-1721900000000-a1b2c3",
  "status": "passed",
  "artifacts": [
    {
      "kind": "step",
      "path": "D:/demo/outputs/model/demo.step",
      "exists": true,
      "isDirectory": false,
      "sizeBytes": 12345,
      "sha256": "..."
    }
  ],
  "verification": [],
  "resultMessage": "任务完成"
}
```

写入路径:

```text
queue/ledgers/{job_id}.ledger.json
```

相对输出路径会优先按任务 `cwd` 解析；没有 `cwd` 时按 `projectPath` 所在目录或项目目录解析。同一信息会摘要回写到任务 JSON 的 `artifactLedgerPath` 和 `artifacts` 字段，并追加 `artifact.ledger_written` 事件。真实 CAD handler 仍然必须自己判断 P0 交付物是否齐全；Ledger 负责记录事实，不替代制造级验收。

## Reviewer Gate

Reviewer Gate 基于 Artifact Ledger 生成最小交付物复核报告:

```text
queue/reviews/{job_id}.review.json
```

当前规则:

- 没有声明交付物: `warning`，说明只能确认流程完成，不能确认制造文件齐全。
- 声明的交付物不存在: `fail`。
- 交付物为空文件: `fail`。
- 交付物是目录: `warning`，当前不递归校验目录内容。
- 普通文件存在且有 SHA-256: `pass`。
- Codex 自报验证为 `failed` 时，Reviewer Gate 必须 `fail`；没有验证记录或存在残余风险时至少为 `warning`。
- `SLDPRT / STEP / STL`、`DWG / DXF / PDF` 等明确格式清单按逐项门禁检查，不能用其中一个文件代替整个交付包。
- Codex 交付物必须位于任务工作区、用户输出目录或输入文件目录内。执行前会记录 CAD 文件的大小、纳秒级修改时间和 SHA-256；执行后只有新文件或内容哈希发生变化的文件才标记 `producedThisRun = true`，仅修改时间戳不能冒充本轮产物；AI 回执和未变化旧文件不计为本轮 CAD 产物。
- STEP/STP 必须包含 `ISO-10303-21` 和 `END-ISO-10303-21` 标记。
- STL 必须具备可识别的 ASCII `solid/endsolid` 或 Binary STL 基础结构。
- DXF 必须包含 `SECTION` 并以 `EOF` 结束。
- PDF 必须包含 `%PDF-` 文件头。
- DWG 必须包含 AutoCAD `AC10` 版本头。
- SLDPRT、SLDASM 属于专有格式，当前只能给出 `warning`，后续由 SolidWorks 打开复核。

报告摘要会回写到任务 JSON 的 `reviewGate` 和 `reviewGatePath`，并追加 `review.gate_completed` 事件。它是后续制造级 Reviewer Gate 的基础，真实 CAD 阶段还需要继续检查 STEP/STL/DWG/PDF 是否可打开、尺寸链是否完整、3D 打印真实开孔是否成立。

## Codex Bridge

软件定位是“AI 辅助 CAD 自动化控制台”:

```text
图形化配置 -> 结构化任务 JSON -> Python worker -> codex exec -> 回写队列结果
```

Worker 在编译 Prompt 前会执行本地优先 RAG：默认检索主 Skill、`references/` 和子技能知识文件，并把来源、SHA-256 与片段注入 Prompt。`uiConfig.knowledgeBase.cloudEnabled=true` 时，Tauri 会服务端派生 `external_network` 能力；只有人工审批完成后才允许调用 HTTPS 云检索端点。

启用 Codex 执行:

```powershell
python -m apps.desktop.cad_workbench.queue_worker --watch --enable-codex --queue-dir "<队列目录>"
```

软件内点击“启动”时等价于启动:

```powershell
python -m apps.desktop.cad_workbench.queue_worker --watch --enable-codex --queue-dir "<Tauri 队列目录>"
```

该入口默认不会加 `--codex-full-access`，全权限仍需要人工审批和显式命令开关。

worker 会调用:

```powershell
node.exe "<npm>/node_modules/@openai/codex/bin/codex.js" exec -C "<cwd>" -s workspace-write -c "approval_policy=\"never\"" -o "<输出文件>" --output-schema "<schema>" "<prompt>"
```

注意:

- `--enable-codex` 是显式开关，避免普通 mock 调试误触发真实 Codex 执行。
- 默认只允许 `workspace-write`。若确需全权限，任务必须先经过 Policy Gate 审批，并且 worker 启动时额外传 `--codex-full-access`。
- Windows npm 安装优先使用 `node.exe + codex.js`，不经 `cmd.exe` 解析用户 prompt。
- Codex 版本、登录状态和 SolidWorks preflight 健康检测均有 5～10 秒超时；超时会终止进程树并返回明确错误，不阻塞桌面界面。
- worker 会校验 `cwd` 必须位于仓库白名单内，并强制输出到 `<cwd>/ai_team/{job_id}_codex_result.json`；执行前删除同名旧回执，缺失或非法 JSON 直接失败。
- UI 负责生成 prompt 和执行约束，Codex 负责实际读写文件、调用 skill、运行验证、提交推送。
- Worker 在执行前运行本地机械知识检索，并将带来源路径、SHA-256 和评分的片段注入企业 Prompt。
- 设置页可添加本地标准库；云 RAG 默认关闭，启用后由 Tauri 服务端派生 `external_network` 危险能力并要求审批。
- Codex 输出会写入 `ai_team/{job_id}_codex_result.json`，同时在任务 JSON 的 `result.outputPath` 中回写路径。

### CAD 软件路由

UI 会把目标软件写入 `targetSoftware` 和 `uiConfig.cadRuntime`:

```json
{
  "targetSoftware": "AI 自动选软件",
  "capabilities": ["cad_macro"],
  "policy": {
    "sandbox": "danger-full-access",
    "approval": "never"
  },
  "uiConfig": {
    "cadRuntime": {
      "application": "auto",
      "applicationLabel": "AI 自动选软件",
      "localCadAutomation": true,
      "solidworksSkillPath": "C:/path/to/solidworks-automation-skill/SKILL.md",
      "autocadSkillPath": "C:/path/to/solidworks-automation-skill/subskills/autocad-automation/SKILL.md"
    }
  }
}
```

路由规则:

- 三维实体、装配、真实开孔、钣金、STEP/STL/SLDPRT 导出优先调用 SolidWorks。
- DWG/DXF/PDF、国标工程图、图层、尺寸链、孔表、标题栏和 AutoCAD 原生预览优先调用 AutoCAD。
- 交付包、装配图和制造复核可以先用 SolidWorks 生成三维与中间文件，再用 AutoCAD 完成二维图纸和导出。
- `application == "auto"` 时，Codex 必须根据任务目标自动选择 SolidWorks、AutoCAD 或两者联动，并在结果中说明选择理由。
- `localCadAutomation == true` 时任务会声明 `cad_macro` 能力和 `danger-full-access` 沙箱，因此 Policy Gate 会要求人工审批；worker 也必须以 `--codex-full-access` 启动后，审批过的任务才会真正具备桌面软件调用能力。

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
