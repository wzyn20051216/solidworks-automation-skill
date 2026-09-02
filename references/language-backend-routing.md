# CAD 多语言后端路由

## 核心原则

不要把“某个 `I*` 方法不能由 Python 调用”扩大成“整个能力不能用 Python”。
先确认目标是业务能力还是某个精确接口，再按以下顺序选择：

1. 有同名非 `I` 方法、`CreateMassProperty` 等 Automation 兼容接口时，优先 Python `pywin32`。
2. 遇到 `SAFEARRAY`、`BYREF`、`object/out` 封送差异时，依次试显式 `VARIANT`、`comtypes`、C# PIA，并回读真实产物。
3. 官方明确写明“in-process, unmanaged C++ only”且任务要求原始接口语义时，才使用隔离的原生 C++ Add-in/桥。
4. 事件、PropertyManagerPage、TaskPane 和长期驻留回调优先 C# Add-in。
5. 缺许可证、缺加载项或 API 根本没有暴露数据时，换语言不能解除阻塞。

## 可执行查询

```powershell
# 查看全部原子操作和候选后端
python scripts/backend_router.py --list

# 常规底层数组任务：允许 Automation 等价接口，优先 Python
python scripts/backend_router.py `
  --operation solidworks_pointer_array_api `
  --available solidworks-com-pywin32

# 明确要求原始 I* 指针语义：选择原生 C++
python scripts/backend_router.py `
  --operation solidworks_pointer_array_api `
  --available solidworks-com-pywin32 `
  --available solidworks-native-cpp `
  --exact-api

# 已知 SW2026 SP1.1 保持线阻塞：返回 KNOWN_HOST_REVISION_BLOCKER
python scripts/backend_router.py `
  --operation fillet_hold_lines_exact `
  --available solidworks-native-cpp `
  --solidworks-revision 34.1.1
```

能力与路由的唯一真源是 `capabilities.yaml`。调用方应把实际检测到的后端、
SolidWorks Revision、加载项和许可证条件传给路由器，不得把“清单中存在”误当作“本机可用”。
未传 `--available` 时路由器会保守返回 `unavailable`，不会假定清单中的运行时已经安装。

## 已核实的接口边界

| 接口/场景 | 官方边界 | 首选策略 |
|---|---|---|
| `ISldWorks.IGetDocuments` | 返回指针数组，仅进程内非托管 C++ | 普通文档遍历用 Automation 接口；精确原始语义用 C++ |
| `IModelDocExtension.IGetMassProperties` / `IBody2.IGetMassProperties` | 返回 double 指针数组，托管语言不支持 | 优先 `GetMassProperties` / `CreateMassProperty`；原始数组才用 C++ |
| `IModelDocExtension.IListExternalFileReferences` | 多个指针数组，仅进程内非托管 C++ | 优先受支持的依赖/外部引用 Automation 路线；严格原始语义用 C++ |
| `ISldWorks.IGetDocumentDependencies2` | 原生字符串指针，仅进程内非托管 C++ | 普通交付用 `GetDependencies2`；原始接口才用 C++ |
| `IModelDoc2.IGetConfigurationNames` | 名称指针数组，仅进程内非托管 C++ | Python/C# 使用 `GetConfigurationNames` |
| `ISimpleFilletFeatureData2.ISetHoldLines` | 仅进程内非托管 C++ | 原生 C++ 是唯一精确路径；SW2026 SP1.1 已知宿主故障继续 blocked |
| `IPropertyManagerPage2` / 事件 / TaskPane | 需要稳定处理器与 Add-in 生命周期 | C# Add-in；Python 只做外部编排 |
| `IAnnotation` 精确文字包围盒 | API 未提供所需数据 | 保守估算 + PDF/图像回读 + 人工目视复核，不能换语言伪造 |

官方依据：

- [IGetDocuments](https://help.solidworks.com/2026/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.ISldWorks~IGetDocuments.html)
- [IGetMassProperties](https://help.solidworks.com/2026/english/api/sldworksapi/SOLIDWORKS.Interop.sldworks~SOLIDWORKS.Interop.sldworks.IModelDocExtension~IGetMassProperties.html)
- [IListExternalFileReferences](https://help.solidworks.com/2026/english/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IModelDocExtension~IListExternalFileReferences.html)
- [IGetDocumentDependencies2](https://help.solidworks.com/2026/English/api/sldworksapi/SOLIDWORKS.Interop.sldworks~SolidWorks.Interop.sldworks.ISldWorks~IGetDocumentDependencies2.html)
- [IGetConfigurationNames](https://help.solidworks.com/2026/English/api/sldworksapi/SOLIDWORKS.Interop.sldworks~SOLIDWORKS.Interop.sldworks.IModelDoc2~IGetConfigurationNames.html)
- [ISetHoldLines](https://help.solidworks.com/2025/English/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.ISimpleFilletFeatureData2~ISetHoldLines.html)
- [C# Add-in 模板与事件结构](https://help.solidworks.com/2026/English/api/sldworksapiprogguide/Overview/Using_SolidWorks_C__Add-In_Wizard_to_Create_C__Add-In.htm)
- [PropertyManagerPage2](https://help.solidworks.com/2026/English/api/sldworksapi/SolidWorks.Interop.sldworks~SolidWorks.Interop.sldworks.IPropertyManagerPage2.html)

## 当前能力分类

- Python 继续作为常规模型、装配、工程图、导出、配置族、属性和审计的默认编排语言。
- C# PIA 是强类型 Automation 封送回退，不是非托管 `I*` 指针接口的替代品。
- C# Add-in 专门承担事件、UI 与长期宿主生命周期。
- 原生 C++ 仅承担官方限定接口和必要的底层高吞吐几何，必须做版本白名单、崩溃隔离和真机回归。
- SWBasic/VBA 用于 SolidWorks 主线程最小复现和兼容性诊断，不能替代原生 C++。
- Python/OCP 用于开放格式无头几何；它不能生成原生 SolidWorks 特征树。
- AutoCAD 原生 DWG 数据库操作优先 C# .NET；不稳定的 ActiveX 不应继续由 Python 硬扛。
- CalculiX/Elmer 使用 Python 生成输入、编排原生求解器并审计结果；通过不等于工程认证。

## 仍需继续扩展

优先级从高到低：

1. C# Add-in 通用宿主：事件、PropertyManagerPage、TaskPane、主线程调度和版本化部署。
2. 原生 C++ 安全桥：仅封装已由官方文档确认的非托管接口，每个入口单独进程/版本门禁。
3. 钣金真实样件：基体法兰、边线法兰、展开、折弯参数与 DXF 展开证据。
4. 焊件真实样件：结构构件、角部处理、切割清单和长度/角度回读。
5. 配置族后续：派生配置、显示状态、配置专属抑制和设计表；不得沿用未经验证的旧签名。
6. Routing/Simulation 原生适配器：只有加载项和许可证证据齐全时启用。
