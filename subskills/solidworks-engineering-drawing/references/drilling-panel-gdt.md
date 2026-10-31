# 钻孔面板分析（pilot）

`drilling_panel_gdt.py` 识别面板孔位阵列、计算候选坐标表，并提出基准方案。结果是设计人员复核用的**候选方案**，不会自动交付工程图。它参考了社区贡献 [PR #36](https://github.com/wzyn20051216/solidworks-automation-skill/pull/36)。

默认不猜测孔的用途，也不生成位置度、平面度或材料条件。需要 GD&T 候选时，须由工程师显式提供 `--gdt-profile` JSON，包含 `positionToleranceMm`、`dowelPositionToleranceMm`、`flatnessMm`、`materialCondition` 和 `datumRefs`。计算结果仍须复核，不能代替设计输入或标准符合性判定。

历史函数 `default_gdt_profile()` 只返回带 `_exampleOnly` 标记的示例；它不能直接用于候选生成，实际公差必须由设计输入提供。

从中性文档分析（需真实模型路径和 `metadata.plate` 的宽、高、厚）：

```powershell
python subskills/solidworks-engineering-drawing/scripts/drilling_panel_gdt.py panel.cadstudio.json --source-model C:\work\panel.SLDPRT --analysis-out panel_analysis.json --spec-out panel_spec.json
```

从已保存的 SolidWorks 零件读取：

```powershell
python subskills/solidworks-engineering-drawing/scripts/drilling_panel_gdt.py --from-model C:\work\panel.SLDPRT --analysis-out panel_analysis.json --spec-out panel_spec.json
```

输出文件采用独占创建，不覆盖已有文件。真实模型路径来自打开的文档；使用受控会话，已有用户文档不会作为本次打开的文档关闭。没有保存的模型、缺失包围盒或 B-Rep 读取出错时阻断出图规格生成。

面板法向按包围盒最薄方向推测；该方法仅适合坐标轴对齐的简单面板。`GetPartBox` 返回的是[近似包围盒](https://help.solidworks.com/2013/English/Api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IPartDoc~GetPartBox.html)，不能当作精确板边或加工尺寸；输出会保留提示。缺少有效边界时不再按孔位外扩或虚构板厚。中性文档未指定板原点时会明确提示按 `(0, 0)` 假定，必须由设计人员确认。

孔壁必须有有效轴向，同轴分段按 0.01 mm 容差合并；几何本身不能证明通孔、螺纹、沉孔用途或定位销。包围盒、基准面、孔型、孔边距和材料条件均须结合真实模型及设计意图复核。斜置面板、多实体、阶梯孔和复杂几何需要单独验证。

SolidWorks 2026 SP1.1 已用一个 80×60×20 mm 四孔板验证保存、重开、四孔轴线和孔径回读。它只证明该样例的分析路径可用，**未验证不同版本或实际 GD&T/孔表落图**。候选 `drawing_spec` 不等于已生成或可制造的工程图。
