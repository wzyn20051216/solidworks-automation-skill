# 非标钻孔台面板：孔位规整 + 基准推测 + GD&T 自动出图

`scripts/drilling_panel_gdt.py` 面向「一块布满孔的非标自动化台面板从 3D 自动出图到 SLDDRW」这一
极端案例，把最难自动化、最有价值的**分析推理**做成纯函数、可离线单测，输出一份通过本子技能
schema 的 `drawing_spec`，再交给现有渲染器落图。

## 三件事

1. **孔位规整（detect_hole_patterns）**：按（孔径, 孔型）分组，一维聚类识别栅格/线性/离散阵列，
   给出行列数、节距、原点与规整度（`regular`/`complete`）。不同孔型（tapped/clearance/dowel）即使
   同名义直径也分开成组，避免把定位销并进螺纹孔栅格。
2. **基准自动推测（infer_datums）**：按 3-2-1 原则，从包围盒取基准角（默认左下角），沿长边定 B、
   短边定 C，A 为面板主平面；识别到恰好 2 个 dowel/小孔时列为基准孔候选，可改用基准孔目标。
3. **GD&T 自动给出（generate_gdt）**：为每组孔阵列生成 GB/T 1182 / ISO GPS 位置度框
   `⌖ ⌀t Ⓜ | A | B | C`（间隙孔默认最大实体 MMC），定位销孔位置度从严且 RFS；基准 A 加平面度
   `⏥ t`（区域公差，不带 ⌀）。

配套 `build_hole_table`（孔表：标签/规格/数量/阵列描述/相对基准原点）与
`build_ordinate_dimensions`（从基准原点的 X/Y 坐标基线）。

## 用法

```bash
python subskills/solidworks-engineering-drawing/scripts/drilling_panel_gdt.py \
  panel.cadstudio.json --source-model panel.SLDPRT \
  --analysis-out out/panel_analysis.json --spec-out out/panel_spec.json
```

输入是 NeutralCadDocument：`features[type=hole].parameters` 提供 `x`、`y`、`diameter`（或 `radius`）、
`holeKind`（tapped/clearance/dowel）；`metadata.plate` 提供 `widthMm`/`heightMm`/`thicknessMm`。
输出 `analysis`（阵列/基准/GD&T/孔表/坐标）与 `drawing_spec`（含 professionalAnnotations 的
datums、geometricTolerances、holeCallouts、centerMarks，holeRequirements 精确孔位，requiredDimensions
坐标基线与 GD&T）。

## 打通真机 3D → 分析（pilot）

除了中性文档，还可直接从活动 SolidWorks 零件抽取孔位快照，打通「3D → 孔位规整 → 基准 → GD&T →
drawing_spec」这一段：

```python
from drilling_panel_gdt import analyze_model
result = analyze_model(model)          # model 为 IModelDoc2/IPartDoc
result["snapshot"]["holes"]            # 抽取到的孔（去重后的功能孔径）
result["analysis"], result["drawingSpec"]
```

CLI：

```bash
python subskills/solidworks-engineering-drawing/scripts/drilling_panel_gdt.py \
  --from-model C:\path\panel.SLDPRT --spec-out out/panel_spec.json
```

抽取机制复用根技能已验证的 `sw_review.collect_geometry_measurements`（`GetPartBox(True)` 包围盒 +
B-Rep 内部圆柱孔壁，`FaceInSurfaceSense=True` 已滤除外圆柱、凸台与圆角），再走纯函数适配层
`holes_from_geometry_measurements`：

- **面板法向**取包围盒最薄方向；只保留轴向与法向平行的圆柱（滤掉侧壁/斜孔）。
- **平面内坐标**由投影掉法向轴得到 `(x, y)`。
- **沉孔/阶梯孔**同位置的多段孔壁合并为一孔，取**最小直径**为功能孔径。
- **板尺寸/基准原点**优先用 `GetPartBox` 角点，缺失时按孔范围外扩估算（会给 warning）。

适配层是纯函数、离线单测（含法向 z/y、侧壁过滤、沉孔合并、板尺寸回退等用例）；`collect_geometry_measurements`
与 `analyze_model` 的 COM 读取为 pilot，须真机验证。孔型（tapped/clearance/dowel）无法从纯几何判定，
默认 clearance；定位销识别交给下游 `infer_datums`，需要精确孔型时用中性文档路径显式提供 `holeKind`。

## 与渲染器的分工

- 分析/规划为纯函数，离线单测（`tests/test_drilling_panel_gdt.py`），并且生成的 `drawing_spec`
  已用本子技能 `validate_drawing_spec` 通过 schema 校验。
- 真正把基准标签、位置度框、孔表和坐标标注**落到 SLDDRW** 仍由本子技能的专项 COM 脚本执行
  （`InsertDatumTag2`、GTOL、孔标注等），为 `pilot`，须真机与工程复核；生成器不得声称已自动交付图纸。

## 边界与约定

- 单位统一 mm；坐标系为面板正面 XY，基准原点默认包围盒左下角。
- 聚类容差 `cluster_tol_mm` 默认 0.5，节距均匀容差 0.2；面板孔位偏差大或存在斜置阵列时需调参并复核。
- 斜向阵列、极坐标阵列、沉头/阶梯孔的多段标注暂按离散簇处理，交由人工补充。
- 位置度/平面度默认值来自 `default_gdt_profile()`，可用 profile 覆盖；最终公差必须按图纸功能与
  配合要求由工程师确认，本工具只做首版自动建议。
