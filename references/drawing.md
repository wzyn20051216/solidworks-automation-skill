# 工程图 API 参考

## 创建视图

### 标准三视图

```python
drawing.Create3rdAngleViews2(partPath)  # 第三角投影法
drawing.CreateFirstAngleViews2(partPath) # 第一角投影法
```

### 自定义视图

```python
view = drawing.CreateDrawViewFromModelView3(
    ModelName,     # str: 零件/装配体路径
    ViewName,      # str: 视图方向（见下表）
    X, Y, Z        # float: 放置位置（米）
)
```

视图方向名称：
| 名称 | 说明 |
|---|---|
| `*Front` | 前视图 |
| `*Back` | 后视图 |
| `*Top` | 俯视图 |
| `*Bottom` | 仰视图 |
| `*Left` | 左视图 |
| `*Right` | 右视图 |
| `*Isometric` | 等轴测 |
| `*Trimetric` | 三等轴测 |
| `*Dimetric` | 二等轴测 |

### 设置视图比例

```python
view.ScaleRatio = (1.0, 2.0)  # 1:2 比例
view.ScaleRatio = (2.0, 1.0)  # 2:1 比例
```

## 尺寸标注

### 自动标注（模型项目）

```python
drawing.Extension.InsertModelAnnotations3(
    InsertType,    # int: 0=整个模型
    AnnotationType, # int: 32=标记为图纸的尺寸
    DuplicateDims, # bool
    AutoArrange,   # bool
    UseDoc,        # bool
    UseView        # bool
)
```

### 手动添加尺寸

```python
# 先选择两个实体
drawing.Extension.SelectByID2("Edge1@View1", "EDGE", 0, 0, 0, False, 0, None, 0)
drawing.Extension.SelectByID2("Edge2@View1", "EDGE", 0, 0, 0, True, 0, None, 0)
# 添加尺寸
drawing.AddDimension2(x, y, 0)  # 尺寸标注放置位置
```

## 注释与标注

```python
# 添加注释
note = drawing.InsertNote(text)

# 添加表面粗糙度符号
drawing.InsertSurfaceFinishSymbol3(...)

# 添加焊接符号
drawing.InsertWeldSymbol(...)

# 添加基准符号
drawing.InsertDatumTag2(...)
```

## BOM 表

```python
bom = drawing.InsertBomTable4(
    TemplateName,  # str: BOM 模板路径(.sldbomtbt)
    X, Y,          # float: 位置
    BomType,       # int: 1=顶层, 2=仅零件, 3=缩进
    Configuration, # str: 配置名
    TableAnchor,   # str: 锚点名
    Hidden         # bool: 是否包含隐藏组件
)
```

## 图纸操作

```python
# 获取当前图纸
sheet = drawing.GetCurrentSheet()

# 获取所有图纸名称
names = drawing.GetSheetNames()

# 激活指定图纸
drawing.ActivateSheet(sheetName)

# 添加新图纸
drawing.NewSheet4(
    Name,        # str: 图纸名称
    PaperSize,   # int: 纸张大小（5=A4, 6=A3, 7=A2, 8=A1, 9=A0）
    TemplateIn,  # int: 12=自定义
    Scale1,      # float: 比例分子
    Scale2,      # float: 比例分母
    FirstAngle,  # bool: 第一角投影法
    Template,    # str: 图纸格式路径
    W, H,        # float: 宽高
    PropertySheet, # str
    Zone_LeftMargin, Zone_RightMargin, Zone_TopMargin, Zone_BottomMargin,
    Zone_Col, Zone_Row  # int: 分区
)

# 设置图纸格式
sheet.SetTemplateName(formatPath)  # .slddrt 文件路径
```

## 导出 PDF

```python
sw = model.GetSldWorksObject()
pdf_data = sw.GetExportFileData(1)  # swExportPDFData
sheet_names = drawing.GetSheetNames()
pdf_data.SetSheets(0, sheet_names)  # 0=指定图纸

errors = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
warnings = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
model.Extension.SaveAs("output.pdf", 0, 1, pdf_data, errors, warnings)
```
