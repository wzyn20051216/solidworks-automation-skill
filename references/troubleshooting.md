# 常见问题排查

## 连接问题

### 无法连接到 SolidWorks

```
错误: pywintypes.com_error: (-2147221005, '无效的类字符串', None, None)
```

**原因**: SolidWorks 未安装或 COM 未注册
**解决**: 确认 SolidWorks 已安装，尝试指定版本号连接：
```python
sw = win32com.client.Dispatch("SldWorks.Application.32")  # SW 2024
```

### GetActiveObject 失败

```
错误: pywintypes.com_error: (-2147221021, '操作不可用', None, None)
```

**原因**: SolidWorks 未运行
**解决**: 先手动启动 SolidWorks，或使用 `Dispatch` 启动新实例

### Python 32/64 位不匹配

**原因**: Python 位数必须与 SolidWorks 一致（通常为 64 位）
**解决**: 安装 64 位 Python

## 类型错误

### SelectByID2 类型不匹配

```
错误: TypeError: Objects of type 'NoneType' can not be converted to a COM VARIANT
```

**解决**: 对 Callout 参数使用显式 VARIANT：
```python
from win32com.client import VARIANT
import pythoncom
callout = VARIANT(pythoncom.VT_DISPATCH, None)
model.Extension.SelectByID2("Front Plane", "PLANE", 0, 0, 0, False, 0, callout, 0)
```

### by-ref 参数错误

**解决**: 使用 VARIANT 包装输出参数：
```python
errors = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
warnings = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
```

## 操作失败

### 特征创建失败（返回 None）

常见原因：
1. **未选择正确实体** - 检查 SelectByID2 的实体名称和类型
2. **草图未完全约束** - 添加足够的约束和尺寸
3. **草图有开环** - 拉伸需要闭合轮廓
4. **单位错误** - API 使用米，不是毫米

### 基准面选择失败

**原因**: 中英文名称不同
**解决**:
```python
# 尝试英文名称
success = model.Extension.SelectByID2("Front Plane", "PLANE", 0, 0, 0, False, 0, None, 0)
if not success:
    # 尝试中文名称
    model.Extension.SelectByID2("前视基准面", "PLANE", 0, 0, 0, False, 0, None, 0)
```

### 保存/导出失败

检查错误码：
```python
errors = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
warnings = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
success = model.Extension.SaveAs(path, 0, 1, None, errors, warnings)
print(f"错误码: {errors.value}, 警告码: {warnings.value}")
# 查看 references/export.md 中的错误码对照表
```

## 性能优化

### 大型装配体操作慢

```python
# 开启后台处理模式
model.FeatureManager.EnableFeatureTree = False
model.ActiveView.EnableGraphicsUpdate = False

# ... 执行操作 ...

# 恢复并刷新
model.FeatureManager.EnableFeatureTree = True
model.ActiveView.EnableGraphicsUpdate = True
model.GraphicsRedraw2()
```

### 批量操作优化

```python
# 禁用自动重建
sw.UserControl = False

# 执行批量操作...

# 手动重建
model.EditRebuild3()
sw.UserControl = True
```

## 版本号对照

| SolidWorks | 修订号 | ProgID |
|---|---|---|
| 2020 | 28 | SldWorks.Application.28 |
| 2021 | 29 | SldWorks.Application.29 |
| 2022 | 30 | SldWorks.Application.30 |
| 2023 | 31 | SldWorks.Application.31 |
| 2024 | 32 | SldWorks.Application.32 |
| 2025 | 33 | SldWorks.Application.33 |

公式: `修订号 = (年份 - 2000) + 8`
