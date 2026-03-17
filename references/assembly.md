# 装配体 API 参考

## 添加组件

```python
component = asm_model.AddComponent4(
    CompPath,    # str: 零件/子装配体文件路径
    ConfigName,  # str: 配置名（空字符串=默认）
    X, Y, Z      # float: 放置位置（米）
)
```

## 配合类型

### AddMate5 参数

```python
mate = asm_model.AddMate5(
    MateTypeFromEnum,   # int: 配合类型（见下表）
    AlignFromEnum,      # int: 对齐方式（0=Aligned, 1=Anti-Aligned）
    Flip,               # bool: 翻转方向
    Distance,           # float: 距离值（距离配合时使用）
    DistanceAbsUpperLimit,  # float: 距离上限
    DistanceAbsLowerLimit,  # float: 距离下限
    GearRatioNumerator,    # float: 齿轮比分子
    GearRatioDenominator,  # float: 齿轮比分母
    Angle,                 # float: 角度（弧度）
    AngleAbsUpperLimit,    # float: 角度上限
    AngleAbsLowerLimit,    # float: 角度下限
    ForPositioningOnly     # bool: 仅用于定位
)
```

### 配合类型枚举

| 值 | 名称 | 说明 |
|---|---|---|
| 0 | swMateCOINCIDENT | 重合 |
| 1 | swMateCONCENTRIC | 同心 |
| 2 | swMatePERPENDICULAR | 垂直 |
| 3 | swMatePARALLEL | 平行 |
| 4 | swMateTANGENT | 相切 |
| 5 | swMateDISTANCE | 距离 |
| 6 | swMateANGLE | 角度 |
| 8 | swMateLOCK | 锁定 |
| 20 | swMateWIDTH | 宽度 |

## 组件操作

```python
# 获取所有组件
components = asm.GetComponents(True)  # True=仅顶层

# 遍历组件
for comp in components:
    print(comp.Name2)           # 组件名
    print(comp.GetPathName())   # 文件路径
    print(comp.IsSuppressed())  # 是否被压缩

# 压缩/解压缩
comp.SetSuppression2(0)  # 0=Resolved, 2=Suppressed, 3=Lightweight

# 替换组件
asm.ReplaceComponents2(newPath, configName, False, replaceType, True)
```

## 干涉检查

```python
interference = asm.InterferenceDetection
interference.TreatSubAssembliesAsComponents = False
interference.TreatCoincidenceAsInterference = False
interference.Done()
count = interference.GetInterferenceCount()
```

## 爆炸视图

```python
# 创建爆炸视图需要通过配置管理器
config = model.GetActiveConfiguration()
# 使用 IExplosionStepData 创建爆炸步骤
```
