# 测量与装配检查原语 API 参考

提供零件整体尺寸、包围盒、装配体组件计数和特征/尺寸枚举等只读检查原语。能力清单记录为
`measurement_and_inspection=pilot`（SW2024 已在电机项目回归 3 外购件整体尺寸与装配组件计数）。

## 零件整体尺寸（最可靠：临时工程图 GetOutline@1:1）

对未类型化的 `OpenDoc6` 派发，`GetBox` 常不可解析；而工程图视图是**类型化**对象，
`GetOutline()` 恒可用、且与可选择性无关。因此整体尺寸用一张临时工程图测量：

```python
# 1. 新建一张临时工程图
drawing = new_document(sw, "drawing")
# 2. 画前视图 + 俯视图，比例强制 1:1（UseSheetScale=False + ScaleDecimal=1.0）
front = drawing.CreateDrawViewFromModelView3(part_path, "*Front", x, y, 0)
top   = drawing.CreateDrawViewFromModelView3(part_path, "*Top",   x, y, 0)
# 3. 读视图轮廓（米）-> 换算 mm
ol = front.GetOutline()      # [xmin, ymin, xmax, ymax]，单位米
width_mm  = (ol[2] - ol[0]) * 1000.0
height_mm = (ol[3] - ol[1]) * 1000.0
```

- 前视图给 **W（X）× H（Y）**；俯视图给 **W（X）× D（Y）**。
- W 取前/俯两视图的平均（两者应一致，取平均抑制微小数值差）。
- 视图轮廓含约 6 mm 余量（1:1 下），所以是**含余量的近似**，不是严格名义尺寸。
- 测完关闭临时图（不保存）。

> 比例必须强制为 1:1，否则 `GetOutline` 返回的是缩放后的米值。强制方法见
> `references/drawing.md` 的“视图比例与可选择性”。

## 包围盒

```python
# 类型化文档上可用（OpenDoc6 未类型化派发上可能 Member not found -> 回退到上面的临时图法）
box = model.GetBox(0)        # -> [xmin, ymin, zmin, xmax, ymax, zmax]，单位米
dx_mm = (max(box[0], box[3]) - min(box[0], box[3])) * 1000.0
# ...同理 dy, dz
```

- `GetBox(0)` 取实体包围盒；零件可能**非原点对称**，必须读 min/max，不能用 ±box[0]。
- 多实体零件：`model.GetBodies2(0, False)` 遍历各 `IBody2.GetBodyBox()` 取并集。
- 仍不可解析时回退到临时工程图法。

## 装配体组件计数

```python
# adoc: 已打开的装配体文档
components = adoc.GetComponents(True)   # True=扁平（所有实例），False=仅顶层
for comp in components:
    path = comp.GetPathName()           # 真方法 -> 可经 get_com_member 调用；返回模型文件全路径
    name = os.path.splitext(os.path.basename(path))[0]   # 去扩展名即零件名
```

- **不要用 `IComponent2.Name2` 属性**做计数：在动态派发下若被当方法处理会返回访问器函数
  对象，破坏计数。`GetPathName()` 是真方法，安全。
- `GetComponents(True)` 返回所有实例（含子装配内件），适合统计采购件数量；
  `GetComponents(False)` 只给顶层，适合看装配结构。

## 特征 / 尺寸枚举

```python
feat = model.GetFirstFeature()
while feat is not None:
    name = feat.Name                       # 属性
    type_name = feat.GetTypeName2()        # 方法
    for dim in feat.GetDimensions():       # 方法 -> IDimension 数组
        full_name = dim.FullName           # 属性
        value_m = dim.SystemValue          # 属性（米）
    feat = feat.GetNextFeature()
```

`Name` / `FullName` / `SystemValue` 是属性（经 `get_com_member` 无参读取）；
`GetTypeName2` / `GetDimensions` / `GetNextFeature` 是方法（带参或显式调用）。

## 技能封装（`scripts/sw_inspect.py`）

```python
from sw_connect import connect_solidworks, open_document
from sw_inspect import overall_dimensions, bounding_box, count_components, enumerate_features

sw, _ = connect_solidworks()

# 整体尺寸（内部建/弃临时工程图）
dims = overall_dimensions(sw, r"D:\parts\bolt.sldprt")
# -> {"status":"pass", "width_mm":.., "height_mm":.., "depth_mm":.., "method":"throwaway_drawing_getoutline_at_1to1", ...}

# 包围盒（类型化文档）
model = open_document(sw, r"D:\parts\bolt.sldprt")
bb = bounding_box(model)
comps = count_components(open_document(sw, r"D:\asm\station.sldasm"), flat=True)
feats = enumerate_features(model, max_features=200)
```

`count_components` 返回 `{"status":"pass", "counts":{name: n, ...}, "total": N, "flat": True}`。

## 占位几何告诚

外购/标准件在装配体中常为**示意占位几何**（实测一个 “M8 螺栓” 零件整体尺寸约
22×22×26 mm，与真实 M8×45 螺栓完全不符）。因此：

- **不得**直接拿模型测量值填 BOM 规格栏。
- 外购件规格须按**功能意图 + 装配堆叠**确定（如按夹紧厚度推算螺栓长度），不确定的参数
  （长度、直径、接口）在 BOM 中标 “请复核”。
- 整体尺寸/包围盒只用于验证 API 通路和装配空间检查，不作为采购规格依据。

## 回归证据

SW2024 电机项目（`measure_parts.py` / `count_parts.py`）：

- 3 个外购件整体尺寸经临时图法测得（占位值，仅验证通路）。
- 装配组件计数（扁平）：螺栓M8 ×8、钻头M5 ×1、钻夹头 ×1 —— 用于生成采购 BOM 数量栏。
