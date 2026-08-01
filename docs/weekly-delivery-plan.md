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
