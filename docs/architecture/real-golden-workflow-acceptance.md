# SolidWorks 2026 真实 Golden Workflow 验收

本验收面向自动化维护者与 QA，验证 P0-1 / P0-1.1 `mounting_bracket`。规格从
`golden-workflows.yaml` 的 `real_acceptance_2026` 读取：120 × 80 × 10 mm，
4 × Ø7 贯穿孔，孔中心 X=±48、Y=±28 mm，原厂材料库 6061-T6。
解析体积为 94460.619599741 mm³；长度容差 0.01 mm，体积容差 0.05 mm³。

## 构建与运行

使用 Windows、Python 3.12、已授权且完成首次启动的 SolidWorks 2026，
安装项目 `requirements.txt` 与 pytest。真机前先执行离线契约测试与既有
deterministic eval；后者使用夹具，不能证明 CAD 能力。

```powershell
python -X utf8 -m pytest -q -rs
python tests/evals/runner.py --output-dir output/p0-offline-eval
python tests/solidworks_golden_mounting_bracket_2026.py --output output/p0-golden-unique --runs 5
# P0-1.1：显式验收五轮正确人工门禁；业务任务仍然 blocked。
python tests/solidworks_golden_mounting_bracket_2026.py --output output/p0-11-golden-unique --runs 5 --expected-terminal blocked
```

输出根目录必须不存在；每轮目录独立且拒绝覆盖。每轮先保存 preflight/doctor
诊断，再检查全机 SolidWorks 进程为空。若用户已有实例或进程状态不可知，
记录 BLOCKED，不修改、关闭或杀死已有实例。不自动切换到 Mock/OCCT。

## 验收证据

复用 `sw_connect`、`sw_part`、`sw_sketch_quality`、`sw_measure`、`sw_review`
和 `sw_export`，不重新实现 COM 连接器。完全定义草图保留驱动尺寸并拒绝 Fix；
重建后从 B-Rep 独立读取一个实体、六个板体平面、四个内部圆柱面及八条圆边。
逐孔验证直径、中心、法向、轴向长度及圆边与两个板面的邻接，排除盲孔。
STEP 导入可能将一个完整孔壁拆成两个半圆柱面。验收保留原始面和边数据，
另外按同轴几何归并面积，并用裁剪圆弧的真实长度证明两个入口各为完整圆周；
缺失任一半面或半弧不能通过。不会仅按边数把槽弧视为孔，也不修改通用测量器。
同时验证解析体积、包络、厚度参数、原生 Boss/Cut 特征与草图健康状态。
从原厂材料库分配精确条目 `6061-T6 (SS)`（matid 164），回读材料名/数据库及
实际质量体积反算密度；不把不存在的 `6061-T6` 条目或自定义属性当作材料分配。
SW2026 Instant3D 返回 `ICE` 时按官方规则用 `GetTypeName` 回读底层 Cut 类型，
保留原始类型，不将未知类型直接解释为切除。

保存 SLDPRT 后关闭、重新打开并重新采集完整证据。STEP 必须非空且具有
ISO-10303-21 文件头，再由真实 SolidWorks 导入，复核实体与几何。
审查复用四视角 BMP 和原有规则；不忽略 WARN/FAIL、未知值或人工复核标志。
CAD 流程结束后通过 Execution Core 适配终态与 trace，通过 Artifact Ledger 记录产物与 hash。
`sha256.json` 覆盖本轮日志、诊断、几何证据、原生件、STEP、预览、Review、
报告、trace 和 ledger（清单自身不自哈希）。失败保留已有产物，不删日志。

每轮清理仅关闭本轮创建的未保存文档或路径处于本轮目录内的文档。
只有已确认拥有 PID 且无剩余文档时才请求 ExitApp；等待退出并比对进程快照。
不使用全局 CloseAll、按进程名终止或清理用户文件。清理不通过不得完成。

## 已知限制

当前通用 `sw_review.evaluate_review_report` 固定返回
`manual_review_required=True`。即使所有几何检查和规则评分通过，终态也只能是
`task_status=blocked`。默认严格完成模式返回非零；P0-1.1 显式预期阻塞模式可在
全部独立证据通过时报告 `acceptance_status=passed`、返回 0。该验收不会取消人工审查要求。
需后续经过审查的自动审查能力才能满足无人复核的五轮 `completed` 标准。

本测试不证明其它尺寸、装配、工程图、复杂孔、材料力学性质或多版本兼容性。
STEP 回读验证交付几何，不要求保留原生草图或材料。COM 若永久挂起，需由操作者
核查进程所有权再处理；本脚本不会猜测所有权并强杀进程。

## CI 边界

**当前 P0-1.2 机制已替代下述历史白名单**：受保护分支手动触发、托管机 API 准入、
Environment 人工审批和专用 Runner。配置缺失仍 BLOCKED，见
[合并前检查报告](real-golden-merge-readiness.md)。以下保留 P0-1.1 当时的限制及结果。

复用 `windows-cad-regression.yml`，只有仓库内指定
`test/p0-real-golden-mounting-bracket-2026` 分支的 `workflow_dispatch`
可访问自托管 CAD Runner。没有 PR/pull_request_target 触发，checkout 使用
触发分支；只读令牌、串行运行、不取消前一轮清理。证据由既有 always 上传步骤保留。
本地证据与离线结果应分别列出，禁止用 deterministic 37 场景 PASS 替代五轮真机结果。

硬编码分支是当前验收期的安全白名单：即使 PR 合并到 main，main 上手动触发也会
因 job 条件不符而跳过；删除该测试分支后没有可执行的真机入口。后续维护需单独
审查并更新受控分支白名单及 Runner 保护规则，不能改为任意分支前缀匹配、PR
触发或可由外部传入 checkout ref。本阶段保留此限制，不擅自放宽。

## P0-1.1 状态传播审计与边界

生产代码未修改：`sw_review.py` 仍输出原始规则结果和人工标志；
`core/verification.py` 可适配规则 PASS 并保留人工要求；`core/execution.py`
只在明确 PASS 且无需人工复核时 completed，否则按既有规则 blocked/failed。

旧真机脚本先把汇总状态设为 blocked，再以该状态作为 Core handler 结果。
Core 将其视为工具失败，未进入 Verification。因此旧记录只证明终态没有假成功，
不证明人工 Review 的 Core 传播链已经实际执行。

P0-1.1 在测试适配层把真实 CAD 执行事实与 Review 结果分开输入：CAD 成功时
handler success=true，原始 Review 完整保留，适配后的规则 PASS 与人工标志
进入 Verification。预期 trace 为 `tool.succeeded → verification.passed → run.blocked`，
Recovery 为 `user_action_required`。Core 仍在整个 CAD 流程及清理结束后调用；
报告明确标记 `core_scope=terminal_adaptation_only`，**没有验证真实 CAD 步骤由
Core 调度**，也没有新增自动审查策略。

schema 1.1 增加两个独立结果：`task_status` 为 completed/blocked/failed，
`acceptance_status` 为 passed/failed。旧 `status` 字段仅作为 task_status 的兼容别名。
`--expected-terminal` 默认 completed，人工要求未解除就返回非零；显式 blocked
模式强制 `--runs 5`，仅当五轮独立真机、所有几何/材料/草图/特征、重开、STEP、
原始 Review 规则、完整证据和清理都通过，且 Core 实际阻塞原因仅为人工要求时
验收通过。未知原因、额外阻塞、WARN/FAIL、缺文件、哈希或 Ledger 不全、清理失败、
Core/报告不一致和重复实例均不通过。套件结束再次核验每轮磁盘产物，防止早期
通过的文件在后续轮次中丢失。退出码按 acceptance_status，绝不修改 task_status。

证据先封存并核验，再计算验收结果；最终报告写入后重新生成 Ledger/清单并校验，
避免报告和哈希相互引用。Ledger 不哈希自身；SHA-256 清单包含 Ledger，不包含清单
自身。封存异常会记录失败并返回非零。离线故障注入使用临时目录的合成契约数据，
不被统计为真实 CAD 结果。

## 本次排错记录

- 首次离线测试收集失败：本仓库 `tests` 不是 Python 包，改为复用现有 eval
  测试的路径导入方式。修正后离线测试通过。
- `output/p0-probe-01/run-01` 真机失败：不存在精确名为 `6061-T6` 的库条目，
  原 API 调用没有产生材料；实际回读为空、密度 1000，被验收拒绝。同时检测到
  SW2026 的特征类型为 `Extrusion/ICE`。修正为解析并使用原厂真实材料条目，
  按官方接口回读 ICE 底层类型，未改核心连接或测量架构。
- `output/p0-probe-02/run-01` 真机失败：原生件和 Review 规则通过，STEP 回读
  产生八个半圆柱面和十六条半圆弧，原孔数规则拒绝。加入面积与完整圆周验证，
  离线故障注入证明缺半面/半弧仍失败。两次失败均保留证据，清理通过。
- 通用 Review 固定的人工复核标记未取消；它仍是无人值守完成的阻塞条件。

## API 核查依据

- [IFeature.GetTypeName2 与 Instant3D ICE 底层类型](https://help.solidworks.com/2022/English/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IFeature~GetTypeName2.html)
- [ICurveParamData 的裁剪参数](https://help.solidworks.com/2026/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.ICurveParamData_members.html)
- [ICurve.GetLength3 的裁剪曲线长度](https://help.solidworks.com/2024/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.ICurve~GetLength3.html?format=P&value=)

## 2026-10-23 本机执行结果

Base SHA：`f9d6efbecf297bcdfffc451de81ba3a7bdea6a0d`。
真实验收执行代码 SHA：`0f27516082f9df132cb42d43a2f5f9ea33b47471`。
本次文档和证据索引在执行后单独提交。环境：SolidWorks 2026 SP01.1，revision
`34.1.1`，Python 3.12.10，Windows 11。

离线全量结果：**900 passed / 1 skipped**（61.43 s）。跳过项是尚未生成桌面
内嵌 Skill 的发布包检查；未把跳过项计作通过。deterministic mock eval 的
37 个场景预期结果正确、escaped false completion 为 0；它不是 CAD 真机结果。

| 轮次 | 独立 PID | 原生/重开/STEP 几何 | Review 规则 | 清理 | 验收终态 |
| --- | --- | --- | --- | --- | --- |
| 01 | 47484 | PASS | PASS / 100 | PASS | BLOCKED |
| 02 | 14168 | PASS | PASS / 100 | PASS | BLOCKED |
| 03 | 19516 | PASS | PASS / 100 | PASS | BLOCKED |
| 04 | 29352 | PASS | PASS / 100 | PASS | BLOCKED |
| 05 | 40840 | PASS | PASS / 100 | PASS | BLOCKED |

五轮均为一个实体，原生件重开及 STEP 回读体积均为 **94460.6196 mm³**；
四孔均为 Ø7，中心为 (±48, ±28) mm；两个草图均完全定义、无 Fix、无悬空，
材料回读 `6061-T6 (SS)`，实际密度 2700 kg/m³。每轮进程启动前和退出后的
快照为空，关闭后的剩余文档数为 0。每轮 17 项文件 hash 全部重新校验，
共 85 项一致；Artifact Ledger 亦复核一致。

**P0-1 没有完成：0/5 completed，5/5 blocked。** 唯一现存验收阻塞为通用
Review 的 `manual_review_required=True`；没有取消标记或将其静默当作通过。
真机命令因此按设计返回退出码 1。未执行 GitHub 自托管 Runner，也未验证其它版本、
其它规格或无人复核交付。没有进行 merge。

工作目录：`E:\desktop\sw-skills\p0-real-golden-2026`。

```text
output/p0-final-five-01/summary.json
output/p0-final-five-01/run-01 ... run-05/
output/p0-probe-01/run-01/              # 首次真机失败证据
output/p0-probe-02/run-01/              # STEP 分面排错证据
output/p0-offline/                     # 离线日志和 deterministic eval
output/p0-evidence-20261023.zip         # 全部报告、日志、CAD、预览、hash
```

证据包 SHA-256：
`01b6f43954d6304c5f72c3de99a6ecf6206333347063cec3cae5dd1b1fd9071a`。
原生/STEP 二进制与 BMP 不提交到 Git；可审查的
[结构化索引](evidence/p0-real-golden-2026-10-23.json)包含每轮报告和清单的 SHA-256。
[Draft PR #39](https://github.com/wzyn20051216/solidworks-automation-skill/pull/39)。

## 2026-10-23 P0-1.1 实际复测结果

本阶段起点为 `13e22ca5244b808d04fde2a51346c800aa8a52d1`；执行代码 SHA 为
`6e8903cdea3cdf36b0e4fe15e55779cdc663ac39`。生产 Review / Verification / Execution
Core 均未修改，历史 P0-1 报告和失败证据保持原样。

全部离线回归 **942 passed / 1 skipped**（66.42 s）；跳过原因为桌面内嵌 Skill
尚未生成，另附 UTF-8 日志说明。deterministic mock eval 37 场景预期结果正确，
escaped false completion 为 0。这些是离线契约验证，不能代替下列真机结果。
新增故障注入覆盖错误孔径/孔位、STEP 孔径、材料/草图、Review FAIL/WARN/未知、
人工标志缺失、清理失败、遗留文档/进程、用户实例归属、许可证阻塞、缺产物、
哈希/账本不全、错误终态、错误人工标记、重复 PID、不足五轮和最终封存失败。
CLI 契约测试确认只有正常预期阻塞返回 0，关键注入故障均非零，默认完成模式仍非零。

真实命令（输出目录原先不存在）如下；退出码 **0**：

```powershell
python -X utf8 tests/solidworks_golden_mounting_bracket_2026.py --output output/p0-11-real-five-01 --runs 5 --expected-terminal blocked
```

| 轮次 | 独立 PID | 几何/交付/证据/清理 | task_status | acceptance_status | 人工复核 |
| --- | --- | --- | --- | --- | --- |
| 01 | 39596 | PASS | blocked | passed | true |
| 02 | 46956 | PASS | blocked | passed | true |
| 03 | 41440 | PASS | blocked | passed | true |
| 04 | 22712 | PASS | blocked | passed | true |
| 05 | 20972 | PASS | blocked | passed | true |

五轮真实几何成功率 **5/5（100%）**；预期门禁正确率 **5/5（100%）**；
Task Completion **0**；Test Acceptance **5**；False Completion **0**；
安全清理 **5/5（100%）**。五轮均为 SolidWorks 2026 revision 34.1.1，
原生件重开和 STEP 回读体积均为 94460.6196 mm³。五轮实际 trace 均含
`tool.succeeded → verification.passed → run.blocked`，Verification=PASS，
manual_review_required=true，Recovery=user_action_required，且无 tool.failed / run.completed。
每轮均只有 `EXPECTED_MANUAL_REVIEW_REQUIRED`，原始 Review 规则为 PASS / 100 分。

套件结束和交付前均重新读取全部证据，85 项文件 SHA-256 及 Artifact Ledger
复核通过，进程快照为空且残留文档为 0。以相同真实证据运行严格 completed 门禁
复核得到 acceptance_status=failed、task_status=blocked，未改变原始真实运行记录。
本阶段没有真机失败轮次；所有故障注入均在离线临时目录，不改真实 CAD 或原始证据。

```text
output/p0-11-real-five-01/summary.json
output/p0-11-real-five-01/run-01 ... run-05/
output/p0-11-real-console.log
output/p0-11-real-exitcode.txt
output/p0-11-offline/pytest-full.log
output/p0-11-offline/eval/eval_report.json
output/p0-11-offline/real-evidence-strict-control.json
output/p0-11-evidence-sha256.json
output/p0-11-evidence-20261023.zip
```

完整证据包 SHA-256：
`bc8c055c7ce314f3d148a43ce3d7dbd5ff8b9ef3a4c6519ddd3a234dd26a01c0`。
[P0-1.1 结构化索引](evidence/p0-11-real-golden-2026-10-23.json)记录每轮报告与清单哈希。
本次完成的是**测试状态分层和预期门禁验收**；未启用无人复核策略，未验证 Core
逐步调度真实 CAD，未运行远程自托管 CAD Runner。硬编码分支的合并维护限制见上文。
