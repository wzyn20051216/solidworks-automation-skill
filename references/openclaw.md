# OpenClaw 控制 SolidWorks

本说明面向会调用本 skill 的代理实例，目标是在 OpenClaw 中稳定复用现有 `scripts/` 封装，而不是每次重新手写 COM 自动化代码。

## 运行前检查

1. 操作系统必须是 Windows。
2. SolidWorks 已安装，并且最好先手动打开一次确认 COM 可用。
3. `python` 或 `py` 在 PATH 中可执行。
4. 已安装 `pywin32`：

```bash
pip install pywin32
```

5. 本 skill 位于以下任一目录：

```text
~/.openclaw/skills/solidworks-automation/
~/.agents/skills/solidworks-automation/
```

## 推荐执行流程

1. 先补齐约束信息：SolidWorks 版本、界面语言、中间文件路径、最终输出路径、尺寸单位、目标格式。
2. 优先调用 `scripts/sw_connect.py`、`scripts/sw_part.py`、`scripts/sw_assembly.py`、`scripts/sw_drawing.py`、`scripts/sw_export.py`。
3. 把任务拆成小步骤：连接、打开/新建、建模/装配、保存、导出、截图/预览自审查。
4. 每一步都检查返回值，不要假设 COM 调用一定成功。
5. 导出或保存后，再检查目标文件是否实际存在。
6. 生成或修改模型后，导出至少一张等轴测预览图；如果有桌面截图能力，再截图当前 SolidWorks 窗口复核。

## 最小导入模板

在 OpenClaw 中执行 Python 时，优先使用 `{baseDir}` 引用 skill 根目录：

```python
import sys
sys.path.insert(0, r"{baseDir}/scripts")

from sw_connect import connect_solidworks, mm, deg, new_document, open_document, save_document
from sw_part import start_sketch, end_sketch, sketch_rectangle, sketch_circle, extrude_boss, extrude_cut
from sw_export import export_to_step, export_to_stl, export_to_pdf
from sw_review import collect_model_summary, save_review_previews
```

## 推荐提示词

适合直接在 OpenClaw 中触发本 skill 的用户表达：

- “用 SolidWorks 画一个 120x80x10 mm 的安装板，四角各打一个 phi6 孔，保存到 `C:\\temp\\plate.sldprt` 并导出 STEP。”
- “打开 `C:\\parts\\gearbox.sldasm`，检查干涉并把结果告诉我。”
- “把 `C:\\parts\\bracket.sldprt` 导出为 STL 和 STEP，输出到 `C:\\output\\`。”

## 执行注意事项

- `SolidWorks API` 的长度单位是米，所有毫米输入都先用 `mm()` 转换。
- `start_sketch()` 已经内置中英文基准面名称兜底，优先直接传 `"Front Plane"`、`"Top Plane"`、`"Right Plane"` 或它们的中文名。
- 需要操作特征、面、边前，先明确实体名称和类型，再执行 `SelectByID2`。
- 大任务优先保存为 `.sldprt` / `.sldasm` / `.slddrw`，导出格式作为最后一步。

## 自检清单

执行完成后至少检查：

1. `connect_solidworks()` 是否返回有效的 `sw` 对象。
2. 新建或打开文档后，`model` 是否不为 `None`。
3. 特征函数（如 `extrude_boss()`）是否返回特征对象。
4. `save_document()` / 导出函数是否返回成功。
5. 目标文件是否在磁盘上真实存在。
6. `save_review_previews()` 是否成功导出预览图。
7. 预览图中模型是否符合任务描述，是否存在空白、比例错误、部件缺失、方向错误、重叠或悬空。

## 自审查示例

```python
model.ForceRebuild3(False)
previews = save_review_previews(model, r"C:\temp\review", basename="result")
summary = collect_model_summary(model)
print(previews)
print(summary["feature_count"])
```

如果预览图不对，先修改脚本并重新生成，不要只报告“文件保存成功”。
