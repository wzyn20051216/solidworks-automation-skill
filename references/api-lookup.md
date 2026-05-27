# SolidWorks API 查证流程

当任务需要使用 `scripts/` 尚未封装的 SolidWorks API 时，先查证再实现。不要凭记忆补长参数、枚举值或返回值。

## 优先资料源

1. 官方网页：`https://help.solidworks.com`
   - 搜索关键词建议：
     - `site:help.solidworks.com SolidWorks API Help <InterfaceName> <MethodName>`
     - `site:help.solidworks.com <MethodName> Method (SOLIDWORKS API Help)`
     - `site:help.solidworks.com swSaveAsOptions_e`
2. 本地 SDK / API Help：
   - 常见入口：SolidWorks 安装目录下的 `api`、`api\help`、`api\redist`
   - 常见类型库：`SolidWorks.Interop.sldworks.dll`、`SolidWorks.Interop.swconst.dll`
3. 本仓库封装与经验：
   - 优先搜索 `scripts/*.py`
   - 再查 `references/*.md`
   - 最后才写新的最小验证脚本

## 必查 API 类型

- `IModelDocExtension.SaveAs*`、`OpenDoc*`、`CloseDoc`、导出相关 API
- `SelectByID2`、选择标记、选择类型字符串与选择追加逻辑
- `FeatureManager.FeatureExtrusion*`、`FeatureCut*`、扫描、放样、圆角、倒角等长参数方法
- `IAssemblyDoc.AddComponent*`、`AddMate*`、组件变换、轻化/压缩状态
- 外观/材质：`MaterialPropertyValues`、`IMaterialVisualPropertiesData`、组件级外观、显示状态
- 工程图：视图创建、BOM、尺寸标注、打印/导出 PDF
- 需要 `VARIANT`、by-ref、枚举或 bitmask 的接口

## 查证记录模板

在任务脚本或提交说明中保留最小记录，方便后续沉淀：

```text
API:
资料源:
版本:
签名:
关键参数:
枚举/常量:
返回值:
失败症状:
验证脚本:
是否沉淀到 scripts/references:
```

## 最小验证脚本要求

1. 单独连接 SolidWorks，打印 `sw.RevisionNumber()` 和当前文档类型。
2. 只验证一个新 API，不把它直接混入大任务。
3. 对每个 COM 调用检查 `None` / `False` / 错误码 / 警告码。
4. 生成可打开的 `.SLDPRT` / `.SLDASM` / `.SLDDRW` 或导出文件。
5. 运行 `sw_review.py` 或人工截图复核模型/工程图/装配体是否真的正确。

## 沉淀规则

- 同一 API 第二次用到，优先封装进 `scripts/`。
- 出现兼容问题、错误码、中文版名称差异、选择标记坑位时，补充到对应 `references/*.md`。
- 封装函数应隐藏 COM 长参数细节，暴露稳定、可读、带单位约定的 Python API。
- 文档示例必须是已运行过的写法，不放未经验证的猜测代码。
