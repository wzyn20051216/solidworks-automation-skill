# 零件建模 API 参考

## 草图操作

### 基准面选择

```python
# 英文版
model.Extension.SelectByID2("Front Plane", "PLANE", 0, 0, 0, False, 0, None, 0)
# 中文版
model.Extension.SelectByID2("前视基准面", "PLANE", 0, 0, 0, False, 0, None, 0)
```

基准面对应关系：
| 英文 | 中文 | 法线方向 |
|---|---|---|
| Front Plane | 前视基准面 | Z 轴 |
| Top Plane | 上视基准面 | Y 轴 |
| Right Plane | 右视基准面 | X 轴 |

### 草图几何体方法速查

| 方法 | 参数 | 说明 |
|---|---|---|
| `CreateLine(x1,y1,z1, x2,y2,z2)` | 起点终点坐标（米） | 直线 |
| `CreateCircleByRadius(cx,cy,cz, r)` | 圆心+半径 | 圆 |
| `CreateCenterRectangle(cx,cy,cz, rx,ry,rz)` | 中心+角点 | 中心矩形 |
| `CreateCornerRectangle(x1,y1,z1, x2,y2,z2)` | 对角点 | 角点矩形 |
| `CreateArc(cx,cy,cz, x1,y1,z1, x2,y2,z2, dir)` | 圆心+起终点+方向 | 圆弧 |
| `CreatePolygon(cx,cy,cz, sx,sy,sz, sides, inscr)` | 中心+顶点+边数 | 正多边形 |
| `CreateEllipse(cx,cy,cz, mx,my,mz, r)` | 中心+长轴端点+短轴半径 | 椭圆 |
| `CreateSpline2(pointArray, closed)` | 点数组+是否闭合 | 样条曲线 |
| `CreateSketchSlot(type, w, w, ...)` | 类型+宽度+端点 | 槽口 |

### 草图约束

```python
# 选中实体后添加约束
model.SketchAddConstraints("sgHORIZONTAL")
```

常用约束类型：`sgFIXED`, `sgHORIZONTAL`, `sgVERTICAL`, `sgCOLINEAR`, `sgPARALLEL`, `sgPERPENDICULAR`, `sgTANGENT`, `sgCONCENTRIC`, `sgEQUAL`, `sgSYMMETRIC`, `sgMIDPOINT`, `sgCOINCIDENT`

## 特征操作

### FeatureExtrusion3 参数详解

```python
feature_mgr.FeatureExtrusion3(
    Sd,           # bool: 单方向（True）或双方向（False）
    Flip,         # bool: 翻转切割方向
    Dir,          # bool: 翻转挤出方向
    T1,           # int: 终止条件1 (见下表)
    T2,           # int: 终止条件2（双方向时使用）
    D1,           # float: 深度1（米）
    D2,           # float: 深度2
    Dchk1,        # bool: 拔模1
    Dchk2,        # bool: 拔模2
    Ddir1,        # bool: 拔模方向1向外
    Ddir2,        # bool: 拔模方向2向外
    Dang1,        # float: 拔模角度1（弧度）
    Dang2,        # float: 拔模角度2
    OffsetReverse1, # bool: 偏移反转1
    OffsetReverse2, # bool: 偏移反转2
    TranslateSurface, # bool: 平移曲面
    Merge,        # bool: 合并结果
    UseFeatScope, # bool: 自动选择实体范围
    UseAutoSelect, # bool: 自动选择
    T0,           # bool:
    StartOffset   # float: 起始偏移
)
```

终止条件枚举：
| 值 | 名称 | 说明 |
|---|---|---|
| 0 | swEndCondBlind | 给定深度 |
| 1 | swEndCondThroughAll | 完全贯穿 |
| 2 | swEndCondThroughAllBoth | 两侧贯穿 |
| 5 | swEndCondUpToSurface | 成形到一曲面 |
| 6 | swEndCondMidPlane | 两侧对称 |
| 7 | swEndCondUpToBody | 成形到实体 |

### FeatureCut4 参数详解

与 FeatureExtrusion3 类似，但用于切除操作。额外参数：
- `NormalCut`: 法向切除
- `FlipSide`: 翻转切除侧

### FeatureRevolve2 参数

```python
feature_mgr.FeatureRevolve2(
    SingleDir,     # bool: 单方向
    IsSolid,       # bool: 实体旋转（True）
    IsThin,        # bool: 薄壁旋转
    IsCut,         # bool: 切除旋转
    ReverseDir,    # bool: 反转方向
    BothDirectionUpToSameEntity, # bool
    Dir1Type,      # int: 终止条件（0=Blind）
    Dir2Type,      # int
    Dir1Angle,     # float: 旋转角度（弧度）
    Dir2Angle,     # float
    OffsetReverse1, # bool
    OffsetReverse2, # bool
    OffsetDistance1, # float
    OffsetDistance2, # float
    ThinType,      # int: 薄壁类型
    ThinThickness1, # float
    ThinThickness2, # float
    Merge,         # bool
    UseFeatScope,  # bool
    UseAutoSelect  # bool
)
```

### 圆角/倒角

```python
# 圆角 FeatureFillet 参数
feature_mgr.FeatureFillet(
    Options,   # int: 195 = 常用默认值
    R1,        # float: 半径（米）
    R2,        # float: 第二半径
    R3,        # float: 第三半径
    Rarray1,   # variant: 半径数组1
    Rarray2,   # variant: 半径数组2
    Rarray3    # variant: 半径数组3
)

# 倒角 InsertFeatureChamfer
feature_mgr.InsertFeatureChamfer(
    Options,     # int: 4 = 角度距离
    ChamferType, # int: 1 = 等距离
    Width,       # float: 距离（米）
    Angle,       # float: 角度（弧度）
    OtherDist,   # float: 另一距离
    VertexDist1, # float
    VertexDist2, # float
    VertexDist3  # float
)
```

### 圆角/倒角当前可靠边界

圆角和倒角的核心难点不是 API 参数本身，而是**稳定选择目标边线/面**。不同 SolidWorks 版本、界面语言、特征顺序和草图轮廓都会改变自动命名的 `Edge`/`Face`，因此不要把“随机坐标 SelectByID2 选边 + FeatureFillet”当成高可靠流程。

推荐策略：

1. 基准 demo 和无人值守批量脚本不要把圆角/倒角作为成功标准。
2. 需要圆角时，优先在建模阶段用更稳定的草图轮廓近似，例如圆弧、槽口、圆角矩形草图。
3. 必须做特征圆角/倒角时，先通过 body/face/edge 枚举按几何条件过滤目标边，再选择实体对象调用特征，不要依赖临时的 `Edge1` 名称。
4. 圆角失败应降级为保留直边模型，并在审查报告或最终说明中标注“外观圆角未应用”，不要让模型生成流程整体失败。

## SelectByID2 实体类型

| 类型字符串 | 说明 |
|---|---|
| `"PLANE"` | 基准面 |
| `"FACE"` | 面 |
| `"EDGE"` | 边线 |
| `"VERTEX"` | 顶点 |
| `"SKETCH"` | 草图 |
| `"BODYFEATURE"` | 实体特征 |
| `"COMPONENT"` | 组件 |
| `"AXIS"` | 轴线 |
| `"SKETCHSEGMENT"` | 草图线段 |
| `"SKETCHPOINT"` | 草图点 |
| `"EXTSKETCHSEGMENT"` | 外部草图线段 |
| `"REFERENCECURVES"` | 参考曲线 |
