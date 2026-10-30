# 近似链轮实体（pilot）

`scripts/sw_sprocket.py` 将给定链节距、滚子直径、齿数、厚度和轴孔生成**近似、折线齿廓的 SolidWorks 实体**，用于外观与几何演示。它不是标准链轮生成器：链条啮合、强度、寿命和制造标准均未验证，不能用于生产设计。草图未完全约束或参数化，修改参数应重新生成，结果保持 `review_required`。

接口要求一个没有实体的零件，先校验输入，再创建草图和拉伸；它本身不保存、重命名或覆盖文件。如果建模中途失败，零件可能保留部分草图，只应在本次新建的文档中使用。调用者负责保存新路径、导出和检查预览。

```python
from scripts.sw_session import SolidWorksSession
from scripts.sw_sprocket import SprocketSpec, create_approximate_sprocket

with SolidWorksSession(visible=True) as session:
    model = session.new_part()
    spec = SprocketSpec(chain_pitch_mm=12.7, roller_diameter_mm=7.92,
                        teeth=17, thickness_mm=6, bore_diameter_mm=10)
    feature, evidence = create_approximate_sprocket(model, spec)
    # 保存到本次新建且未占用的路径；随后导出并审查实际几何和预览。
```

轮廓的名义齿根圆 `pitch_diameter - roller_diameter` 与实际折线的最小直径不同；轴孔使用实际折线最小直径限制。`profile_min_diameter_mm` 给出该几何边界，并非啮合尺寸公差。

执行 `python tests/solidworks_sprocket_live.py` 可在新临时目录做手动回归。SW2026 SP1.1 的一个 17 齿、10 mm 轴孔示例已验证单实体、体积、包围盒、保存重开、STEP 导出与视图。自动审查仍会报告草图约束需复核；其他参数和版本尚未完成真机验证。

实现方向参考社区贡献 [PR #36](https://github.com/wzyn20051216/solidworks-automation-skill/pull/36)。
