# SolidWorks Automation Skill

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.8+](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/downloads/)
[![SolidWorks](https://img.shields.io/badge/SolidWorks-2020--2025-red.svg)](https://www.solidworks.com/)

通过 Python COM 接口自动化控制 SolidWorks 的完整工具集。支持零件建模、装配体、工程图、钣金、焊件、仿真等全流程自动化操作。

[English](#english) | [中文](#中文)

---

## 中文

### ✨ 特性

- 🔧 **零件建模** - 草图绘制、拉伸、旋转、倒角、圆角、阵列等
- 🔩 **装配体操作** - 添加组件、配合关系、干涉检查、爆炸视图
- 📐 **工程图出图** - 三视图、剖视图、尺寸标注、BOM 表
- 💾 **文件导出** - STEP、STL、IGES、PDF、DXF/DWG、Parasolid
- 🔨 **钣金设计** - 基体法兰、边线法兰、展开图导出
- ⚡ **焊件设计** - 结构构件、切割清单
- 📊 **FEA 仿真** - 静态分析、频率分析、热分析
- 📝 **自定义属性** - 读写文件属性、配置管理、设计表

### 📋 环境要求

- **操作系统**: Windows 10/11
- **SolidWorks**: 2020-2025 任意版本
- **Python**: 3.8 或更高版本
- **依赖库**: `pywin32`

### 🚀 快速开始

#### 方式一：npx 一键安装（推荐）

```bash
npx github:wzyn20051216/solidworks-automation-skill
```

自动下载并安装到 Claude/Codex 的 skills 目录，无需手动配置。

#### 方式二：Claude CLI 安装

```bash
claude skill add https://github.com/wzyn20051216/solidworks-automation-skill
```

#### 方式三：手动克隆

##### 1. 安装依赖

```bash
pip install pywin32
```

##### 2. 克隆仓库

```bash
git clone https://github.com/wzyn20051216/solidworks-automation-skill.git
cd solidworks-automation-skill
```

##### 3. 运行示例

确保 SolidWorks 已经运行,然后执行:

```python
import sys
sys.path.insert(0, r"./scripts")

from sw_connect import connect_solidworks, mm, deg, new_document
from sw_part import start_sketch, sketch_rectangle, end_sketch, extrude_boss

# 连接 SolidWorks
sw, model = connect_solidworks()

# 创建新零件
model = new_document(sw, "part")

# 在前视基准面上绘制矩形
start_sketch(model, "Front Plane")
sketch_rectangle(model, 0, 0, mm(50), mm(30))
end_sketch(model)

# 拉伸 10mm
extrude_boss(model, "Sketch1", mm(10))

print("零件创建完成!")
```

### 📚 文档结构

```
solidworks-automation-skill/
├── scripts/              # Python 脚本模块
│   ├── sw_connect.py    # 连接与文档管理
│   ├── sw_part.py       # 零件建模
│   ├── sw_assembly.py   # 装配体操作
│   ├── sw_drawing.py    # 工程图
│   └── sw_export.py     # 文件导出
├── references/          # API 参考文档
│   ├── part-modeling.md
│   ├── assembly.md
│   ├── drawing.md
│   ├── export.md
│   ├── advanced.md
│   └── troubleshooting.md
├── examples/            # 示例代码
└── README.md
```

### 🎯 使用示例

#### 创建零件

```python
from sw_connect import connect_solidworks, mm, new_document
from sw_part import *

sw, _ = connect_solidworks()
model = new_document(sw, "part")

# 绘制草图
start_sketch(model, "Front Plane")
sketch_circle(model, 0, 0, mm(25))
end_sketch(model)

# 拉伸
extrude_boss(model, "Sketch1", mm(50))
```

#### 装配体操作

```python
from sw_connect import connect_solidworks, new_document
from sw_assembly import add_component, add_mate_coincident

sw, _ = connect_solidworks()
asm = new_document(sw, "assembly")

# 添加零件
comp1 = add_component(asm, r"C:\parts\part1.sldprt", 0, 0, 0)
comp2 = add_component(asm, r"C:\parts\part2.sldprt", 0.1, 0, 0)

# 添加配合
add_mate_coincident(asm, "Face1@part1", "FACE", "Face1@part2", "FACE")
```

#### 导出文件

```python
from sw_connect import connect_solidworks, open_document
from sw_export import export_to_step, export_to_stl

sw, _ = connect_solidworks()
model = open_document(sw, r"C:\parts\mypart.sldprt")

# 导出 STEP
export_to_step(model, r"C:\output\mypart.step")

# 导出 STL
export_to_stl(model, r"C:\output\mypart.stl", quality="fine")
```

### 🔑 核心概念

#### 单位转换

SolidWorks API 使用**米**作为基本单位,使用辅助函数进行转换:

```python
from sw_connect import mm, deg

length = mm(50)      # 50mm → 0.05m
angle = deg(90)      # 90° → 1.5708 弧度
```

#### 实体选择

操作特征前需要先选择实体:

```python
model.Extension.SelectByID2(
    "Front Plane",  # 实体名称
    "PLANE",        # 实体类型
    0, 0, 0,        # 坐标
    False,          # 追加选择
    0,              # 标记
    None,           # 标注
    0               # 选择标记
)
```

#### 基准面名称

| 英文版 | 中文版 | 法线方向 |
|--------|--------|----------|
| Front Plane | 前视基准面 | Z 轴 |
| Top Plane | 上视基准面 | Y 轴 |
| Right Plane | 右视基准面 | X 轴 |

### 🛠️ 高级功能

- **批量处理**: 批量打开、转换、导出文件
- **配置管理**: 创建和切换配置,修改配置参数
- **自定义属性**: 读写零件属性,支持配置特定属性
- **设计表**: 通过 Excel 驱动参数化设计
- **钣金展开**: 导出 DXF 展开图用于激光切割
- **仿真分析**: 创建 FEA 算例,运行分析,获取结果

详见 [references/](./references/) 目录下的完整文档。

### ❓ 常见问题

#### 无法连接 SolidWorks?

确保:
1. SolidWorks 已经运行
2. Python 位数与 SolidWorks 一致(通常为 64 位)
3. 已安装 `pywin32`: `pip install pywin32`

#### 特征创建失败?

检查:
1. 草图是否闭合
2. 单位是否正确(使用 `mm()` 转换)
3. 实体是否正确选择
4. 查看 [troubleshooting.md](./references/troubleshooting.md)

### 🤝 贡献

欢迎提交 Issue 和 Pull Request!

1. Fork 本仓库
2. 创建特性分支 (`git checkout -b feature/AmazingFeature`)
3. 提交更改 (`git commit -m '添加某个功能'`)
4. 推送到分支 (`git push origin feature/AmazingFeature`)
5. 开启 Pull Request

### 📄 许可证

本项目采用 MIT 许可证 - 详见 [LICENSE](LICENSE) 文件

### 🙏 致谢

- SolidWorks API 文档
- pywin32 项目
- 所有贡献者

---

## English

### ✨ Features

- 🔧 **Part Modeling** - Sketching, extrusion, revolution, chamfer, fillet, patterns
- 🔩 **Assembly Operations** - Add components, mates, interference detection, exploded views
- 📐 **Drawing Creation** - Standard views, section views, dimensions, BOM tables
- 💾 **File Export** - STEP, STL, IGES, PDF, DXF/DWG, Parasolid
- 🔨 **Sheet Metal** - Base flange, edge flange, flat pattern export
- ⚡ **Weldments** - Structural members, cut lists
- 📊 **FEA Simulation** - Static, frequency, thermal analysis
- 📝 **Custom Properties** - Read/write file properties, configuration management

### 📋 Requirements

- **OS**: Windows 10/11
- **SolidWorks**: 2020-2025 (any version)
- **Python**: 3.8+
- **Dependencies**: `pywin32`

### 🚀 Quick Start

#### 1. Install Dependencies

```bash
pip install pywin32
```

#### 2. Clone Repository

```bash
git clone https://github.com/yourusername/solidworks-automation-skill.git
cd solidworks-automation-skill
```

#### 3. Run Example

Make sure SolidWorks is running, then:

```python
import sys
sys.path.insert(0, r"./scripts")

from sw_connect import connect_solidworks, mm, new_document
from sw_part import start_sketch, sketch_rectangle, end_sketch, extrude_boss

# Connect to SolidWorks
sw, model = connect_solidworks()

# Create new part
model = new_document(sw, "part")

# Draw rectangle on Front Plane
start_sketch(model, "Front Plane")
sketch_rectangle(model, 0, 0, mm(50), mm(30))
end_sketch(model)

# Extrude 10mm
extrude_boss(model, "Sketch1", mm(10))

print("Part created!")
```

### 📚 Documentation

See [references/](./references/) directory for complete API documentation.

### 🤝 Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

### 📄 License

This project is licensed under the MIT License - see [LICENSE](LICENSE) file for details.
