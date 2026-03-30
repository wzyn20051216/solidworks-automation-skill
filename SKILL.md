---
name: solidworks-automation
description: "SolidWorks CAD 自动化技能，可通过 Python COM 接口与 OpenClaw / Codex / Claude 协作控制 Windows 上运行的 SolidWorks，用于零件建模、装配体、工程图、钣金、焊件、仿真、文件导出、自定义属性、设计表与配置管理；当用户提到 SolidWorks、SW、OpenClaw、龙虾、3D 建模、CAD、零件、装配、工程图、钣金、焊件、导出 STEP/STL/PDF、BOM、设计表或 FEA 仿真等需求时使用。"
metadata: { "openclaw": { "homepage": "https://github.com/wzyn20051216/solidworks-automation-skill", "os": ["win32"], "requires": { "anyBins": ["python", "py"] } } }
---

# SolidWorks 自动化技能

## 快速开始

### 环境要求

- Windows 系统 + SolidWorks 已安装并运行
- Python 3.8+ + `pywin32`（`pip install pywin32`）
- 如果通过 OpenClaw 使用，确保技能目录位于 `~/.openclaw/skills/solidworks-automation/` 或 `~/.agents/skills/solidworks-automation/`

### 连接 SolidWorks

```python
import sys; sys.path.insert(0, r"SKILL_DIR/scripts")
from sw_connect import connect_solidworks, mm, deg, new_document

sw, model = connect_solidworks()  # 连接已运行的实例
```

> 将 `SKILL_DIR` 替换为此技能的实际安装路径。

## 核心工作流

根据用户需求选择对应模块：

| 需求 | 脚本 | 参考文档 |
|---|---|---|
| 连接与文档管理 | `scripts/sw_connect.py` | - |
| 零件建模（草图+特征） | `scripts/sw_part.py` | `references/part-modeling.md` |
| 装配体操作 | `scripts/sw_assembly.py` | `references/assembly.md` |
| 工程图出图 | `scripts/sw_drawing.py` | `references/drawing.md` |
| 文件导出 | `scripts/sw_export.py` | `references/export.md` |
| OpenClaw 控制 SolidWorks | - | `references/openclaw.md` |
| 钣金/焊件/仿真/属性 | - | `references/advanced.md` |
| 常见错误排查 | - | `references/troubleshooting.md` |

## OpenClaw 协作方式

1. 先确认 SolidWorks 版本、界面语言、输入文件路径、输出路径，以及目标操作（建模 / 装配 / 出图 / 导出）。
2. 优先复用 `{baseDir}/scripts` 下已有模块，不要重复手写 COM 连接逻辑。
3. 在 OpenClaw 的 `exec` / `shell` 能力中执行短小、一次性的 Python 脚本，最小导入集如下：

```python
import sys
sys.path.insert(0, r"{baseDir}/scripts")
from sw_connect import connect_solidworks, mm, deg, new_document
```

4. 执行后检查返回对象是否为 `None`、保存/导出是否成功、输出文件是否落盘。
5. 如果需要更完整的 OpenClaw 工作流、提示词示例和排障建议，再读取 `references/openclaw.md`。

## 使用流程

1. 确认 SolidWorks 正在运行
2. 调用 `connect_solidworks()` 连接实例
3. 根据需求调用对应脚本函数（组合使用）
4. 使用 `sw_export.py` 保存/导出文件

## 关键注意事项

- **单位**：API 统一使用**米**。用 `mm(50)` 转换 50mm 为 0.05m，用 `deg(90)` 转换角度
- **版本**：使用 `SldWorks.Application` 自动连接，兼容所有版本
- **选择**：特征操作前需用 `SelectByID2` 选择目标实体
- **VARIANT**：by-ref 参数必须用 `VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)` 包装
- **基准面名称**：`start_sketch()` 会自动兼容英文版 "Front/Top/Right Plane" 与中文版 "前视/上视/右视基准面"
- **草图坐标**：基于草图平面的局部坐标系，单位为米
