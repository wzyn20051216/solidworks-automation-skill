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
# 获取所有配置名称
config_names = model.GetConfigurationNames()

# 激活配置
model.ShowConfiguration2(configName)

# 获取配置对象
config = model.GetConfigurationByName(configName)

# 添加新配置
config_mgr = model.ConfigurationManager
new_config = config_mgr.AddConfiguration2(
    "NewConfig",    # 名称
    "描述",          # 描述
    "",             # 替代名称
    0,              # 选项
    "",             # 父配置
    "",             # 描述2
    True            # 使用所有参数
)

# 修改配置中的尺寸
model.ShowConfiguration2("Config1")
dim = model.Parameter("D1@Boss-Extrude1")
dim.SystemValue = 0.05  # 50mm（单位: 米）
model.EditRebuild3()
```

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
# 钣金相关特征通过 FeatureManager 创建
# 1. 基体法兰
feature_mgr.InsertSheetMetalBaseFlange2(
    Thickness,    # float: 板厚（米）
    BendRadius,   # float: 折弯半径（米）
    ...
)

# 2. 边线法兰
feature_mgr.InsertSheetMetalEdgeFlange2(...)

# 3. 斜接法兰
feature_mgr.InsertSheetMetalMiterFlange(...)

# 4. 展开
feature_mgr.InsertSheetMetalFlatPattern2()

# 5. 折叠
feature_mgr.InsertSheetMetalFold()
```

### 展开图导出

```python
# 导出展开图为 DXF
model.ExportToDWG2(
    dxfPath,           # str: 输出路径
    modelPath,         # str: 模型路径（或空字符串）
    1,                 # int: 导出类型（1=展开图）
    True,              # bool: 显示外轮廓
    True,              # bool: 包含弯曲线
    False,             # bool: 草图实体
    False,             # bool: 隐藏边线
    0,                 # int: 弯曲注释
    None               # variant: 导出数据
)
```

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
