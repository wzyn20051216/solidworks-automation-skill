# 可选 ROT 附着回退：SW2024 原生回归

## 环境与候选身份

- Windows、SolidWorks 2024 SP0.1，`RevisionNumber = 32.0.1`。
- 验证时仅有一个版本明确、已运行的目标实例，窗口可见。
- 后端为 Python COM，版本化 ProgID 为 `SldWorks.Application.32`；附着既有用户实例，不是由测试新建或取得退出所有权的独占实例。
- 被测 `scripts/sw_connect.py` 的 SHA-256：`1fc00d022d41b345bc3d619c3b3aa76bbed73ed2bb7640ad5016fdae79b604f3`。
- 本次自然状态下版本化 `GetActiveObject` 不可用；没有注入 ROT 查询故障。
- 原始报告留在本地，本文仅保留脱敏摘要，不包含 PID、文档身份或机器路径。

## 实际结果

| 入口 | `SW_ATTACH_EXISTING_DISPATCH` | 结果 |
|---|---|---|
| 直接 Python API | 未设置 | 返回 `SW_INSTANCE_NOT_READY`；连接调用没有执行 `Dispatch` |
| 直接 Python API | `1` | 通过真实版本化 `Dispatch` 附着到原 PID；`started_by_cad_studio=False` |
| 新启动的 MCP stdio 服务 | 未设置 | `solidworks_connect` 返回 `SW_INSTANCE_NOT_READY` |
| 新启动的 MCP stdio 服务 | `1` | `solidworks_connect` 附着到原 PID，回读年份为 2024 |

每组测试后均核对进程清单、文档清单、活动文档身份和可见性没有变化。测试专门创建了一个空零件并标记为未保存；连接及 MCP 客户端退出后，该文档仍打开且保持未保存状态，SolidWorks 实例没有被退出。验证完成后只关闭本次专用文档，不保存，恢复原来的空白会话。

测试脚本建立观察快照时另有一次真实版本化 `Dispatch`，也核对其 PID、版本及进程清单；该准备调用不计入表中“连接调用”的次数。这不是对构造器无副作用的普遍保证。

## 复现

从仓库根目录使用已安装项目依赖的 Python 执行。先确认目标版本已有唯一实例；使用 `--create-test-document` 时还要求该实例没有打开文档。输出目录必须不存在。

```powershell
python tests/manual_rot_attachment.py --version 2024 --create-test-document --output outputs/rot-native-new-run
```

默认不传 `--create-test-document` 时，仅核对既有文档状态。脚本不会保存文档或退出 SolidWorks；若验证中途失败，专用未保存文档可能仍保持打开，应检查报告及窗口后处理。

脚本启动独立的 MCP 服务并临时传入进程环境，不改用户配置。若自然 ROT 可用，脚本会额外对直接 API 注入 ROT 查询失败，仍使用真实 `Dispatch`；报告用 `controlled_rot_failure` 明确区分。MCP 结果反映自然环境，不伪造其 ROT 故障。

## 验证边界

- SW2026 尚未实测；本记录不宣称达到项目 SW2026 原生验收目标。
- 未知版本、同版本多实例或未指定版本时目标不唯一、错误 PID、版本不符、进程清单变化或不可读等拒绝路径由离线测试覆盖，没有在真机上制造这些状态。
- `Dispatch` 在部分安装环境可能启动其他实例。回退默认关闭；身份不符后停止后续操作，不取得未知实例的退出所有权，也不自动重试。应先检查实例及未保存文档。
- 此选项提供明确启用的恢复路径，不修复 Windows ROT 机制。
- 本次没有验证模型几何、装配配合、干涉、导出、运动、载荷或制造放行；没有对既有模型做保存重开试验。测试仅验证连接、文档状态保留及客户端退出后的会话状态，不代表上游 CI 已通过。

后续规范修订只补充手工脚本的中文文档字符串与本说明，脚本去除文档字符串后的 AST 保持一致，生产文件哈希不变；上述真机记录继续有效，没有为说明文字变更重复运行 CAD。

## 与筋修复 PR 的组合检查

基于共同上游 `36bc337357723b9763759ff06e4a1afab990b823`，与[筋修复 PR #83](https://github.com/wzyn20051216/solidworks-automation-skill/pull/83) 的 `783319a6583e195e5cf1499ff1ae4ef4151a1c4d` 组合：两份改动没有重叠文件，按两个顺序均可干净应用，得到同一 Git tree。组合结果的筋封装、连接归属、文档身份及发布契约相关回归共 61 项通过。

该检查是离线组合验证，没有执行组合版本的 CAD 真机回归；不替代两份各自的 SW2024 记录，也不代表 SW2026 或上游 CI 通过。结论仅适用于上述版本，后续上游或分支变化后需重新评估。
