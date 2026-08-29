# SolidWorks 螺纹孔实测经验

## 2026-08-29 实测结论

以前 `CreateFeature(ThreadFeatureData)` 返回 `None` 的主要原因不只是“COM 不稳定”，而是创建数据不完整：

- `InitializeThreadData()` 后 `Type` 默认为空，内公制螺纹必须设置 `Type="Metric Tap"`。
- Thread Profiles 目录必须存在 `Metric Tap.SLDLFP`。官方文档允许 `Type` 使用不带路径和扩展名的轮廓名。
- 平面圆边使用选择标记 `1`，再设置 `IThreadFeatureData.Edge`。
- 已提供平面圆边时，不要再把同一圆边写入 `StartEntity`。
- `IThreadFeatureData` 没有 `LoadReferences(edge)` 创建步骤，不应调用。
- 底孔圆柱面已决定线程直径；不要用公称大径强制 `DiameterOverride=True`。

修正后的 M6×1 右旋内螺纹在 SolidWorks 2026 SP01.1 上实测成功：

| 场景 | 底孔 | Thread 终止 | 结果 |
|---|---|---|---|
| 16 mm 基体、12 mm 螺纹深度的盲孔 | Ø5.0、13 mm 定深 | `BlindDepth=12 mm` | `real-thread-verified`，review `pass/100` |
| 16 mm 基体的贯穿孔 | Ø5.0、`Through All` | `Revolutions=16` | `real-thread-verified`，review `pass/100` |

## 官方 API 依据

- [Thread Features and ThreadFeatureData Objects](https://help.solidworks.com/2026/English/api/sldworksapiprogguide/Overview/Thread_Features_and_ThreadFeatureData_Objects.htm)
- [IThreadFeatureData.Type](https://help.solidworks.com/2026/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IThreadFeatureData~Type.html)
- [IThreadFeatureData.Edge](https://help.solidworks.com/2026/English/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IThreadFeatureData~Edge.html)
- [swThreadEndCondition_e](https://help.solidworks.com/2026/English/api/swconst/SolidWorks.Interop.swconst~SolidWorks.Interop.swconst.swThreadEndCondition_e.html)
- [InsertCosmeticThread3](https://help.solidworks.com/2017/english/api/sldworksapi/SOLIDWORKS.Interop.sldworks~SOLIDWORKS.Interop.sldworks.IFeatureManager~InsertCosmeticThread3.html)
- [swCosmeticEndConditions_e](https://help.solidworks.com/2026/English/api/swconst/SolidWorks.Interop.swconst~SolidWorks.Interop.swconst.swCosmeticEndConditions_e.html)
- [BlankSketch](https://help.solidworks.com/2026/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IModelDoc2~BlankSketch.html)

## 正确的终止条件

底孔、真实 Thread 和 CosmeticThread 是三组不同枚举，不能混用：

```text
底孔 FeatureCut4:
  Blind      = swEndCondBlind (0)
  ThroughAll = swEndCondThroughAll (1)

ThreadFeatureData:
  Blind       = swThreadEndCondition_Blind (0)
  Revolutions = swThreadEndCondition_Revolutions (1)
  UpToSelect  = swThreadEndCondition_UpToSelection (2)

CosmeticThread:
  Blind   = swEndConditionBlind (0)
  Through = swEndConditionThrough (2)
```

贯穿底孔必须用 `FeatureCut4(..., T1=1, ...)`。使用“厚度 + 1 mm”的盲孔虽然视觉上穿透，但特征语义、后续修改和工程图识别都不正确。

## 参数验证底线

COM 调用前必须拒绝：

- NaN/无穷大、非正的基体尺寸、底孔、深度和倒角。
- 底孔直径大于等于公称直径。
- 螺纹深度大于盲孔底孔深度，或贯穿螺纹深度大于板厚。
- 孔中心越出基体，或没有为螺纹大径和孔口倒角保留边界。
- 表外公制螺距却没有显式 `--tap-drill`。攻丝底孔受切削材料、丝锥类型和螺纹百分比影响，不能只靠 `D-P` 通用估算当作确认值。

## 特征持久化证据

Thread/CosmeticThread 返回非空 COM 对象只是“尝试创建”，不是最终证据。脚本在 `ForceRebuild3(False)` 后遍历 `FirstFeature/GetNextFeature`，并递归遍历 `GetFirstSubFeature/GetNextSubFeature`，输出：

- `thread_attempts`：每种 API 的尝试结果和失败原因。
- `thread_evidence`：底孔、倒角、真实 Thread、CosmeticThread 和 3D 证据草图是否留在特征树。
- `thread_status`：基于重建后证据得出的 `real-thread-verified` / `cosmetic-thread-verified` / `visible-helix-verified`。若只剩自定义属性，模板会阻断交付。

SolidWorks 官方示例说明 CosmeticThread 是孔或切除的子特征。只遍历顶层特征会把已经持久化的 CosmeticThread 误判为丢失；当前证据收集已包含子特征。

## 3D 螺旋线只是证据表达

旧实现将 `thread_depth / pitch` 四舍五入为整数圈，会改变真实螺距。例如 16 mm 深、P=1.25 mm 应为 12.8 圈，不应改为 13 圈。当前使用小数圈和每圈 32 段以保持螺距，并将螺旋线限制在孔深之内。

SolidWorks 会把可见 3D 草图线透过实体显示，直接用于标准等轴测预览会出现外壁虚线。因此脚本先生成 `*_thread_evidence.bmp`，再通过 `BlankSketch()` 隐藏证据草图，标准预览只显示清洁模型。

3D 草图不是可切削牙型，不得将其宣称为 CAM 实体螺纹。

## 尚未覆盖的制造细节

当前盲孔底孔仍是平底切除，没有建模标准钻尖、有效全牙深度、不完整牙、攻丝退刀量和排屑空间。因此“底孔 + Thread”是良好的 CAD 和工程图语义，但不能在没有工艺复核的情况下宣称已完成全部攻丝工艺设计。

详细扩展顺序和验收门槛见 [threaded-hole-roadmap.md](threaded-hole-roadmap.md)。
