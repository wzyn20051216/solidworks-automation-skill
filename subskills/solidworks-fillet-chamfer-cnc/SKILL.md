---
name: solidworks-fillet-chamfer-cnc
description: SolidWorks 多圆角/倒角 CNC 零件自动化子技能。用于创建或修改圆角、倒角很多的机加工件、铝合金安装座、连接块、外壳、支架、沉孔安装板等模型；当任务涉及 FeatureFillet、InsertFeatureChamfer、稳定选边、孔口倒角、圆角矩形外轮廓、CNC 减重口袋、STEP 导出和预览审查时使用。
---

# SolidWorks Fillet Chamfer CNC

## 核心判断

圆角/倒角多的 SolidWorks 自动化模型，难点不是 API 参数，而是稳定拓扑、稳定选边和特征顺序。默认策略是：

1. 先运行父技能自检：`python ../../scripts/sw_preflight.py`。
2. 先做简单可靠的基础体：矩形/圆柱/凸台/孔槽，避免一开始就画复杂圆角草图。
3. 大圆角、外轮廓倒角尽量放在孔槽切除之前。
4. 孔、沉孔、定位孔、长槽、减重口袋放在主体边处理之后。
5. 孔口小倒角放最后；容易重算卡住的小圆角可降级或跳过，并在参数报告里写明。
6. 生成后必须保存、导出 STEP、运行 `sw_review.run_review()`，并查看等轴测预览。

## 推荐调用

优先复用父技能脚本：

```python
import sys
sys.path.insert(0, r"C:\path\to\solidworks-automation-skill\scripts")

from sw_connect import mm, get_com_member, create_empty_dispatch_variant
from sw_session import SolidWorksSession
from sw_export import export_to_step
from sw_review import run_review
from sw_appearance import set_document_appearance
```

需要模板时，从本子技能复制或参考：

```text
subskills/solidworks-fillet-chamfer-cnc/scripts/create_cnc_mount_template.py
```

详细经验和避坑规则见：

```text
subskills/solidworks-fillet-chamfer-cnc/references/cnc-fillet-chamfer-lessons.md
```

## 稳定流程

1. 关闭同名旧文档，避免 `SaveAs` 错误码 `1`。
2. 新建零件，创建底板、凸台和必要参考面。
3. 枚举实体边线，用对象 `edge.Select2(append, 0)` 选择，不依赖 `Edge1` 名称或随机坐标点击。
4. 先加外轮廓真实特征：
   - 立角大圆角：`FeatureFillet(195, radius, ...)`
   - 顶/底外边倒角：`InsertFeatureChamfer(4, 1, distance, pi/4, ...)`
5. 再切孔槽：
   - 贯穿安装孔
   - 沉孔台阶
   - 定位孔
   - 中心长圆槽
   - 减重口袋
6. 最后只做轻量孔口倒角；复杂槽口/口袋底部小圆角先保守处理。
7. 写参数 JSON，保存 SLDPRT，导出 STEP，运行审查。

## 少走弯路

- 不要把“圆角很多”理解为一开始画复杂圆角草图；草图闭合失败会导致拉伸返回 `None`。
- 不要用 `SelectByID2("", "EDGE", x, y, z, ...)` 作为主方案；不同视图和拓扑下容易选错边。
- 不要把全部孔槽切完再一次性大圆角；复杂拓扑会让 SolidWorks 求解非常慢甚至卡住。
- 不要把外观成功当作几何成功；外观 API 可能让预览偏透明或颜色异常，几何仍需看审查预览。
- 不要只报告保存成功；必须确认 `SLDPRT`、`STEP`、预览图和 review report 都存在且非空。

## 验证要求

每次完成后输出：

- `*.SLDPRT`
- `*.step`
- `*_parameters.json`
- `*_review_report.json`
- `*_isometric.bmp` 或转换后的 PNG

审查时至少检查：

- `evaluation.status` 是否为 `pass` 或可解释的 `warn`
- `expected_outputs_exist` 是否为 `True`
- `previews_not_blank` 是否为 `True`
- 特征树是否包含预期的 `Fillet` / `Chamfer` / `Cut` 特征
