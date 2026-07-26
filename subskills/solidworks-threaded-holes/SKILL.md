---
name: solidworks-threaded-holes
description: SolidWorks 螺丝孔/螺纹孔自动化子技能。用于创建或修改 M3/M4/M5/M6/M8 等内螺纹孔、攻丝底孔、盲孔/通孔、孔口倒角、装饰螺纹、可见 3D 螺旋线和螺纹参数属性；当用户要求“画螺丝孔”“有螺纹的孔”“攻牙孔”“M6x1 盲孔”“螺纹安装孔”“Hole Wizard/ThreadFeatureData/CosmeticThread”或需要导出 STEP 并审查螺纹孔模型时使用。
---

# SolidWorks Threaded Holes

## 核心判断

SolidWorks COM 创建真实 `ThreadFeatureData` 在不同版本和语言环境下很不稳定。默认交付不要押注单一 API，而是按稳定层级完成模型：

1. 先运行父技能自检：`python ../../scripts/sw_preflight.py`。
2. 建立真实几何：攻丝底孔直径、盲孔/通孔深度、孔口倒角必须正确。
3. 尝试创建真实 Thread 特征；失败时继续尝试 `InsertCosmeticThread3`。
4. 无论真实/装饰螺纹是否成功，都写入螺纹规格、自攻底孔、深度等自定义属性。
5. 对需要肉眼可见螺纹的样件，添加 3D 草图螺旋线作为审查兜底。
6. 保存 `SLDPRT`、导出 `STEP`、运行 `sw_review.run_review()`，检查预览和特征树。

## 推荐调用

优先复用父技能脚本：

```python
import sys
sys.path.insert(0, r"C:\path\to\solidworks-automation-skill\scripts")

from sw_connect import mm, get_com_member, create_empty_dispatch_variant
from sw_session import SolidWorksSession
from sw_export import export_to_step
from sw_review import run_review
from sw_part import sketch, sketch_rectangle, extrude_boss
```

需要快速生成样件时，从本子技能运行或复制：

```text
subskills/solidworks-threaded-holes/scripts/create_threaded_hole_template.py
```

详细实测经验和接口避坑见：

```text
subskills/solidworks-threaded-holes/references/threaded-hole-lessons.md
```

## 稳定流程

1. 明确规格：螺纹如 `M6x1.0`、内/外螺纹、盲孔/通孔、螺纹深度、孔位置、材料和是否需要真实可切削螺纹。
2. 选择攻丝底孔：默认粗牙内螺纹使用常规钻底孔，例如 `M3=2.5`、`M4=3.3`、`M5=4.2`、`M6=5.0`、`M8=6.8`、`M10=8.5` mm。
3. 先切底孔：用圆草图 + `FeatureCut4` 做真实孔，不要先画复杂螺旋扫掠。
4. 选择孔口圆边：枚举 `GetBodies2/GetEdges`，按圆心、半径和顶面高度找边，用 `edge.Select2()`，不要依赖 `Edge1` 或坐标点击。
5. 尝试螺纹表达：
   - 真实 Thread：`CreateDefinition(swFmSweepThread)` + `CreateFeature(thread_data)`。
   - 装饰螺纹：`InsertCosmeticThread3(8, "Tapped Hole", "M6x1.0", diameter, 0, depth, note)`。
   - 可见兜底：3D 草图短线段螺旋线，命名为 `Sketch_M6x1_Visible_Internal_Thread_Helix`。
6. 最后做孔口倒角：常用 `C0.3-C0.8`，M6 默认 `C0.6`。
7. 写自定义属性和参数 JSON，保存、导出 STEP、审查。

## 模板用法

默认生成 M6x1 内螺纹盲孔样件：

```powershell
python subskills/solidworks-threaded-holes/scripts/create_threaded_hole_template.py `
  --output-dir C:\CADAutomationWorkbench\solidworks_threaded_hole_output
```

生成 M8x1.25 螺纹孔并自定义块尺寸：

```powershell
python subskills/solidworks-threaded-holes/scripts/create_threaded_hole_template.py `
  --thread M8 `
  --block-length 60 `
  --block-width 36 `
  --block-thickness 20 `
  --thread-depth 16 `
  --output-dir C:\CADAutomationWorkbench\m8_threaded_hole_output
```

默认 `--hole-face top`，即从安装座上表面向实体内部打孔；需要侧面螺纹孔时传 `--hole-face front` 或 `--hole-face right`。

## 少走弯路

- 不要把 STEP 里的实体螺旋牙型当作默认交付；真实螺旋扫掠会显著增加重建时间和失败概率。
- 不要承诺 `ThreadFeatureData` 一定能创建成功；本机实测 `CreateFeature(ThreadFeatureData)` 返回过 `None`。
- 不要只靠 `CosmeticThread`；它可能返回非空对象，但保存后普通特征树不稳定显示。
- 不要跳过攻丝底孔和孔口倒角；这两个是真实几何和加工语义的底线。
- 不要把“看起来有线”当作工程图螺纹标注；交付时要在属性或说明中写清楚规格、深度和表达方式。
- 不要只报告保存成功；必须看 review report 和等轴测/俯视预览。

## 验证要求

每次完成后输出：

- `*.SLDPRT`
- `*.step`
- `*_parameters.json`
- `*_review_report.json`
- `*_isometric.bmp/png`

审查时至少确认：

- `evaluation.status` 为 `pass` 或可解释的 `warn`
- `expected_outputs_exist` 为 `True`
- `previews_not_blank` 为 `True`
- 特征树包含底孔切除、孔口倒角，以及 Thread/CosmeticThread/可见螺旋线中的至少一种螺纹表达
