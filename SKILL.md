---
name: solidworks-automation
description: |
  SolidWorks CAD 自动化技能，通过 Python COM 接口直接控制 Windows 上运行的 SolidWorks 实例。
  覆盖完整工程工作流：零件建模、装配体、工程图、钣金、焊件、仿真、文件导出、自定义属性、设计表与配置管理。
  兼容 SolidWorks 2020-2025 各版本。
  触发场景：用户提到 SolidWorks、3D 建模、CAD 自动化、零件设计、装配体、工程图、钣金设计、
  焊件设计、STEP/STL/PDF 导出、BOM 表、设计表、FEA 仿真等相关需求时使用。
  触发关键词：SolidWorks、SW、3D建模、CAD、零件、装配、工程图、钣金、焊件、导出STEP、导出STL。
---

# SolidWorks 自动化技能

## 快速开始

### 环境要求

- Windows 系统 + SolidWorks 已安装并运行
- Python 3.8+ + `pywin32`（`pip install pywin32`）

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
| 钣金/焊件/仿真/属性 | - | `references/advanced.md` |
| 常见错误排查 | - | `references/troubleshooting.md` |

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
- **基准面名称**：英文版 "Front/Top/Right Plane"，中文版 "前视/上视/右视基准面"
- **草图坐标**：基于草图平面的局部坐标系，单位为米
