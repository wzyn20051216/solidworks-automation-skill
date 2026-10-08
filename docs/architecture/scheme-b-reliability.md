# 方案 B：既有架构的可靠性修复与验收

2026-10-08；支持与原生验收目标为 SolidWorks 2026。实施基线为 `592e655`，保留社区 PR #21 的提交历史，修复相关 Issues 的执行与交付契约。

## 改动与真正原因

| 问题 | 原因 | 修复与验收边界 |
|---|---|---|
| 执行失败仍显示成功 | 非异常返回被当成成功；Core 在最终 Review 之前完成 | 必要标记 false 失败、未知证据 blocked；Review 的 required FAIL 不受顶层 PASS 覆盖；只有 PASS 且无需人工复核才 completed；Queue 与 Core 终态统一 |
| #7 草图缺少设计参数 | 几何坐标被误当成约束与尺寸，缺少保存重开验证 | 基础圆/矩形补充尺寸与关系，回读完全定义、尺寸与 Fix；审查检查草图是否被特征消费；复杂草图仍需设计参数与人工复核 |
| #14 阵列不稳定 | 原生成员/参数签名错误，未可靠选择母特征和方向实体 | 精确母特征、真实平行直边、20 参数线性阵列；圆周阵列选明确轴；选择失败立即停止 |
| #5/#15 进程与文档生命周期 | Dispatch 不代表新进程，ROT 未就绪时可能重复启动；文件长期累积 | 读取 PID/实际 Revision、等待已有实例；仅清理本轮登记文档和确认归属的空实例；默认 8 文档预算；清单不可读时阻断创建 |
| #20/#22 远端只能得到本机路径 | 只有 stdio，HTTP 默认 Host 校验与远端地址不符，路径不能作为远端文件内容 | 同一个 MCP 增加可选 HTTP、显式 Host/Origin 与 Bearer；复用 Ledger 登记不透明产物 ID，返回 PNG 内容块/原始资源/有界块并核对 SHA-256 |
| #12 注塑 DFM 入口缺失 | 现有工艺白名单和规则分发没有注塑 | 加入 `injection_molding`，复用 NeutralCadDocument、Profile 和报告；拔模、筋厚、壁厚变化、倒扣方案、浇口与顶针水路间距按声明筛查 |

保留现有 Worker、Queue、Reviewer、Artifact Ledger、Policy Gate 和启动互斥锁。Recovery 仍只生成决策。原有 60 个 MCP 工具逐项比较名称与完整 Input Schema 一致；新增 `cadstudio_read_artifact`，共 61 个工具。默认仍是 stdio，HTTP 是同一进程的可选传输。

## 验证结果

- Windows/Python 3.12 全量 pytest：810 passed，无跳过、失败或警告；Skill 自检通过，MCP 验证 61 工具；发布一致性检查通过，217 个内嵌运行时文件。
- 禁用 `pythoncom`、`win32com`、`comtypes` 导入后，Core/Eval：125 passed。
- 37 个 deterministic 场景沿用 `golden-workflows.yaml`；基线 v3 的 nominal 为 10/10，warning 归 guardrail 并 blocked，原始完成比例 21/37（仅诊断），假成功泄漏 0。
- SolidWorks 2026 SP1.1 / Revision 34.1.1：线性 3 孔和圆周 4 孔实际 B-Rep/解析体积一致；保存重开后草图具有尺寸、无 Fix 且被特征消费；厚度 8→10 mm 后孔径与孔中心位置不变。
- 同一真实 CAD 测试实例内，文档预算阻止额外创建，Session 结束只关闭本轮文档，模拟用户未保存文档与进程保留；最终测试实例自行清理。
- 实际原生模型经 HTTP 导出 STEP 并由 MCP 资源取回，31,651 字节，SHA-256 `87388f90be31e299eb4d4e3c6dd12e4310d690ab08c16fe1be40552b10eb9ae2` 一致；BMP 经只读工具变为 PNG 内容块，目视确认 3 孔模型。Review 仍为 `review_required`。
- 独立 HTTP 协议测试验证握手、工具发现、401、错误 Host/Origin 拒绝、PNG 与二进制资源；注塑规则另有真实 CLI 落盘测试。

## 如何运行与复核

仓库根目录，使用安装了依赖的 Python 3.12：

```powershell
python scripts/sync_bundled_skill.py
python -m pytest -q
python scripts/validate_skill.py
python scripts/validate_mcp.py
python scripts/release_check.py
python tests/evals/runner.py
```

真机测试要求没有正在使用的 SolidWorks 实例，输出目录必须是新目录：

```powershell
python tests/solidworks_reliability_b_regression.py --output C:\cad-test\reliability-b-2026
```

`report.json` 记录体积、孔位、草图证据及文档清理结果。该脚本不进入默认 pytest，CI 无 SolidWorks 时不假装完成原生验收。HTTP 部署与产物读取步骤见 [`../../mcp-server/README.md`](../../mcp-server/README.md)。

## 已知限制

- 按当前范围，旧版 SolidWorks 不再安排兼容实现或真机验证；保留的通用 COM 防御逻辑不构成旧版支持承诺。
- 真机证据限于上表明确场景；不能据此保证所有复杂零件、第三方加载项或高负载任务不会崩溃。
- 注塑仍为 `pilot` 声明型规则筛查；未自动识别完整 B-Rep 拔模/倒扣，未接入模流，规则通过也需工程复核。阈值由用户/工艺/供应商明确声明，不充当材料通用认证值。
- HTTP 验收使用本机服务和远端 Host 头及真实 MCP 客户端，未验证跨机器网络、防火墙、TLS 代理；输入上传、并发 CAD 写入不在本次范围。
- 大文件分块逐次校验内容，适合交付读取；本次没有实现大文件上传或断点上传。
- 综合 PR #23 的独立 comtypes Pack and Go 回退与打开错误分类尚未合入；其提交与当前主分支有冲突，需独立适配与验证，不能用本次常规 Session 的验收代替。
