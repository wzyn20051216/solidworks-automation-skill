# 高级功能参考

## 目录

- [自定义属性](#自定义属性)
- [设计表与配置](#设计表与配置)
- [钣金设计](#钣金设计)
- [焊件设计](#焊件设计)
- [曲面建模](#曲面建模)
- [仿真/FEA](#仿真fea)

---

## 自定义属性

```python
# 获取属性管理器
# 空字符串 = 文件级属性，配置名 = 配置特定属性
props = model.Extension.CustomPropertyManager("")

# 读取属性
val = ""
resolved = ""
was_resolved = False
is_linked = False
result = props.Get6("Description", False, val, resolved, was_resolved, is_linked)
# resolved 包含解析后的值

# 写入/更新属性
# 类型: 30=文本, 2=数字, 11=Yes/No, 64=日期
props.Add3("Description", 30, "主轴零件 Rev A", 1)  # 1=覆盖
props.Add3("Material", 30, "Steel 1045", 1)
props.Add3("Weight", 2, "2.5", 1)
props.Add3("PartNumber", 30, "PN-001-001", 1)

# 删除属性
props.Delete2("OldProperty")

# 获取所有属性名称
count = props.Count
names = props.GetNames()
```

## 设计表与配置

### 配置管理

```python
from sw_document_data import (
    activate_configuration,
    create_configuration,
    inspect_configurations,
    update_dimension_mm,
)

# 使用官方 AddConfiguration3 创建并激活；默认同名配置幂等复用。
created = create_configuration(
    model,
    "加工",
    comment="CNC 工况",
    alternate_name="MACHINED",
)

# 使用官方 ShowConfiguration2，并以活动配置名回读而非单独 COM 返回值判定。
activated = activate_configuration(model, "加工")

# 用显式 VT_ARRAY|VT_BSTR 写入指定配置，API 内部单位自动换算为米。
dimension = update_dimension_mm(
    model,
    "D1@Boss-Extrude1",
    50.0,
    configuration_mode="specific",
    configuration_names=["加工"],
)

evidence = inspect_configurations(model)
```

SW2026 真机已验证配置创建、切换、配置级尺寸/属性以及保存重开回读。`AddConfiguration3`
会自动激活新配置，因此重复调用 `ShowConfiguration2` 可能返回 `False`；执行器会记录原始
返回值，但以 `ConfigurationManager.ActiveConfiguration.Name` 回读和重建结果作为成功证据。
设计表、派生配置、显示状态和大规模抑制矩阵仍是 `pilot` 范围外能力。

### 设计表

```python
# 插入设计表（从 Excel）
design_table = model.InsertFamilyTableOpen(excelFilePath)

# 编辑完成后关闭
model.CloseFamilyTable()

# 更新设计表
model.InsertFamilyTableEdit()
```

## 钣金设计

### 基本操作

```python
from sw_sheet_metal import BaseFlangeSpec, create_base_flange

# 先创建并退出开放或闭合草图，再使用现代 FeatureData API。
feature = create_base_flange(
    model,
    sketch_name,
    BaseFlangeSpec(
        thickness=0.002,
        bend_radius=0.0025,
        depth=0.100,
        k_factor=0.42,
    ),
)
```

该封装使用 `CreateDefinition(swFmBaseFlange)`、`IBaseFlangeFeatureData.Initialize`
和 `CreateFeature`，不会猜测已废弃长参数接口。SW2026 SP01.1 已验证开放 U 型轮廓、
两道真实折弯及保存重开；边线法兰、斜接法兰和放样折弯仍按 `pilot` 门禁处理。

### 展开图导出

```python
from sw_export import export_flat_pattern_dxf

# 零件必须先保存；选项位掩码默认为“展开几何(1) + 折弯线(4)”。
export_flat_pattern_dxf(model, dxfPath, include_bend_lines=True)
```

`ExportToDWG2` 的第五个参数是 12 个双精度数值组成的对齐数组，第八个参数才是
钣金选项位掩码；不要把多个布尔值误当作“轮廓/折弯线/草图/隐藏边线”。

### 钣金参数

```python
# 获取钣金特征数据
feat = model.FeatureByName("Sheet-Metal1")
sheet_metal_data = feat.GetDefinition()
thickness = sheet_metal_data.Thickness    # 板厚
bend_radius = sheet_metal_data.BendRadius # 折弯半径
```

## 焊件设计

### 切割清单

```python
def get_cut_list(model):
    """遍历焊件切割清单"""
    feat = model.FirstFeature()
    items = []
    while feat:
        if feat.GetTypeName2() == "CutListFolder":
            props = feat.CustomPropertyManager
            # 读取属性
            qty_val = ""
            qty_resolved = ""
            props.Get6("QUANTITY", False, qty_val, qty_resolved, False, False)

            desc_val = ""
            desc_resolved = ""
            props.Get6("DESCRIPTION", False, desc_val, desc_resolved, False, False)

            items.append({
                "name": feat.Name,
                "quantity": qty_resolved,
                "description": desc_resolved
            })
        feat = feat.GetNextFeature()
    return items
```

### 结构构件

```python
# 插入结构构件（焊件型材）
feature_mgr.InsertStructuralWeldment5(
    ProfilePath,   # str: 型材文件路径（.sldlfp）
    ...
)
```

## 曲面建模

```python
# 拉伸曲面
feature_mgr.InsertExtrudedSurface(depth, flip, dir, t1, t2, d1, d2)

# 旋转曲面
feature_mgr.InsertRevolvedRefSurface(...)

# 放样曲面
feature_mgr.InsertLoftRefSurface2(...)

# 扫描曲面
feature_mgr.InsertSweepRefSurface(...)

# 平面区域
feature_mgr.InsertPlanarRefSurface()

# 修剪曲面
feature_mgr.InsertTrimSurface2(...)

# 缝合曲面
feature_mgr.InsertSewRefSurface(True, False, 0.001)

# 曲面加厚为实体
feature_mgr.InsertThickenSheet(thickness, False, True)
```

## 仿真/FEA

> 需要安装 SolidWorks Simulation 插件

```python
# 获取 Simulation 插件
cos_works = sw.GetAddInObject("SldWorks.Simulation")
if not cos_works:
    print("Simulation 插件未安装或未激活")

study_mgr = cos_works.StudyManager

# 创建静态分析算例
study = study_mgr.CreateStudy(
    model,
    "StaticStudy1",
    0  # 0=Static, 1=Frequency, 2=Buckling, 3=Thermal, 5=Fatigue
)

# 添加材料（通过 SolidBody）
# 添加约束（Fixed, Roller/Slider, Prescribed）
# 添加载荷（Force, Pressure, Gravity, Torque）

# 运行分析
study.RunAnalysis()

# 获取结果
results = study.Results
# 应力、位移、安全系数等
```

### 算例类型

| 值 | 类型 | 说明 |
|---|---|---|
| 0 | Static | 静态分析 |
| 1 | Frequency | 频率分析 |
| 2 | Buckling | 屈曲分析 |
| 3 | Thermal | 热分析 |
| 4 | Drop Test | 跌落测试 |
| 5 | Fatigue | 疲劳分析 |
| 6 | Nonlinear | 非线性分析 |
