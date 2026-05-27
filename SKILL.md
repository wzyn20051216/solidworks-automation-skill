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
from sw_connect import mm
from sw_part import sketch, sketch_circle, extrude_boss
from sw_session import SolidWorksSession

session = SolidWorksSession()
model = session.new_part()

with sketch(model, "Front Plane") as sketch_name:
    sketch_circle(model, 0, 0, mm(25))

extrude_boss(model, sketch_name, mm(50))
session.save(model, r"C:\temp\cylinder.sldprt")
session.export(model, r"C:\temp\cylinder.step")
```

> 将 `SKILL_DIR` 替换为此技能的实际安装路径。

## 核心工作流

根据用户需求选择对应模块：

| 需求 | 脚本 | 参考文档 |
|---|---|---|
| 友好会话 API | `scripts/sw_session.py` | - |
| 连接与文档管理 | `scripts/sw_connect.py` | - |
| 外观与材质 | `scripts/sw_appearance.py` | `references/appearance.md` |
| 零件建模（草图+特征） | `scripts/sw_part.py` | `references/part-modeling.md` |
| 装配体操作 | `scripts/sw_assembly.py` | `references/assembly.md` |
| 工程图出图 | `scripts/sw_drawing.py` | `references/drawing.md` |
| 文件导出 | `scripts/sw_export.py` | `references/export.md` |
| 结果自审查 | `scripts/sw_review.py` | `references/review.md` |
| 未封装 API 查证 | - | `references/api-lookup.md` |
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
5. 生成或修改模型后必须做结果自审查：导出至少一个等轴测预览图，必要时导出前/俯/右视图，并通过截图或 BMP 目视检查几何是否符合用户意图。
6. 如果需要更完整的 OpenClaw 工作流、提示词示例和排障建议，再读取 `references/openclaw.md`。

## 使用流程

1. 确认 SolidWorks 正在运行
2. 优先用 `SolidWorksSession()` 管理连接、打开、新建、保存、导出
3. 需要底层控制时再组合 `sw_connect.py`、`sw_part.py` 等函数
4. 使用 `session.export()` 或 `sw_export.py` 保存/导出文件
5. 使用 `sw_review.py` 导出预览图并自审查；如果有 GUI/桌面截图能力，打开 SolidWorks 视图截图复核

## 未封装 API 规则

当任务需要调用 `scripts/` 中尚未封装的 SolidWorks API 时：

1. 先读取 `references/api-lookup.md`，再查询 SolidWorks 官方 API 文档，或本地 SolidWorks SDK / 参考资料，确认方法签名、参数含义、枚举值、返回值和版本差异。
2. 禁止凭记忆猜接口；尤其是长参数 COM 方法、`VARIANT` / by-ref 参数、枚举值、选择标记和 `SaveAs` 类接口。
3. 写代码时保留最小可运行脚本，并对每一步返回值做 `None` / `False` 检查。
4. 实现后必须真实运行，保存或导出目标文件，并使用 `sw_review.py` 生成预览图与审查报告。
5. 新发现的坑、错误码、兼容写法或稳定封装，要补充到 `references/troubleshooting.md` 或对应模块参考文档；常用逻辑再沉淀进 `scripts/`。

## 结果自审查

每次生成、修改、导入或导出 CAD 后都要做自审查，除非用户明确说不需要：

1. 检查 COM 返回值、特征对象、保存/导出返回值和输出文件大小。
2. 调用 `model.ForceRebuild3(False)`、`model.ViewZoomtofit2()` 刷新模型。
3. 用 `scripts/sw_review.py` 的 `run_review()` 导出 `isometric/front/top/right` 预览图并写入 `*_review_report.json`。
4. 读取报告里的 `evaluation.status`、`evaluation.issues`、`checks` 和预览图；通过截图或导出的 BMP 检查：主体是否存在、比例/方位是否合理、关键部件是否缺失、是否明显重叠或悬空、文件名和输出路径是否正确。
5. 若发现问题，先修脚本并重新生成，再汇报；不要只报告“保存成功”。

示例：

```python
from sw_review import run_review

model.ForceRebuild3(False)
report, report_path = run_review(
    model,
    r"C:\temp\review",
    basename="car",
    expected_outputs=[r"C:\temp\car.sldprt", r"C:\temp\car.step"],
)
print(report_path)
print(report["evaluation"])
```

## 关键注意事项

- **单位**：API 统一使用**米**。用 `mm(50)` 转换 50mm 为 0.05m，用 `deg(90)` 转换角度
- **版本**：使用 `SldWorks.Application` 自动连接，兼容所有版本
- **选择**：特征操作前需用 `SelectByID2` 选择目标实体
- **草图**：推荐用 `with sketch(model, "Front Plane") as sketch_name:` 自动进入/退出草图并获取草图名
- **外观**：对颜色要求高的模型优先拆成多零件装配体，并用 `sw_appearance.py` 设置文档级或组件级外观
- **VARIANT**：by-ref 参数必须用 `VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)` 包装
- **基准面名称**：`start_sketch()` 会自动兼容英文版 "Front/Top/Right Plane" 与中文版 "前视/上视/右视基准面"
- **草图坐标**：基于草图平面的局部坐标系，单位为米
