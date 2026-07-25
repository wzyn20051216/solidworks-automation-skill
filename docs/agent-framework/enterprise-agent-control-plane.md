# CAD Studio 企业级 Agent 控制平面

## 定位

CAD Studio 不是把大模型塞进 CAD 软件里，而是一个面向机械工程师的 Agent 控制平面:

```text
图形化配置 -> 企业任务契约 -> Codex 执行 -> Skill/工具链 -> 审核门禁 -> 交付回写
```

Codex 仍然是最终执行者，`solidworks-automation` skill 是核心能力包。界面负责把用户意图变成可审计、可复用、可回放的任务单。

## 对标吸收

从 `datawhalechina/hello-agents` 一类教学/框架项目吸收:

- Agent 基础抽象: 角色、工具、记忆、上下文、协议、评估。
- 从单轮 prompt 升级为可复用工作流。
- 使用案例驱动，把框架能力落到真实任务。

从 Hermes Agent 等更完整框架吸收:

- 长期运行 worker。
- Agent Profile / Skill / Memory 分层。
- 多 Agent 委派与评审。
- 网关、审计、权限和可回滚执行。

本项目不直接照搬通用 Agent 框架，而是收敛为 CAD/Skills 垂直场景。

## 模块边界

- UI: 收集配置、展示队列、展示 prompt 预览和执行结果。
- Queue: 用 JSON 持久化任务，保证离线可恢复。
- Agent Contract: 编译 Agent Profile、Policy、Prompt 和 Output Schema。
- Worker: 监听队列，分发 mock / Codex / CAD handler。
- Codex Executor: 调用 `codex exec`，强制读取 skill，输出结构化结果。
- Reviewer Gate: 检查真实开孔、GB/T 图纸、测试、Git 状态和交付物。
- Artifact Store: 保存 Codex 输出、CAD 文件、复核报告和队列日志。

## 当前落地状态

已实现:

- Tauri 本地队列。
- Python worker。
- `executor: "codex"` 桥接。
- Codex Bridge UI。
- Agent Profile 与 prompt 编译器。
- Codex 最终响应 JSON schema。
- 版本化任务 Schema。
- 默认 `workspace-write` 沙箱、工作区白名单和固定输出目录。
- JSON 队列 claim lock、lease、stale running 恢复和坏任务 quarantine。
- 运行中 heartbeat 续租、取消语义、JSONL 事件流和 stdout/stderr 日志落盘。
- Policy Gate 人工审批状态，覆盖 Git push、全权限沙箱、CAD 宏、外部网络、跨工作区写入和删除文件。
- 审批范围复核: 批准后若任务风险原因变化，worker 会重新拦截。
- Artifact Ledger: 成功任务自动记录交付物路径、存在性、大小和 SHA-256。
- Worker Control: 桌面端可启动/停止本地 Python worker，并显示运行状态和 PID。
- Worker Health: worker 写入健康心跳、队列统计、恢复数量和最近错误。
- Reviewer Gate: 基于 Artifact Ledger 输出交付物复核报告，并检查 STEP/STL/DXF/PDF/DWG 轻量格式特征。

未实现:

- 软件内启动/停止 worker。
- 队列实时日志流。
- 多 Agent 并行/评审调度。
- Memory 和企业权限。
- CAD 真实执行器的生产级回滚。
- HMAC 签名和不可变审计账本。

## 最小企业级原则

- 所有任务必须有结构化 JSON。
- 所有执行必须有输出文件。
- 所有 Codex 调用必须引用 skill 路径。
- 所有交付必须有验证记录。
- 真实制造文件必须经过 Reviewer Gate。
- 用户未指定的工程选项默认进入 `auto_best`，由 AI 自动选择最佳方案，并记录选择理由和残余风险。
- Codex 执行必须显式启用，不允许默认静默运行。
- `danger-full-access` 必须同时满足任务审批和 worker `--codex-full-access` 开关，不能作为默认值。
- 前端任务 JSON 不可信，Policy Gate 必须在 worker/control-plane 层强制执行。

## Policy Gate

当前 Policy Gate 先解决“危险操作不能被 UI 一键静默执行”的问题。Codex 任务进入 worker 后，会在真正调用 `codex exec` 前检查:

- `policy.approval == "manual-required"`。
- `policy.requirePush == true` 或界面配置 `commitAndPush == true`。
- `policy.sandbox == "danger-full-access"`。
- `capabilities` 包含 `git_push`、`full_access`、`cad_macro`、`external_network`、`cross_workspace`、`delete_files`。

命中后任务进入 `approval_required`，worker 写入 `approvalReasons` 和 `policy.approval_required` 事件。桌面端批准后写入 `approvedAt`、`approvedBy`、`approvedPolicyReasons` 并恢复为 `queued`。worker 会重新计算审批原因，只有当前原因与已批准原因一致时才继续执行。

## Artifact Ledger

Artifact Ledger 是 Reviewer Gate 的前置基础。任务成功后，worker 会把 `result.outputPath`、`result.outputs`、`result.artifacts` 和任务级 `artifacts` 汇总成 `queue/ledgers/{job_id}.ledger.json`，记录:

- 交付物 kind/path。
- 文件是否存在、是否目录。
- 文件大小和 SHA-256。
- 执行结果消息和验证摘要。

Ledger 只记录事实，不替代制造级验收。真实 CAD handler 仍需在写入 `passed` 前检查 STEP/STL/DWG/PDF 等 P0 文件是否真实存在、可打开、可制造。

## Worker Health

worker 会写入 `queue/worker_health.json`，记录运行心跳、进程 PID、队列状态统计、本轮处理数量、stale running 恢复数量和最近错误。桌面端读取这个文件后，可以把进程状态和队列健康分开展示: 进程活着不代表任务健康，队列有失败或待审批也需要明确提示。

## Reviewer Gate

Reviewer Gate 当前提供交付物文件事实检查和轻量格式特征检查，报告路径为 `queue/reviews/{job_id}.review.json`。它会检查交付物是否声明、是否存在、是否为空文件、是否具备 SHA-256，并对 STEP/STP、STL、DXF、PDF、DWG 做文件头或结构标记检查。SLDPRT 属于专有格式，当前只记录 warning，后续要接入 SolidWorks 打开复核。

## 近期路线

1. Queue Store: 增加事件流 UI 时间线、运行中重试策略和队列健康状态。
2. Reviewer Gate: 增加 SolidWorks/AutoCAD 真打开检查、图纸尺寸链检查和 3D 打印真实开孔复核。
3. Worker Health: 增加崩溃原因持久化、队列健康评分和 UI 时间线。
4. UI: 把 Prompt Preview 改为执行计划、门禁和影响范围，prompt 放到高级详情。
5. Multi-Agent: 增加 Planner/Executor/Reviewer 三阶段，不追求多进程炫技，先追求可追溯和可验收。
