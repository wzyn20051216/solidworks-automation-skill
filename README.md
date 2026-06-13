# SolidWorks Automation Skill

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.8+](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/downloads/)
[![SolidWorks](https://img.shields.io/badge/SolidWorks-2020--2025-red.svg)](https://www.solidworks.com/)

通过 Python COM 接口自动化控制 SolidWorks 的完整工具集，可被 Codex / Claude / OpenClaw（龙虾）等代理直接复用。支持零件建模、装配体、工程图、钣金、焊件、仿真等全流程自动化操作。

<p align="center">
  <img src="assets/douyin-balance.jpg" alt="抖音 @balance. 关注二维码" width="320">
  <br>
  <strong>关注抖音 @balance.</strong>
  <br>
  <sub>嵌入式开发、SolidWorks 自动化和 AI 辅助工程实践持续更新</sub>
</p>

[English](#english) | [中文](#中文)

---

## 中文

### ✨ 特性

- 🔧 **零件建模** - 草图绘制、拉伸、旋转、倒角、圆角、阵列等
- 🧵 **螺纹孔建模** - 攻丝底孔、M3/M4/M5/M6/M8 盲孔/通孔、孔口倒角、装饰螺纹与可见螺旋线兜底
- 🔩 **装配体操作** - 添加组件、配合关系、干涉检查、爆炸视图
- 📐 **工程图出图** - 三视图、剖视图、尺寸标注、BOM 表
- 💾 **文件导出** - STEP、STL、IGES、PDF、DXF/DWG、Parasolid
- 🎨 **外观材质** - 文档、特征、组件级颜色设置，支持装配体分色建模
- 🎬 **Motion Study** - 自动创建运动算例、匀速旋转马达并计算/播放动画
- 🔌 **MCP Server** - 将 SolidWorks COM 自动化封装成 Codex / Claude / Cursor 可调用的本地 MCP 工具，覆盖基础建模、装配、Mate、外观、导出、审查和旋转马达
- 🔨 **钣金设计** - 基体法兰、边线法兰、展开图导出
- ⚡ **焊件设计** - 结构构件、切割清单
- 📊 **FEA 仿真** - 静态分析、频率分析、热分析
- 📝 **自定义属性** - 读写文件属性、配置管理、设计表
- 👀 **结果自审查** - 导出多视角预览图、`review_report.json` 与 Markdown 摘要，帮助代理复核模型是否符合意图
- 🔎 **API 查证优先** - 未封装接口先查官方 API Help / 本地 SDK，再实现、运行、自审查并沉淀

### 📋 环境要求

- **操作系统**: Windows 10/11
- **SolidWorks**: 2020-2025 任意版本
- **Python**: 3.8 或更高版本
- **依赖库**: `pywin32`、`comtypes`

> 运行前可执行 `python scripts/sw_preflight.py`。如果缺少 `comtypes` / `win32com`，脚本会先询问是否授权 AI 自动配置本地环境；如果未检测到 SolidWorks，会直接停止并提示先手动安装 SolidWorks。

### 🚀 快速开始

#### 方式一：npx 一键安装（推荐）

```bash
npx github:wzyn20051216/solidworks-automation-skill
```

自动下载并安装到 Claude/Codex/OpenClaw 等已检测到的 skills 目录，并自动尝试把 SolidWorks MCP 注册到 Codex、Claude Code、Claude Desktop、Cursor、Windsurf 等本地 AI 客户端。

安装后如果客户端已经打开，建议重启对应客户端；部分客户端首次加载本地 MCP 时可能还需要在界面中确认信任。

#### 方式二：OpenClaw / 龙虾 使用

OpenClaw 兼容本 skill 的 `SKILL.md + scripts/ + references/` 目录结构。推荐把技能放在以下任一目录：

```text
~/.openclaw/skills/solidworks-automation/
~/.agents/skills/solidworks-automation/
```

安装后，可直接在 OpenClaw 中使用自然语言驱动 SolidWorks，例如：

```text
用 SolidWorks 新建一个 120x80x10 mm 的安装板，四角各打一个 phi6 孔，保存到 C:\temp\plate.sldprt，并导出 STEP 到 C:\temp\plate.step
```

OpenClaw 侧的接入约定、执行模板与排障说明见：

```text
references/openclaw.md
```

#### 方式三：Claude CLI 安装

```bash
claude skill add https://github.com/wzyn20051216/solidworks-automation-skill
```

#### 方式四：手动克隆

##### 1. 安装依赖

```bash
pip install "pywin32>=305" "comtypes>=1.2.0"
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

from sw_preflight import run_preflight
from sw_connect import connect_solidworks, mm, deg, new_document
from sw_part import start_sketch, sketch_rectangle, end_sketch, extrude_boss

run_preflight()

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
│   ├── sw_session.py    # 友好会话 API
│   ├── sw_preflight.py  # 运行前自检、依赖补齐、SolidWorks 检测
│   ├── sw_macro_guard.py # 多模型 Prompt、VBA 校验、重试与模板兜底
│   ├── sw_connect.py    # 连接与文档管理
│   ├── sw_appearance.py # 外观与材质
│   ├── sw_part.py       # 零件建模
│   ├── sw_assembly.py   # 装配体操作
│   ├── sw_motion.py     # Motion Study 与旋转马达
│   ├── sw_drawing.py    # 工程图
│   ├── sw_export.py     # 文件导出
│   └── sw_review.py     # 多视角预览与自审查报告
├── references/          # API 参考文档
│   ├── openclaw.md
│   ├── appearance.md
│   ├── review.md
│   ├── api-lookup.md
│   ├── part-modeling.md
│   ├── assembly.md
│   ├── motion-study.md
│   ├── drawing.md
│   ├── export.md
│   ├── advanced.md
│   └── troubleshooting.md
├── subskills/           # 专项子技能：多圆角/倒角 CNC、螺纹孔等
├── examples/            # 示例代码
├── mcp-server/          # 本地 stdio MCP Server
└── README.md
```

### 🔌 MCP Server

本仓库包含一个本地 `stdio` MCP Server，可让 Codex / Claude Code / Claude Desktop / Cursor / Windsurf 等 MCP 客户端通过工具调用 SolidWorks：

```powershell
pip install -r mcp-server\requirements.txt
python mcp-server\server.py
```

推荐使用多客户端注册器：

```powershell
powershell -ExecutionPolicy Bypass -File .\mcp-server\register_all_ai_mcp.ps1 -InstallDependencies
codex mcp list
claude mcp list
```

该注册器会自动尝试：

- Codex：调用 `codex mcp add`
- Claude Code：调用 `claude mcp add --scope user`
- Claude Desktop：写入 `claude_desktop_config.json`
- Cursor：写入 `~/.cursor/mcp.json`
- Windsurf：写入 `~/.codeium/windsurf/mcp_config.json`

> 通过 `npx github:wzyn20051216/solidworks-automation-skill` 安装时会自动运行注册器。若使用某些客户端的纯 skill 导入功能，客户端可能不会执行安装脚本，此时让 AI 运行上面的注册命令即可。

客户端手动配置示例：

```json
{
  "mcpServers": {
    "solidworks": {
      "command": "python",
      "args": [
        "C:\\Users\\23201\\.codex\\skills\\solidworks-automation\\mcp-server\\server.py"
      ]
    }
  }
}
```

第一阶段已暴露 `solidworks_connect`、`solidworks_open_document`、`solidworks_save_document`、`solidworks_export_active`、`solidworks_review_active`、`solidworks_add_rotary_motor` 等工具。更多说明见 [mcp-server/README.md](mcp-server/README.md)。

当前 MCP 还包含 `solidworks_health_check`、`solidworks_create_basic_part`、`solidworks_add_component`、`solidworks_add_coincident_mate`、`solidworks_add_distance_mate`、`solidworks_add_concentric_mate`、`solidworks_set_component_fixed`、`solidworks_set_appearance` 等基础工具。复杂圆角/倒角仍建议作为后续专项优化，不作为基准 demo 的成功标准。

### 🎯 使用示例

#### 推荐写法：Session API

```python
import sys
sys.path.insert(0, r"./scripts")

from sw_preflight import run_preflight
from sw_connect import mm
from sw_part import sketch, sketch_circle, extrude_boss
from sw_session import SolidWorksSession

run_preflight()
session = SolidWorksSession()
model = session.new_part()

with sketch(model, "Front Plane") as sketch_name:
    sketch_circle(model, 0, 0, mm(25))

extrude_boss(model, sketch_name, mm(50))
session.save(model, r"C:\temp\cylinder.sldprt")
session.export(model, r"C:\temp\cylinder.step")
```

#### 多模型 VBA 宏防护

当需要由 GPT / Kimi / Claude 生成 SolidWorks VBA 宏时，先使用 `sw_macro_guard.py` 统一处理格式差异：

```python
from sw_macro_guard import build_prompt, fallback_macro_for_request, validate_vba_macro

prompt = build_prompt("画一个 50mm 圆柱", model_name="claude")
macro = fallback_macro_for_request("画一个 50mm 圆柱")
result = validate_vba_macro(macro)
assert result.ok, result.issues
```

策略：

- GPT 系列沿用简洁提示词。
- Kimi / Claude / 未知模型自动使用强格式约束 Prompt，只允许输出 VBA 源码。
- 校验 `SldWorks`、`ModelDoc2`、`Sub`、`End Sub` 后再执行。
- 模型输出解析失败时自动重试 `1~2` 次；仍失败则按“立方体 / 圆柱 / 拉伸 / 草图”等关键词调用本地模板兜底。

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

#### Motion Study 旋转马达

```python
from sw_connect import mm
from sw_motion import (
    create_motion_study,
    add_constant_speed_rotary_motor_by_cylinders,
    calculate_and_play,
)

# 前提：叶轮已通过同心 Mate 装到轴上，且 lock_rotation=False。
study = create_motion_study(asm, name="叶轮_60RPM_循环转动", duration=4.0)
add_constant_speed_rotary_motor_by_cylinders(
    study,
    shaft_component=stand_comp,
    rotor_component=impeller_comp,
    shaft_radius=(mm(4.5), mm(5.5)),
    rotor_radius=(mm(10.5), mm(11.5)),
    rpm=60.0,
    name="叶轮旋转马达_60RPM",
)
calculate_and_play(study)
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

从当前版本开始，`start_sketch()` 会自动在中英文默认基准面名称之间兜底切换，更适合代理在不同语言版本的 SolidWorks 中执行。

### 🛠️ 高级功能

- **批量处理**: 批量打开、转换、导出文件
- **外观材质**: 设置文档、特征、组件级颜色；复杂颜色建议拆成多零件装配体
- **配置管理**: 创建和切换配置,修改配置参数
- **自定义属性**: 读写零件属性,支持配置特定属性
- **设计表**: 通过 Excel 驱动参数化设计
- **钣金展开**: 导出 DXF 展开图用于激光切割
- **仿真分析**: 创建 FEA 算例,运行分析,获取结果
- **CAD Agent 自审查**: 自动导出多视角预览图、生成 `review_report.json`、给出 `pass/warn/fail` 与修复建议
- **API 查证工作流**: 对尚未封装的 SolidWorks API，先查官方 API Help / 本地 SDK，再写最小验证脚本并沉淀稳定封装

详见 [references/](./references/) 目录下的完整文档。

### 🔎 Agent API 查证约定

本 skill 不把 SolidWorks 全量 API 硬塞进上下文。遇到 `scripts/` 里尚未封装的接口时，代理应先读取 [`references/api-lookup.md`](./references/api-lookup.md)，再查询 SolidWorks 官方 API Help 或本地 SDK，确认签名、枚举、返回值和版本差异；实现后必须真实运行、保存/导出文件，并用 `sw_review.py` 或桌面截图自审查结果。

### ⭐ Star History

[![Star History Chart](https://api.star-history.com/svg?repos=wzyn20051216/solidworks-automation-skill&type=Date)](https://www.star-history.com/#wzyn20051216/solidworks-automation-skill&Date)

### ❓ 常见问题

#### OpenClaw 里没有识别到这个 skill？

检查：
1. 目录是否放在 `~/.openclaw/skills/solidworks-automation/` 或 `~/.agents/skills/solidworks-automation/`
2. 目录根下是否存在 `SKILL.md`
3. 当前会话是否在安装后重新开始
4. Python / `pywin32` / `comtypes` 是否已就绪；可先运行 `python scripts/sw_preflight.py`

#### 无法连接 SolidWorks?

确保:
1. SolidWorks 已经运行
2. Python 位数与 SolidWorks 一致(通常为 64 位)
3. 已安装依赖: `pip install "pywin32>=305" "comtypes>=1.2.0"`

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
- 🎨 **Appearance and Materials** - Document, feature, and component-level color workflows
- 🔨 **Sheet Metal** - Base flange, edge flange, flat pattern export
- ⚡ **Weldments** - Structural members, cut lists
- 📊 **FEA Simulation** - Static, frequency, thermal analysis
- 📝 **Custom Properties** - Read/write file properties, configuration management
- 👀 **CAD Agent Self-Review** - Export multi-view previews, JSON reports, Markdown summaries, and `pass/warn/fail` evaluations
- 🔎 **Verified API Workflow** - Look up official API Help or local SDK docs before using unwrapped SolidWorks APIs

### 📋 Requirements

- **OS**: Windows 10/11
- **SolidWorks**: 2020-2025 (any version)
- **Python**: 3.8+
- **Dependencies**: `pywin32`, `comtypes`

### 🚀 Quick Start

#### Option 1: Install with npx

```bash
npx github:wzyn20051216/solidworks-automation-skill
```

This installs the skill into detected Claude/Codex/OpenClaw skill directories.

#### Option 2: Clone Manually

```bash
git clone https://github.com/wzyn20051216/solidworks-automation-skill.git
cd solidworks-automation-skill
pip install "pywin32>=305" "comtypes>=1.2.0"
python scripts/sw_preflight.py
```

#### Run Example

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

See [references/](./references/) for focused workflows:

- [`references/openclaw.md`](./references/openclaw.md) for OpenClaw agent usage.
- [`references/review.md`](./references/review.md) for CAD self-review.
- [`references/api-lookup.md`](./references/api-lookup.md) for verified use of unwrapped SolidWorks APIs.
- [`references/troubleshooting.md`](./references/troubleshooting.md) for common COM and modeling failures.

### 🤝 Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

### 📄 License

This project is licensed under the MIT License - see [LICENSE](LICENSE) file for details.
