# AutoCAD API 查证路线

## 官方资料优先级

1. Autodesk AutoCAD API 概览：说明 AutoCAD 可用 ObjectARX、Managed .NET、Visual LISP 和 ActiveX 等编程环境。
   - https://aps.autodesk.com/developer/overview/autocad-api
2. AutoCAD Developer and ObjectARX Help：查 Managed .NET、ActiveX/VBA、DXF Reference、AutoLISP、Core Console。
   - https://help.autodesk.com/view/OARX/2027/ENU/
3. Managed .NET Developer's Guide：用于 C# 插件、事务、文档锁、实体创建、标注、布局和打印。
   - https://help.autodesk.com/view/OARX/2027/ENU/?guid=GUID-C3F3C736-40CF-44A0-9210-55F6A939B6F2
4. ObjectARX SDK：用于 C++/C# 深度扩展、数据库结构、图形系统和原生命令。
   - https://aps.autodesk.com/developer/overview/objectarx-autocad-sdk
5. APS Design Automation：用于无桌面云端批处理 DWG。
   - https://aps.autodesk.com/en/docs/design-automation/v3

## GitHub 参考

- ADN-DevTech `acad-api-skill`：AI agent 生成 AutoCAD/Civil 3D/Plant 3D .NET 插件的规则。
  - https://github.com/ADN-DevTech/acad-api-skill
- ADN-DevTech `autocad-automation-apps`：APS Design Automation 的 AutoLISP、C++ CRX、.NET bundle 示例。
  - https://github.com/ADN-DevTech/autocad-automation-apps
- `reclosedev/pyautocad`：Python ActiveX 自动化封装，可借鉴坐标点、对象迭代和轻量 API 设计。
  - https://github.com/reclosedev/pyautocad
- AutoCAD .NET Wizards：Visual Studio AutoCAD .NET 项目模板。
  - https://github.com/ADN-DevTech/AutoCAD-Net-Wizards

## 查证流程

1. 先确定路线：COM/ActiveX、AutoLISP/SCR、.NET、ObjectARX、APS。
2. 搜索精确对象和方法名，例如 `ModelSpace AddLine ActiveX AutoCAD`、`DocumentLock AutoCAD .NET`。
3. 阅读目标版本文档，记录方法签名、参数类型、单位、返回值、异常和版本限制。
4. 找 GitHub 示例时优先看 Autodesk/ADN 官方仓库；第三方仓库只吸收模式，不直接照搬。
5. 写最小可运行脚本验证，保存输出文件，并用 `acad_review.py` 复核。
6. 如果文档和实测不一致，把本机版本、语言、错误码和解决办法写入 `troubleshooting.md`。

## COM/ActiveX 常用对象

- `AutoCAD.Application`：应用入口；可设置 `Visible`，访问 `Documents` 和 `ActiveDocument`。
- `Document`：当前图纸；包含 `ModelSpace`、`PaperSpace`、`Layers`、`Blocks`、`SelectionSets`、`SaveAs`、`SendCommand`。
- `ModelSpace`：创建几何实体，例如线、圆、多段线、文字和标注。
- `Layer`：图层颜色、线型和开关状态。
- `AcadEntity`：通用实体，可设置 `Layer`、`Color`，多数对象支持 `GetBoundingBox`。

## 常用方法核查清单

- 线：`ModelSpace.AddLine(startPoint, endPoint)`
- 圆：`ModelSpace.AddCircle(centerPoint, radius)`
- 轻量多段线：`ModelSpace.AddLightWeightPolyline(points2d)`
- 文字：`ModelSpace.AddText(text, insertionPoint, height)`
- 多行文字：`ModelSpace.AddMText(insertionPoint, width, text)`
- 保存：`Document.SaveAs(path)`
- 命令：`Document.SendCommand(command)`
- 视图：`Application.ZoomExtents()`

这些方法在不同 AutoCAD 版本、语言包、LT/完整版中可能有差异；未实测前不要承诺高级对象或导出格式一定可用。

## .NET 插件路线

当 COM 脚本变得难以维护，或需要事务、文档锁、选择过滤、命令注册、面板 UI、事件监听时，切换到 .NET：

1. 使用与 AutoCAD 版本匹配的 .NET 目标框架和 SDK 引用。
2. 命令入口使用 `CommandMethod`。
3. 数据库修改放入事务，涉及活动文档时正确锁定文档。
4. 使用 `NETLOAD` 或调试配置加载 DLL。
5. 插件成功后再考虑封装成 bundle 或 APS Design Automation activity。

## 资料使用底线

- 不凭记忆猜枚举值、保存类型、Plot 配置和命令参数。
- 不把论坛答案当最终依据；论坛只用于定位关键词和错误症状。
- 不复制许可证不明的 GitHub 代码进用户项目。
- 不把云端 APS 流程说成本地 AutoCAD COM 能力，也不把本地 COM 脚本说成可在 CI 直接运行。

