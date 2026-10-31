# 开放端等螺距弹簧实体（pilot）

`scripts/sw_spring.py` 在新建空零件中创建完全约束的基圆、SolidWorks 原生螺旋线，以及圆形截面扫描实体。生成的是开放端、等螺距几何，端圈不并紧、不磨平；不自动选材，也不验证刚度、疲劳、压并高度或制造标准，结果始终 `review_required`。

输入 `helix_height_mm` 是**线材中心线的轴向行程**，不是弹簧实体的自由高度。实体端部沿轴线还有线径带来的延伸；实际实体尺寸使用 `IBody2.GetExtremePoint` 回读。`clockwise` 对应 SolidWorks 螺旋线特征的方向参数，相对于所选草图平面；不要在未核对方向基准时将其直接等同于图纸规定的左旋或右旋。

旧的纯几何函数 `compression_spring_helix` 为兼容保留字段名 `free_length_mm`，但该字段同样表示中心线轴向行程；其 `end_type` 只影响估算，不会生成并紧或磨平端圈。返回的 `limitations` 记录这些限制，不能把估算刚度或压并高度当作制造验收值。

```python
from pathlib import Path
import tempfile
from scripts.sw_session import SolidWorksSession
from scripts.sw_spring import OpenHelicalSpringSpec, create_open_helical_spring

output = Path(tempfile.mkdtemp(prefix="spring_demo_"))
with SolidWorksSession(version=2026, visible=True) as session:
    model = session.new_part()
    spec = OpenHelicalSpringSpec(wire_diameter_mm=3, mean_diameter_mm=24,
                                 helix_height_mm=48, turns=6, clockwise=False)
    feature, evidence = create_open_helical_spring(model, spec)
    if not session.save(model, str(output / "open_spring.sldprt")):
        raise RuntimeError("保存失败")
    # 按具体任务导出 STEP、生成预览并人工审查。
```

试点约束：线径 0.1–50 mm、中径不超过 500 mm 且至少为线径四倍、中心线高度不超过 2000 mm、圈数 1–20；螺距至少为线径 1.25 倍，且不超过中径一半。它们是当前实现的保守边界，不是弹簧设计标准。接口只接受没有实体的零件；失败后可能留下草图或中间特征，只应在本次新建的文档使用。

执行 `python tests/solidworks_spring_live.py` 会在新临时目录分别验证 6 圈和反方向 5.5 圈的示例：回读旋向、圈数、螺距及高度，对照理论体积和 B-Rep 极值，保存、导出 STEP、重开并检查预览。仅 SW2026 SP1.1 完成这两例真机验证，其他尺寸组合和版本需继续验证。

相关接口：[SolidWorks 螺旋线定义](https://help.solidworks.com/2021/english/api/sldworksapi/solidworks.interop.sldworks~solidworks.interop.sldworks.imodeldoc2~inserthelix.html)、[实体极值点](https://help.solidworks.com/2014/English/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IBody2~GetExtremePoint.html)。实现方向参考社区贡献 [PR #36](https://github.com/wzyn20051216/solidworks-automation-skill/pull/36)。
