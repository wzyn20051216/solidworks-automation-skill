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

未实现:

- 软件内启动/停止 worker。
- 队列实时日志流。
- 多 Agent 并行/评审调度。
- Memory 和企业权限。
- CAD 真实执行器的生产级回滚。
- HMAC 签名、人工审批门和审计 ledger。

## 最小企业级原则

- 所有任务必须有结构化 JSON。
- 所有执行必须有输出文件。
- 所有 Codex 调用必须引用 skill 路径。
- 所有交付必须有验证记录。
- 真实制造文件必须经过 Reviewer Gate。
- Codex 执行必须显式启用，不允许默认静默运行。
- `danger-full-access` 必须由额外策略开关启用，不能作为默认值。

## 近期路线

1. Queue Store: 增加事件流 UI 时间线、运行中重试策略和队列健康状态。
2. Policy Gate: 增加 commit/push、跨目录写入、网络访问、CAD 宏执行的人工审批状态。
3. Artifact Ledger: 记录输出文件 hash、Codex 输出、验证命令、Git commit 和审计事件。
4. UI: 把 Prompt Preview 改为执行计划、门禁和影响范围，prompt 放到高级详情。
5. Multi-Agent: 增加 Planner/Executor/Reviewer 三阶段，不追求多进程炫技，先追求可追溯和可验收。
