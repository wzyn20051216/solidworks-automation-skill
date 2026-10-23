# P0-1.2 合并前检查报告

**合并就绪性：BLOCKED。保留 Draft PR #39，当前不建议合并 main。**
代码层已移除一次性测试分支限制，但 GitHub 实际权限和环境保护尚不具备完整安全条件。
本阶段没有创建 Environment、Secret、Runner，也未修改仓库设置或推送 main。

## PR 相对 main 的完整审计

起点为 `b2dbd38f6405466ab5e0cc331bd4cb9c8ca39104`，main Base 为
`f9d6efbecf297bcdfffc451de81ba3a7bdea6a0d`。

| PR 原有变更 | 审计结论与本阶段处理 |
| --- | --- |
| golden-workflows.yaml | 仅为 mounting_bracket 增加固定真机规格；2026 和几何尺寸是已验证用例边界，不能由运行配置改成其它规格。 |
| 安装板真机脚本 | 保留模型和生产接口；补充可移植配置、无副作用诊断、PID 创建时间、证据路径安全和严格 trace 关联。 |
| 安装板离线测试 | 保留全部拒绝假成功用例；补充共用入口、配置、链接和重用 PID 等故障注入。合成输入不计真机统计。 |
| Windows CAD Workflow | 原硬编码测试分支合并后不可运行；改为受保护分支、人员授权、环境核验及 Environment 人工审批。 |
| 验收文档 | 旧章节保留为历史记录，当前规范以本文和 P0-1.2 章节为准。 |
| 两份历史证据索引 | 绝对路径是当时的证据来源，不是执行依赖；不改写、迁移或重新宣称旧运行通过新协议。 |

生产 `scripts/sw_review.py`、`scripts/core/verification.py` 和 `scripts/core/execution.py`
没有修改，也没有引入自动审批。Core 仍只在 CAD 及清理结束后做终态适配，不能声称
真实建模步骤由 Core 调度。

## 可维护的手动 CI 准入

`windows-cad-regression.yml` 仅支持 workflow_dispatch，没有 PR 或 pull_request_target
真机触发。第一阶段在 GitHub 托管 Ubuntu 上检验以下事实，未知/API 失败均阻断，
不会分配自托管 CAD Runner：

1. 仓库名称和不可变 ID 匹配可信仓库；必须为受保护分支，不接受 tag。
2. GitHub API 确认分支保护且分支 HEAD 与触发 SHA 相同，拒绝已移动的分支。
3. 有效 ruleset 至少要求一人审批及必需状态检查。
4. 原触发者与重跑者均为该仓库 admin / maintain；普通 write/read 不足。
5. `cad-validation` 已存在，有必需审批人、禁止自行审批，且仅允许受保护分支部署。
6. API 可见空闲、在线且标签匹配的 Windows CAD Runner。分页不完整也不假定通过。

仅核验通过后，CAD 作业进入 `environment: cad-validation` 的服务器端人工审批。
不是“先调度自托管机，再在机上拒绝”。checkout 固定触发 SHA，不保留 Git 凭据，
使用每个 run_id / run_attempt 的新目录；已有目录直接 BLOCKED，不清除用户文件。
全量离线回归和 deterministic eval 先于真机，Python 父子进程统一 UTF-8。
旧 SolidWorks / AutoCAD 回归保留为显式可选输入，默认 Golden 不依赖 AutoCAD。
所有本工作流第三方 Action 固定已核对的完整 SHA，静态语法由 actionlint 校验。

准入结果只说明本工作流可以进入审批阶段，不证明整体 Runner 隔离已完成；报告
始终明确 `scope=workflow_admission_only`、`safety_acceptance_complete=false`。
不得把环境审核 PASS 或本地真机 PASS 写成远程安全验收完成。

## 实际 GitHub 设置与人工配置条件

只读审计发现仓库为公开的个人仓库，main 的规则集已启用，但审批人数为 0；
`cad-validation` 不存在，Runner 数为 0，`CAD_CI_AUDIT_TOKEN` 未配置。
因此当前准入应为 BLOCKED，远程 CAD CI 未执行。

管理员必须完成并提供可复核证据：

- main 及允许真机运行的分支使用 ruleset，至少一人审批、必需 CI，限制强推和删除；
  审核 bypass 列表，保护工作流、授权脚本和 CAD 测试来源。
- 创建 `cad-validation`：Required reviewers、Prevent self-review、仅受保护分支，
  并在界面关闭管理员绕过保护。需要另一位有资格的审批人，不能只有触发者自己。
- 配置 `CAD_CI_AUDIT_TOKEN`：只选本仓库，Administration:read、Actions:read、
  Metadata:read，无写权限，设置短有效期和轮换负责人。普通 GITHUB_TOKEN 没有
  Runner 清单所需 Administration:read，不能假设它足够，也不能因此跳过核验。
  凭据只进入托管准入脚本，不进入 CAD 作业、不写日志；本阶段未创建凭据。
- 提供专用、隔离的 Windows CAD Runner，正确标签、64 位 Python、已授权的 SW2026、
  模板、材料库及可用桌面；不要把用户日常桌面注册为长期公开仓库 Runner。
- **跨工作流隔离必须单独解决**：本工作流的 if/Environment 不能约束另一个恶意
  PR 新增的工作流。采用可限制指定仓库和工作流的 Runner group，或另行审查可信
  私有控制仓库/隔离方案。当前个人公开仓库不能假定已有组织级 Runner group。
  还需审核外部贡献者工作流审批、Runner 网络/凭据隔离和故障后的清理流程。
- 最后用授权人员、受保护分支和独立审批实际运行远程流程，验证授权拒绝、审批阻止、
  证据上传及异常清理，才能重新评估 READY。本地结果不能替代这一步。

无需为了本 PR 自动修改上述安全设置；这些是未完成的人工前置条件。

## 可复用入口、配置和证据协议

```powershell
$env:PYTHONUTF8 = '1'
python -m pytest -q -rs
node --test tests/test_cad_ci_guard.cjs
python tests/evals/runner.py --output-dir output/offline-unique
python tests/solidworks_golden_workflow.py --case mounting_bracket --output output/golden-unique --runs 5 --expected-terminal blocked
```

共用入口只从 `CASE_REGISTRY` 分派已审核模块，不接受任意 Python 路径或其它后端。
旧安装板入口兼容；新增用例需要注册契约、模型验收及对应故障证据，不自动继承验证等级。
默认仍为严格 completed 模式；显式 blocked 模式要求五轮，只有人工复核是唯一阻塞时
acceptance_status=passed，task_status=blocked，manual_review_required=true。

`--runtime-config` 可读 JSON，仅允许 `part_template`、`material_database`、
`connect_timeout_seconds`（5..120）、`cleanup_timeout_seconds`（5..60）。路径相对配置文件
解析；缺省模板复用现有模板发现，材料库从已诊断的安装目录查找英文/简体中文库。
用例版本、材料条目、尺寸、容差、审批要求不能由配置覆盖。记录解析后的路径及 SHA-256，
不把材料库 hash 当作材料认证。Windows、64 位 Python、COM 依赖缺失、配置不可读或
文件不存在时保留明确 BLOCKED / acceptance failed 报告，不安装替代后端。

schema 1.2 在原有双状态、原始 Review、Core、Ledger、哈希及几何证据外，增加
runtime_config.json、runtime_diagnostics.json、实例内核创建时间及全局唯一 trace_run_id。
同名 run-01 也不能从其它套件复制 trace，Ledger 的 runId 与 Core 保持相同。PID 与创建时间共同
识别实例，避免 Windows 重用 PID 造成假失败。Core trace 必须关联同一 run/step、
验证副本一致、顺序正确且只有一个准确终态。符号链接、junction、硬链接和越界路径
在哈希或写入前拒绝，报告写入失败的回退路径也不能覆盖外部文件。

输出目录必须不存在；重复运行直接拒绝，旧证据不覆盖。只关闭本轮拥有的文档，只有
拥有进程且无未知文档时才请求退出，不全局杀进程。COM 单次调用永久挂起仍无法靠
连接/清理超时彻底解决；异常后必须由操作者核查拥有关系，不将未知清理结果当作通过。

## 核查依据

- [GitHub Environment REST 与权限](https://docs.github.com/en/rest/deployments/environments)
- [Runner 清单所需 Administration:read](https://docs.github.com/en/rest/actions/self-hosted-runners)
- [Runner group 工作流访问限制与公开仓库风险](https://docs.github.com/en/actions/how-tos/manage-runners/self-hosted-runners/manage-access)

## 本阶段完整修改清单

以下 12 个文件为 P0-1.2 变更；PR 相对 main 另外保留 golden-workflows.yaml 和两份历史证据索引，
共 15 个文件。历史索引不参与本阶段新协议的通过统计。

```text
.github/actionlint.yaml
.github/workflows/windows-cad-regression.yml
scripts/ci/cad_ci_guard.cjs
tests/golden_workflow_support.py
tests/solidworks_golden_workflow.py
tests/solidworks_golden_mounting_bracket_2026.py
tests/test_solidworks_golden_mounting_bracket_2026.py
tests/test_golden_workflow_support.py
tests/test_cad_ci_guard.cjs
docs/architecture/real-golden-workflow-acceptance.md
docs/architecture/real-golden-merge-readiness.md
docs/architecture/evidence/p0-12-real-golden-2026-10-23.json
```

## 失败及修复记录

- 新增“配置缺失”用例初次失败，暴露测试适配层把 `success=false` 和 `blocked` 同传后，
  Core 按工具失败归类。修正为前置阻断仅传 `blocked`，不改生产 Core；该情况仍是
  task blocked / acceptance failed，不能通过 expected-terminal 模式。
- 首次全量为 6 failed / 956 passed / 1 skipped，六项旧 CLI 测试出现 Windows 父子进程
  UTF-8 / GBK 解码不一致。统一 `PYTHONUTF8=1` 后全量通过；原失败日志保留。
- 首次 actionlint 不认识自定义 CAD 标签，增加项目配置后通过；原失败日志保留。
- 一次辅助进程查询误用不存在的 sw_api 模块，改用现有 scripts.sw_process；该查询没有
  启动或关闭 CAD。开发阶段故障注入均为合成输入，不计入真实 CAD 统计。

补充回归覆盖链接及硬链接保护、跨套件 trace 互换、事件乱序、错误 step、多重终态、
Verification 副本不一致、PID 重用、重复目录和越权配置。原有错误孔径、孔位、缺产物、
Review WARN/FAIL、清理失败、Ledger/哈希及 CLI 非零退出回归全部保留。

## 实际验收结果（2026-10-23）

真实执行代码提交为 `bbdda7c00f077f58baeffe97e075666b078dfe7e`；随后提交仅补文档和证据索引。

- 离线全量：**963 passed / 1 skipped**（104.44 秒）。跳过项为尚未生成桌面内嵌 Skill 的
  既有发布包检查，没有把它记作通过。
- CI 策略：**26/26** 合成快照故障注入通过；actionlint 通过。这些不是远程授权执行记录。
- deterministic mock eval：**37** 场景符合预期，escaped false completion 为 **0**，
  单独存储于 offline/eval；不计入下面的真实 CAD 数据。
- 本机真实 **SolidWorks 2026 SP01.1（34.1.1）** 五轮独立运行全部通过验收，命令退出码 **0**。

| 轮次 | 实际 PID | 原生 / STEP 体积 mm³ | task_status | acceptance_status | 清理 |
| --- | --- | --- | --- | --- | --- |
| 1 | 48492 | 94460.6196 / 94460.6196 | blocked | passed | PASS |
| 2 | 12520 | 94460.6196 / 94460.6196 | blocked | passed | PASS |
| 3 | 43636 | 94460.6196 / 94460.6196 | blocked | passed | PASS |
| 4 | 47668 | 94460.6196 / 94460.6196 | blocked | passed | PASS |
| 5 | 49280 | 94460.6196 / 94460.6196 | blocked | passed | PASS |

五轮均验证真实尺寸 120×80×10 mm、四个 Ø7 贯穿孔和 ±48/±28 mm 孔位、材料回读及密度、
两张完全定义草图、特征健康、SLDPRT 保存重开、STEP 导出回读和四视角预览。
Review 规则均为 PASS / 100，`manual_review_required=true`；Core 验证均 PASS，实际终态均
run.blocked、Recovery=user_action_required，唯一阻塞为 EXPECTED_MANUAL_REVIEW_REQUIRED。

几何成功率 **5/5=100%**；预期门禁正确率 **5/5=100%**；Task Completion **0**；
Test Acceptance **5**；False Completion **0**；清理成功率 **5/5=100%**。
PID+创建时间及 trace_run_id 均独立，最终无 SolidWorks 测试文档或进程残留，未关闭用户已有实例。
每轮 19 项文件，共 **95 项 SHA-256** 与 Ledger、原始 Review、快照和 Core trace 重新读取一致。
五轮无真机失败；保留全部开发失败记录。用相同真实证据复核严格 completed 模式仍为
acceptance failed / task blocked，未启动额外 CAD 或改写原报告。

实际运行命令（工作目录为仓库根目录）：

```powershell
$env:PYTHONUTF8 = '1'
python tests/solidworks_golden_workflow.py --case mounting_bracket --output output/p0-12-real-five-01 --runs 5 --expected-terminal blocked --runtime-config output/p0-12-runtime.json
```

本次 JSON 配置显式指定本机已经安装的原厂材料库，模板自动发现；安装路径和库文件 hash
记录在报告中，未写入代码默认值。此结果仅覆盖该 2026 安装和精确材料条目，不声称验证其它版本。

证据目录：

```text
E:\desktop\sw-skills\p0-real-golden-2026\output\p0-12-real-five-01
E:\desktop\sw-skills\p0-real-golden-2026\output\p0-12-offline
E:\desktop\sw-skills\p0-real-golden-2026\output\p0-12-evidence-20261023.zip
```

证据包共 121 个文件（含总哈希清单）；SHA-256：

```text
ce64a118beef1ac562641a61698b301fc793ef6a81084327988226f89a6af7ed
```

[本阶段证据索引](evidence/p0-12-real-golden-2026-10-23.json) 记录各轮报告 hash、实例创建时间、
唯一 trace、实际配置和 GitHub 设置快照。完整 CAD、预览及失败日志在本地证据包中；
大文件没有加入 Git，也没有上传远程 CI。历史两阶段证据保持原样。

**合并建议仍为 BLOCKED**：本机验收与代码回归已通过，但缺少受控远程执行所需的 GitHub
配置、Runner 隔离证据和实际远程验收；请保持 Draft。另保留 Core 仅终态适配、COM 永久
挂起恢复及无人复核自动审查均未验证的范围限制。
