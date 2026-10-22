# SolidWorks Standard Parts

`solidworks-standard-parts` 是 `solidworks-automation` 的标准机械零件生成子技能，参数化生成
渐开线直齿圆柱齿轮、圆柱压缩弹簧和滚子链链轮。

## 设计理念

标准件生成器是 SolidWorks 宏命令集最常见、最受工程师欢迎的能力之一。本子技能把它拆成两层：

- **可验证的几何层**：`scripts/standard_parts_geometry.py` 是纯 Python、无 COM 依赖的几何/力学
  计算，可在无 SolidWorks 环境下离线单测（`tests/test_standard_parts_geometry.py`）。
- **需真机验证的 COM 层**：三个生成器用父技能的 `sw_part`/`sw_session`/`sw_export`/`sw_review`
  把轮廓画进 SolidWorks、拉伸/扫描/打孔、重建回读并自审查。

## 当前能力

| 零件 | 输入 | 已单测几何 | 真机门槛（pilot） |
|---|---|---|---|
| 渐开线直齿轮 | 模数、齿数、压力角、变位、齿宽、中心孔 | 分度/基/齿顶/齿根圆、齿厚、尖齿判定、闭合齿廓 | 特征落盘、根切、啮合精度 |
| 圆柱压缩弹簧 | 线径、中径、自由长、圈数、端型、G | 螺旋线、C 值、实体长、刚度 k | 扫描实体、端圈并紧磨平、压并高度 |
| 滚子链链轮 | 链节距、滚子直径、齿数、厚度、中心孔 | 节圆 PD、齿顶圆 OD、齿根圆、滚子座半径 | 精确啮合齿形、齿侧修形 |

## 快速使用

```powershell
python scripts\sw_preflight.py

python subskills\solidworks-standard-parts\scripts\create_spur_gear.py --module 2 --teeth 20
```

弹簧与链轮示例见 [SKILL.md](SKILL.md) 与 `examples/`。

## 来源与许可

功能灵感来自公开的第三方 SolidWorks 宏命令集（与达索/ SolidWorks 官方无隶属关系）。本子技能是
独立的 Python 重写，不包含也不分发任何第三方编译宏（.swp/.swb）代码。
