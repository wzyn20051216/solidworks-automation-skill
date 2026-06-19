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

### COM 伪可调用属性导致“找不到成员”

场景：遍历特征树或读取模型摘要时，`FirstFeature`、`GetNextFeature`、`GetTitle` 等成员在 pywin32 中显示 `callable=True`，但调用后报：

```text
(-2147352573, '找不到成员。', None, None)
```

原因：SolidWorks 某些 COM 成员在动态派发下既可能表现为属性，也可能表现为方法；`callable(member)` 不能作为唯一判断。

稳定写法：优先使用 `sw_connect.get_com_member()` 或 `sw_assembly.safe_get_com_member()`。

```python
from sw_connect import get_com_member

feature = get_com_member(model, "FirstFeature")
while feature:
    print(get_com_member(feature, "Name"), get_com_member(feature, "GetTypeName2"))
    feature = get_com_member(feature, "GetNextFeature")
```

### Motion Study 成员“找不到成员”

场景：`model.Extension.GetMotionStudyManager()` 或 `motion_mgr.CreateMotionStudy()` 报：

```text
(-2147352573, '找不到成员。', None, None)
```

常见原因：

1. Motion Study 的强类型接口位于 `swmotionstudy.tlb`，不是主 `sldworks` 类型库。
2. pywin32 动态派发下，`GetMotionStudyManager`、`CreateMotionStudy`、`Activate`、`Calculate`、`Play` 可能表现为属性，不是方法。

稳定写法：优先使用 `sw_motion.py`。

```python
from sw_motion import create_motion_study, motion_member

study = create_motion_study(asm, name="Motion_60RPM", duration=4.0)
calculated = motion_member(study, "Calculate")
```

如果必须底层调用，先加载类型库：

```python
from sw_motion import ensure_motion_type_library

ensure_motion_type_library(raise_on_error=True)
motion_mgr = asm.Extension.GetMotionStudyManager
study = motion_mgr.CreateMotionStudy
```

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

### GetModelDoc2 返回 None

场景：装配体中组件明明存在，但 `component.GetModelDoc2()` 返回 `None`，后续无法读取基准面、实体面或特征。

常见原因：

1. 组件处于压缩或轻化状态。
2. 组件引用文件没有加载到内存。
3. 刚添加组件后装配体尚未解析。

稳定写法：先解析组件，再读取模型；优先用 `sw_assembly.get_component_model()`。

```python
from sw_assembly import get_component_model, resolve_component

resolve_component(component)  # 默认 swComponentFullyResolved=2，失败时回退 swComponentResolved=3
part = get_component_model(component)
```

### AddComponent4 返回 None

场景：SW2024 中文版 + pywin32 下，`asm.AddComponent4(path, "", x, y, z)` 无异常但持续返回 `None`，导致装配体无法添加零件。

稳定写法：优先使用 `sw_assembly.add_component()`。当前封装先检查文件路径，然后调用 `AddComponent5(path, 0, "", False, config, x, y, z)`，失败后回退 `AddComponent4()`；若仍为空，会自动静默打开零件、重新激活装配体，再重试 `AddComponent5()`。

```python
from sw_assembly import add_component, get_components

component = add_component(asm, r"E:\parts\probe_block.SLDPRT", x=0, y=0, z=0)
if component is None:
    raise RuntimeError("添加组件失败")
print(get_components(asm))
```

真实 SolidWorks 回归验证：

```powershell
py -3.13 tests\solidworks_add_component_regression.py --output-dir E:\desktop\CAD\solidworks_add_component_regression
```

通过标准：`component_count >= 1`，`component_name` 非空，`.SLDASM` 保存成功，`review_evaluation.status` 为 `pass` 或至少 `review_checks.expected_outputs_exist=true`。

### Mate 创建后特征树没有真实配合

场景：脚本报告“成功”，但 SolidWorks 里没有 Gear Mate / Concentric Mate，拖动也不会联动。

排查：

1. `AddMate5()` 是否返回 `None`。
2. by-ref `ErrorStatus` 是否为成功码；`swAddMateError_NoError=1`，部分版本也会在成功时返回 0。
3. 创建前选择集是否正好有 2 个对象。
4. 选择对象是否为装配体上下文实体，而不是零件文档内实体。
5. Mate 是否写入 `MateGroup` 子特征。

稳定写法：

```python
from sw_assembly import add_mate5_checked, collect_mate_feature_summary

mate = add_mate5_checked(asm, 1, lock_rotation=False, name="shaft_concentric")
print(collect_mate_feature_summary(asm))
```

### AddMate5 返回 Mate 但 error_status=1

场景：`AddMate5()` 返回了非空 Mate，SolidWorks 特征树里也有配合，但脚本仍报失败：

```text
AddMate5 失败: type=1, error_status=1
```

原因：`swAddMateError_e` 中 `1=swAddMateError_NoError`，不是错误。不要只把 `0` 当成功。

验证命令：

```powershell
Add-Type -Path 'E:\Solidworks\SOLIDWORKS\SolidWorks.Interop.swconst.dll'
[int][SolidWorks.Interop.swconst.swAddMateError_e]::swAddMateError_NoError
```

稳定写法：使用新版 `sw_assembly.add_mate5_checked()`，它接受 `0` 和 `1` 作为成功码，并仍会检查 Mate 是否为空。

### 选择集被清空

场景：第一个面选择成功，执行解析组件或切换文档后，第二个面选择成功但 `AddMate5()` 失败。

原因：`SetSuppression2()`、激活文档、部分重建操作会清空或改变选择集。

稳定顺序：

1. 先解析所有参与 Mate 的组件。
2. 再用 `GetCorresponding()` 映射到装配体上下文。
3. 再清空选择集并连续选择两个实体。
4. 立即调用 `AddMate5()`。

```python
from sw_assembly import select_entities_for_mate

select_entities_for_mate(asm, entity_a, entity_b, mark=1)
```

### GetCorresponding 返回 None

场景：零件内基准面或面存在，但 `component.GetCorresponding(face_or_feature)` 返回 `None`。

常见原因：

1. 传入对象不是该组件引用文档里的对象。
2. 组件未解析。
3. 使用了错误组件实例；同一零件插入多次时必须用目标实例调用 `GetCorresponding()`。
4. 选择的是临时几何或已失效对象。

稳定写法：从 `get_component_model(component)` 返回的模型中查找特征/面，再由同一个 `component` 映射。

### 同心 Mate 后零件不能转

原因通常不是“没有铰链”，而是旋转自由度被锁死：

1. `lock_rotation=True` 或 GUI 中勾选了 Lock Rotation。
2. 旋转件又被三个基准面重合约束完全固定。
3. 组件本身被固定。
4. 轴向定位 Mate 太多，导致过定义。

做运动装配时，同心 Mate 默认应使用：

```python
add_concentric_mate_by_cylinders(..., lock_rotation=False)
```

上盖铰链可用同心 Mate 保留旋转，再用一个平面重合/距离 Mate 限制轴向窜动。

### 特征创建失败（返回 None）

常见原因：
1. **未选择正确实体** - 检查 SelectByID2 的实体名称和类型
2. **草图未完全约束** - 添加足够的约束和尺寸
3. **草图有开环** - 拉伸需要闭合轮廓
4. **单位错误** - API 使用米，不是毫米

### SelectByID2("SKETCH") 持续返回 False

场景：SolidWorks 2024 中文版中，`SelectByID2("草图1", "SKETCH", ...)` 和 `SelectByID2("Sketch1", "SKETCH", ...)` 都返回 `False`，随后 `FeatureExtrusion3()` 返回 `None`。

根因：部分版本/语言环境下，草图名称选择不稳定；旧版 `sw_part._ensure_sketch_selected()` 还曾经把“当前选择集数量 > 0”当成成功条件，导致前几个零件靠残留选择集偶然成功，选择集被清空后全部失败。

稳定写法：

1. 优先使用 `with sketch(model, "...") as sketch_name:`，由 `sw_part.py` 在创建草图时缓存真实草图对象引用。
2. 不要在特征创建前依赖残留选择集；切换文档、重建、解析组件和失败的 API 调用都可能清空选择集。
3. 选择草图时优先用对象级 `Select2()` 选择草图 Feature / Sketch；最后才回退 `SelectByID2("SKETCH")`。
4. 若必须手写底层流程，`end_sketch(model)` 的返回值可直接传给 `extrude_boss()` / `extrude_cut()`。

```python
from sw_part import end_sketch, extrude_boss, sketch_circle, start_sketch

start_sketch(model, "Front Plane")
sketch_circle(model, 0, 0, 0.025)
sketch_ref = end_sketch(model)
feature = extrude_boss(model, sketch_ref, 0.05)
if feature is None:
    raise RuntimeError("拉伸失败：检查草图闭合、方向和对象选择")
```

真实 SolidWorks 回归验证：

```powershell
py -3.13 tests\solidworks_sketch_selection_regression.py --output-dir E:\desktop\CAD\solidworks_skill_regression
```

通过标准：脚本在两次 `ClearSelection2(True)` 后都报告 `selection_count=0`，随后仍能生成 `凸台-拉伸1` 和 `切除-拉伸1`，保存 `.SLDPRT`、导出 `.step`，并且 `review_evaluation.status` 为 `pass`。

### FeatureCut4 长参数不稳定

场景：手写 `FeatureCut4(...)` 后特征返回 `None`，但同一草图在 GUI 或封装函数中可切除。

原因：`FeatureCut4` 参数多，终止条件、翻转方向、`FlipSide`、`NormalCut`、选择集状态任一不匹配都会静默失败。不要凭记忆拼长参数。

稳定写法：

1. 优先使用 `sw_part.extrude_cut()`。
2. 如果必须底层调用，先用最小圆柱/矩形测试各种方向和终止条件。
3. 每次切除后检查返回特征对象；失败时不要继续保存交付文件。

```python
from sw_part import extrude_cut

feature = extrude_cut(model, sketch_name, 0, direction=True, flip=False)
if feature is None:
    feature = extrude_cut(model, sketch_name, 0, direction=True, flip=True)
if feature is None:
    raise RuntimeError("切除失败，需检查草图、方向或终止条件")
```

### 中心基准面切槽导致轴被剖开

场景：轴类零件上要做长圆槽/键槽，脚本在 `Front Plane` 上画槽并盲切，结果模型出现沿轴向的大平面切口，看起来像把圆柱剖掉一半。

原因：`Front Plane` 常穿过轴线，不是圆柱外表面。直接从中心面切槽会产生剖切效果，而不是表面凹槽。

稳定写法：先创建切向偏置参考面，再在该平面上画槽并按槽深盲切；见 `references/part-modeling.md` 的“圆柱表面长圆槽”。

### 槽特征树成功但预览不可见

场景：特征树中已有 `Cut_*_Slot`，`run_review()` 也通过，但等轴测或主视图看不到槽。

排查：

1. 槽是否切到了背侧；尝试翻转 `flip` 或导出另一侧视图。
2. 槽是否从中心面切除但被当前着色遮挡；查看俯视/右视。
3. 特征是否只切掉了不可见的内部体积；用剖视或修改切向参考面确认。
4. 预览图是否显示了被选中的参考面，导致遮挡槽轮廓。

处理：不要只依赖 `feature is not None`。导出 `isometric/front/top/right`，目视确认关键几何确实出现。

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

### SaveAs 错误码 1 或覆盖失败

场景：`session.save(model, path)` 或 `model.Extension.SaveAs(...)` 返回失败，错误码为 `1`，目标文件明明存在且路径正确。

常见原因：同名文档已经在 SolidWorks 会话中打开，或目标文件被当前 SolidWorks 进程占用，导致覆盖失败。

稳定写法：

```python
session = SolidWorksSession()
session.sw.CloseDoc("Drawing_Stepped_Shaft.SLDPRT")
model = session.new_part()
```

注意：只关闭本次脚本明确要覆盖的输出文档，不要盲目 `CloseAllDocuments()`，除非用户确认可以清理整个会话。

### 临时 SLDPRT 删除失败

场景：PowerShell `Remove-Item` 报：

```text
The process cannot access the file ... because it is being used by another process.
```

原因：调试零件仍在 SolidWorks 中打开。

处理顺序：

1. 用 `sw.CloseDoc("<文件名>.SLDPRT")` 关闭对应文档。
2. 再用 `Remove-Item -LiteralPath <path> -Force` 清理临时文件。
3. 删除前校验路径只匹配预期临时文件，例如 `debug_*.SLDPRT`。

### 参考面或草图污染预览图

场景：`run_review()` 导出的 BMP 出现橙色大参考面、草图或选择高亮，影响判断实体几何。

稳定写法：

```python
for plane_name in created_plane_names:
    model.ClearSelection2(True)
    selected = model.Extension.SelectByID2(
        plane_name, "PLANE", 0, 0, 0, False, 0,
        create_empty_dispatch_variant(), 0,
    )
    if selected:
        model.BlankRefGeom()

model.BlankSketch()
model.ClearSelection2(True)
model.ForceRebuild3(False)
```

`BlankRefGeom()` 通常需要先选择要隐藏的参考几何；单独调用不一定隐藏脚本新建的基准面。

### MathUtility.CreateTransform 不稳定

场景：尝试 `sw.GetMathUtility().CreateTransform(data)` 或 `math_utility.CreateTransform()` 时 COM 返回异常、空对象，或组件移动后不求解。

稳定写法：读取组件已有 `Transform2`，修改 `ArrayData`，再调用 `SetTransformAndSolve2()`；失败时再回退到 `component.Transform2 = transform`。

```python
from sw_assembly import apply_component_transform_x
from sw_connect import deg

ok = apply_component_transform_x(component, 0.1, 0.0, 0.0, deg(30))
```

注意：直接改 Transform 适合生成演示帧或定位；如果目标是在 SolidWorks 里可拖动，仍要靠真实 Mate 保留自由度。

### SolidWorks 内部错误或 COM 变慢

场景：大批量生成零件/装配后，`AddComponent4`、保存、导出或特征操作随机失败。

常见原因：打开文档过多、图形窗口和特征树刷新堆积、同一进程长时间运行。

处理顺序：

1. 保存关键输出。
2. 调用 `sw.CloseAllDocuments(False)` 清理会话。
3. 分批重新打开必要零件并装配。
4. 仍不稳定时，让用户确认后重启 `SLDWORKS.exe`。
5. 脚本内记录失败组件和失败 API，不要只打印“完成”。

## 未封装 API 调用

当需要使用本 skill 尚未封装的 SolidWorks API 时：

1. 先查 SolidWorks 官方 API 文档或本地 SDK 文档，确认接口签名和枚举。
2. 用最小脚本验证接口，不要直接嵌入大任务。
3. 对 COM 返回值做 `None` / `False` 检查，并打印错误码/警告码。
4. 完成后把稳定写法补进 `scripts/`，把坑位补进本文件或对应 `references/*.md`。

沉淀模板：

```text
### <API 或错误现象>

场景:
错误/症状:
原因:
稳定写法:
  # 最小可运行示例
验证方式:
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
