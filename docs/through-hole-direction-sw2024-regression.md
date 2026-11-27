# SW2024 圆形通孔切除方向回归

在标准基准面创建圆形通孔时，若实体位于旧默认切除方向的另一侧，
`solidworks_create_hole_feature` 会返回 `SW_HOLE_NOT_CREATED`。
圆形通孔请求可显式传入 `reverse_direction=true`，沿同一草图平面的反向单侧贯穿。
省略参数保持旧默认。失败仍返回已有诊断，不自动重试或移除失败草图。

## 实测

- Windows 11、Python 3.14.7、SolidWorks 2024 SP0.1（Revision 32.0.1），Python COM。
- 桌面控制端和独立 MCP 服务通过版本化 `SldWorks.Application.32` 附着同一个可见的既有实例。
- 对照用板均在本轮新建，尺寸 80 × 60 × 20 mm，前视基准面为板的一侧端面。孔直径 6 mm，孔心位于板中心。
- 基线 `500c26a` 上，材料位于 Z=0…20 mm 时默认方向成功。材料位于 Z=−20…0 mm 时相同请求失败，实体体积保持不变。

| 修订版用例 | 实体范围 Z（mm） | 通孔请求 | 实际几何与返回 |
| --- | --- | --- | --- |
| 默认方向匹配 | 0…20 | 省略方向参数 | 通过，两个孔口位于 Z=0、20 mm |
| 默认方向不相交 | −20…0 | 省略方向参数 | `SW_HOLE_NOT_CREATED`，无孔口，体积保持不变，诊断 `Dir=true` |
| 显式反向匹配 | −20…0 | `reverse_direction=true` | 通过，两个孔口位于 Z=−20、0 mm |
| 显式反向不相交 | 0…20 | `reverse_direction=true` | `SW_HOLE_NOT_CREATED`，无孔口，体积保持不变，诊断 `Dir=false` |

调用使用真实 stdio MCP 工具。两种成功件均为单实体，两个原生圆边分别位于板的两端面，
孔口同轴、圆心在板中心，半径 3 mm。各减料约 565.486678 mm³，符合 Ø6 × 20 mm 通孔体积。
重建和特征健康检查通过。成品保存关闭后只读重开，孔口和体积结果一致。等轴测预览已目视复核。
失败调用均返回 `retryable=false`，各留下一张未消费的圆草图，仅关闭本轮失败测试件且不保存。
两轮结束均为 0 个打开文档，既有应用实例保留。原生文件及原始报告仅保留于本机。

候选生产文件 SHA-256：

- `scripts/sw_part.py`：`5661ebb75bee0a8c11a2e31acee078111c3dc7d3ae90e0782a56e5d5034ea066`
- `scripts/sw_hole_features.py`：`f632ef24f5a86fd06d28cb0953cb02b3d490d7c8a88e1186e5320d3cc831051e`
- `mcp-server/server.py`：`f2004790487b69e7e92b1034bc78dc2c479261ccb29a63ac66d481cc4cb71d9b`

## 复跑

使用无用户文档的可见 SolidWorks 会话。输出目录须不存在。

```powershell
python tests/manual_through_hole_direction.py --version 2024 --output output/through-hole-direction-new-run
```

在原基线工作区运行时，将该手工脚本复制到该基线的 `tests/` 目录并加 `--baseline`，
只运行默认方向的正反材料侧对照。离线测试位于 `tests/test_sw_hole_features.py` 与
`tests/test_mcp_hole_diagnostics.py`，覆盖显式参数转发、其他孔槽类型的参数拒绝，以及失败时
实际切除方向和禁止自动重试的契约。

本轮验证标准前视基准面上的圆形通孔，未验证 SW2026、斜面、盲孔、沉孔、沉头孔、运动、装配干涉及制造放行。
[#82](https://github.com/wzyn20051216/solidworks-automation-skill/issues/82) 的自变量为零件是否保存后重开，
本轮在新建板上按材料侧复现，未定位 #82 的根因。保存重开复核仅用于验证成功创建的孔持久化。
