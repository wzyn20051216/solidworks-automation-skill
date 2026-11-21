# 筋特征修复的 SolidWorks 2026 回归

基于主线 `fbaf604` 集成 PR #83 后，使用 SolidWorks 2026 SP1.1（Revision `34.1.1`）验证生产脚本。被测 `scripts/sw_part.py` 的 SHA-256 为 `5661ebb75bee0a8c11a2e31acee078111c3dc7d3ae90e0782a56e5d5034ea066`。

真机验证调用 `tests/manual_rib_regression.py` 的 `run()`，由 `SolidWorksSession(version=2026, wait_seconds=60, visible=True)` 管理独占空白会话。草图选择、InsertRib、几何回读和保存重开均为真实 COM 操作。

| 场景 | 结果 |
| --- | --- |
| 双侧厚 6 mm | 侧面 Z 为 −3、3 mm，新增体积约 3600 mm³ |
| 单侧厚 6 mm | 侧面 Z 为 0、6 mm，新增体积 3600 mm³ |
| 在已有筋的零件中创建第二筋 | 返回第二筋；原筋保留，厚度 4 mm，侧面 Z 为 10、14 mm |
| 第二筋持久化 | 保存关闭重开后两条筋和厚度定义保留，总体积约 58000 mm³ |
| 不相交草图 | 返回 None，旧筋数量和实体体积保持一致 |
| 模型健康与收尾 | 重建后无特征错误、警告或未知状态；结束时文档数为 0，本轮启动实例已退出 |

单双侧和两条筋的原生预览已目视复核。原生模型、预览和原始报告保留在本机，公开记录仅包含脱敏结果。

可从独占空白会话重跑原有手工入口。输出目录须不存在，脚本本身会保留应用窗口供观察。

```powershell
python tests/manual_rib_regression.py --version 2026 --output output/rib-sw2026-new-run
```

此验证覆盖上述直角支架及失败路径。复杂筋轮廓、装配、运动及制造放行需按具体任务另行验证。贡献者的 SW2024 记录见 [rib-sw2024-regression.md](rib-sw2024-regression.md)。
