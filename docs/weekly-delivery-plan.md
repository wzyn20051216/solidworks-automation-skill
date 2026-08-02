# CAD Studio 周阶段交付计划

每周只承诺可构建、可测试、可回滚的一组能力。未通过真实 CAD 复核的功能继续标为 `pilot`、`reference_only` 或 `not_implemented`。

| 阶段 | 目标 | 验收出口 |
|---|---|---|
| 第 1 周 | 本机安装发现、可靠性诊断、STL/GLB/OBJ/DXF 预览底座 | 两套 CAD 正确识别；Python/Rust/前端测试通过；预览非空像素和窄窗口截图通过 |
| 第 2 周 | 项目/对话/任务/文件/复核模块拆分，减少 `App.tsx` 体积 | 项目切换 P95 < 150 ms；迁移数量一致；项目删除不删 CAD 交付文件 |
| 第 3 周 | SolidWorks 参数修改、批量导出、属性/BOM、Pack and Go | 黄金工作流真实回归；产物账本不接受旧文件 |
| 第 4 周 | 工程图视图/孔标注、AutoCAD 图层/尺寸/图框检查、DXF 图层预览 | DXF 无头检查通过；AutoCAD 2024 ActiveX 原生绘图真机回归当前为 `blocked`，不得伪报通过 |
| 第 5 周 | 装配检查、配置族试点、交付物版本比较和重新生成 | 能力门禁、错误码、重试和人工复核证据完整 |
| 第 6 周 | 20 次稳定性回归、Windows 自托管 CI、安装包回归、v0.4 发布 | 无重复 CAD 实例或遗留 Worker；黄金工作流首轮成功率达到 90% |

## 第 1 周结果

- 已识别本机 `E:\Solidworks\SOLIDWORKS\SLDWORKS.exe` 与 `D:\AutoCAD 2024\acad.exe`；公共桌面快捷方式和 COM 注册纳入统一发现。
- `cad-studio doctor` 输出产品、版本、来源和路径；导出诊断包时路径只保留文件名。
- Three.js 按需加载 STL、GLB/GLTF、OBJ，DXF 只读覆盖 `LINE`、`CIRCLE`、`LWPOLYLINE`。
- STEP/IGES 和 DWG 暂不在浏览器内直接解析，继续由 SolidWorks/AutoCAD 原生导出预览图；不以占位图冒充真实几何。

## 第 2 周结果

- `App.tsx` 从 3968 行降至约 3479 行；项目、任务、对话、复核和交付文件分别进入组件/领域模块，后续 CAD 工作流不再继续堆叠到单文件。
- 左上角项目入口支持项目搜索、归档/恢复、复制项目、重命名和二次确认删除；复制只复制项目元数据与目录引用，不复制任务、对话或 CAD 交付文件。
- 侧栏任务序列支持终态任务批量清理；排队、执行中和待审批任务始终不能被批量删除。
- SQLite 保留旧 `app_state` 快照，同时建立项目、对话、消息和任务实体索引；首次打开自动迁移，`app_store_migration_status` 返回源数据与索引数量是否一致。
- 项目切换在 Playwright 1440×900 / 900×700 验收中无控制台错误，实测 `performance.measure("cad-studio.project-switch")` 为约 18 ms，低于 150 ms 目标。
- 验证结果：前端构建通过，Rust 15 项通过，Python 118 项通过；真实 SolidWorks/AutoCAD 产物能力仍按能力清单和人工复核门禁处理。

## 第 3 周补充结果

- SolidWorks 2024 零件、尺寸修改、属性回读、装配体、BOM 和批量导出已通过真实回归。
- Pack and Go 原生 API 在本机只返回顶层装配体，封装保留为 `pilot`，缺少依赖时返回 `missing_dependencies`，禁止把不完整包标为交付成功。

## 第 4 周补充结果

- DXF 结构审查 schema 2.0 已覆盖实体类型、图层、包围盒、真实 DIMENSION、孔中心/直径、图框和标题栏候选；渲染结果要求 PNG 像素非空。
- AutoCAD 2024 已成功完成 COM 版本识别，但 `Documents.Count`、`Documents.Add`、`Layers` 和 `SelectionSets.Add` 动态代理仍不稳定。原生 DWG 绘图能力在 `capabilities.yaml` 标记为 `not_implemented`，只保留交互排障模式；DXF 无头后端标记为 `pilot`。

## 第 5 周结果

- 装配干涉检查返回 `pass/warn/blocked` 结构化报告，包含数量、条目和人工复核门禁。
- 配置读取试点返回配置清单、当前配置和限制；尚未开放设计表批量修改。
- 交付物使用 SHA-256 快照比较 added/removed/changed/unchanged；重新生成请求保留旧产物、禁止覆盖并要求复核。

## 第 6 周结果

- 新增 `scripts/stability_regression.py`，以 20 次生命周期模拟验证连接、取消和仅退出本次启动实例的约束。
- 新增 `scripts/release_check.py`，发布前校验 UI/Tauri/Cargo 版本一致、能力 ID 唯一和必需文件完整。
- 新增 `.github/workflows/windows-cad-regression.yml`，仅在预装 SolidWorks/AutoCAD 的 Windows 自托管机运行真实回归；公共 GitHub runner 不会伪造 CAD 通过结果。

## 下一阶段四周拓展结果

- 工程图结构审查返回图纸、视图、真实尺寸、表格、图框模板和人工复核字段；BOM 增加模型/工程图/复核报告追溯关系。
- Automation Job 2.0 支持 `drawingEvidence`、`bomEvidence`、`reviewFindings` 和 `artifactRelations`，worker 会根据领域证据正确落为 `blocked`、`failed` 或 `review_required`。
- 交付页按模型、工程图、BOM、预览和复核报告分组显示；旧 Job 1.0 仍按原字段读取。
- AutoCAD 后端状态保持独立：DXF 无头 `pilot`、白名单脚本 `pilot`、COM 当前 `blocked`；.NET SDK 8 已安装到当前用户目录，AutoCAD 2024 白名单插件已通过 `NETLOAD`、真实 DWG 保存重开、PDF/PNG 和实体/图层/尺寸真机复核，因此 .NET 后端提升为 `pilot`。
- .NET 回归只允许 `CADSTUDIOPROBE/CADSTUDIOCREATE` 固定命令，不提供任意 AutoLISP、SCR 或 C# 执行；AutoCAD 2025–2026 和桌面签名插件部署仍需后续验证。
- 新增综合回归 `tests/cad_studio_weekly_regression.py` 和 SolidWorks 工程图真机回归 `tests/solidworks_week4_drawing_regression.py`；真实 CAD 只能显式使用 `--real-cad` 或自托管 CI 运行。

## 后续第 1 阶段结果：版本化重试与交付门禁

- 终态任务重新执行前保存只读 `runHistory` 快照，最多保留最近 20 轮；旧产物、错误、工程图/BOM 证据和复核记录不会在应用内消失，也不会递归复制历史。
- `retryPolicy` 明确记录上一轮 ID、重跑起点、仅执行失败阶段及后继、保留旧产物和禁止覆盖；worker 会复用上一轮工程 DAG，执行 Prompt 同步强制版本化输出。
- 交付中心使用本轮产物、领域证据、人工复核和阻断原因统一判定 `ready/review_required/blocked/failed/incomplete`，不再把文件存在或侧栏“已完成”直接等同于可交付。
- 交付页新增本轮有效产物数、版本记录、SHA-256 变化摘要、产物追溯和 AutoCAD 后端诊断；模型、图纸、BOM 等分组共用一个预览，避免窄窗口重复渲染大预览。
- `ai_team/delivery-gate-e2e.cjs` 在真实 Chromium 中验证 1440×900 待复核状态和 760×900 已批准状态，无横向溢出、无重复预览，并确保只有人工批准后显示“本轮可交付”。

## 第 7–8 周结果：无头几何双后端

- `scripts/headless_occt_service.py` 以独立子进程调用 OCP，真实写入 STEP、IGES、BREP、STL、OBJ、GLB，并回读有效性、体积、包围盒和拓扑统计；当前黄金样例为盒体、圆柱、布尔合并和圆柱孔切除。
- `scripts/headless_cad_writer.py` 保留 `.cadstudio.json`、版本化输出、SHA-256 和 `producedThisRun` 账本；缺少 OCP 或遇到未支持特征时返回 `pilot/blocked`，不写部分网格冒充完整实体。
- 7 项 OCP/开放格式回归和版本化不覆盖回归通过；复杂曲面、钣金、焊件和参数化特征仍未实现。

## 第 9–12 周结果：无头二维写入

- DXF 写入现在包含 `OUTLINE/HOLES/CENTER/DIMENSION/FRAME/TITLE/TEXT` 图层、真实线性/直径 DIMENSION、孔中心线和可选 A4/A3/A2/A1 GB/T 风格图框及标题栏字段。
- SVG、PDF、PNG 默认从同一份 DXF 通过 ezdxf/matplotlib 渲染，依赖缺失时使用明确标注的简化回退；不写入 DWG。
- 10 项二维写入、DXF 审查和 PreviewScene 回归通过；图框布局、中文字体和最终制造性仍需工程师目视复核，能力保持 `pilot`。

## 第 13–16 周结果：JS 预览第一版

- `ModelViewport` 支持 GLB/GLTF/STL/OBJ 的按需 Three.js 加载、标准视图、正交/透视、选择、按需渲染和资源释放；WebGL 不可用或模型解码失败时切换 Manifest 的 PNG 回退。
- `DxfViewport` 使用 Worker 解析 DXF/PreviewScene，支持图层开关、实体选择、尺寸/文字和 Evidence 引用；`.scene.json` 已纳入前端格式路由。
- 真实 Chromium E2E 覆盖桌面、760px 窄窗和 390px 移动窗口，检查 Canvas 像素、无横向溢出、来源标记和回退图；尚未完成 20 MB/30 FPS 的独立性能基准，不宣称达到该指标。

## 第 17–20 周结果：DXF 检视台与演示边界

- 新增 `scripts/dxf_preview_scene.py`，只读白名单解析 LINE/CIRCLE/ARC/LWPOLYLINE/POLYLINE/TEXT/MTEXT/DIMENSION，限制 50 MB 和 200,000 实体；不支持实体只记录 warnings，不执行脚本。
- CLI 新增 `cad-studio preview-dxf`，MCP 新增 `cadstudio_build_dxf_preview_scene`；输出必须是新建 `.scene.json`，拒绝覆盖旧文件。
- 帮助页加入七个固定演示场景（安装板、带孔支架、CPU 外壳、小型装配体、GB/T 图框、FEA 云图示例、Routing 路径示例），全部标记 `demo-showcase/isDemo`，不会进入交付判断。
- E2E 同时验证后端 Scene JSON、原始 DXF Worker、七个演示样例和 WebGL PNG 回退；FEA 云图和 Routing 路径只是教学演示，真实求解/原生 Routing 继续为 `reference_only/not_implemented`。

## 1–20 周审计结论

- 已有真实代码和自动化证据的范围：项目/交付门禁、开放格式几何、基础二维工程图结构、Preview Manifest/Scene、桌面/Skill/CLI/MCP 双入口和浏览器预览回退。
- 仍需真实 CAD 自托管机或人工复核的范围：SolidWorks 工程图/BOM 视觉质量、AutoCAD 原生 DWG、复杂曲面、FEA、Routing，以及 20 MB/30 FPS 性能指标。
- 未通过上述回归的能力不会显示为已完成，也不会被交付门禁当作本轮产物。
