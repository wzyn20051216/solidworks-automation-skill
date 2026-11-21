# 可选 ROT 附着回退：SolidWorks 2026 验收

基于主线 `524a4a3` 独立吸收 PR #84，并修正附着后写入既有窗口 `Visible` 的问题。
`visible` 只用于本轮新启动的实例；普通 ROT、延迟 ROT 和可选 Dispatch 附着均保留用户窗口状态。
回退后完整比较 PID→版本清单，版本变为未知或改变也拒绝继续。

## 真机证据

- SolidWorks 2026 SP1.1，Revision `34.1.1`。
- 被测 `scripts/sw_connect.py` SHA-256：`32aef993532ca1db6eabd5118bdda87474bdeea2812612a20e27a4c077baa460`。
- 本轮自启独占实例，再把它作为既有实例验证附着；附着入口始终回报 `started_by_cad_studio=False`。
- 分别验证可见窗口及专用未保存零件、隐藏窗口及空白会话，每组各 8 个案例，共 16 个案例。
- 直接 Python API、独立 MCP stdio 均覆盖自然 ROT 和受控 ROT 查询失败，开关分别关闭、开启。
- 自然 ROT 可用：均连接同一 PID。受控查询失败：默认阻止 Dispatch，返回 `SW_INSTANCE_NOT_READY`；显式启用后，真实版本化 Dispatch 返回同一 PID。
- 每次都故意请求与原窗口相反的 `visible`；进程清单、文档清单、活动文档、未保存标记及窗口可见性均保留。
- MCP 客户端退出后实例和文档仍存在；结束时关闭本轮专用空文档，不保存，再由最外层所有者退出本轮自启实例。

本机自然 ROT 可用，故障条件通过仅替换 `GetActiveObject` 注入；Dispatch、进程枚举和 SolidWorks COM 操作真实执行。没有宣称复现了本机自然 ROT 故障。
原始报告留在本机，公开记录不包含 PID 或私人机器路径。SW2024 为贡献者原始记录，见 [rot-sw2024-regression.md](rot-sw2024-regression.md)，本轮未独立复验。

## 重跑与边界

使用唯一、版本明确的既有实例，输出目录须不存在。专用未保存测试文档仅可在空白会话创建。

```powershell
python tests/manual_rot_attachment.py --version 2026 --create-test-document --output output/rot-native-new-run
```

脚本在自然 ROT 可用时对直接 API 和独立 MCP 服务额外注入查询故障；所有附着测试均请求相反显示参数。脚本本身不会退出 SolidWorks。异常中断后应检查专用未保存文档，不自动清理未知文档。

`SW_ATTACH_EXISTING_DISPATCH=1` 仍默认关闭。Dispatch 在其他安装环境可能启动新进程，事后身份检查不能防止构造动作本身；身份不符会停止，不退出未知进程，不自动重试。此功能不修复 Windows ROT，不代表建模、运动或制造验收。
