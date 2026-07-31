# CAD Studio 周阶段交付计划

每周只承诺可构建、可测试、可回滚的一组能力。未通过真实 CAD 复核的功能继续标为 `pilot`、`reference_only` 或 `not_implemented`。

| 阶段 | 目标 | 验收出口 |
|---|---|---|
| 第 1 周 | 本机安装发现、可靠性诊断、STL/GLB/OBJ/DXF 预览底座 | 两套 CAD 正确识别；Python/Rust/前端测试通过；预览非空像素和窄窗口截图通过 |
| 第 2 周 | 项目/对话/任务/文件/复核模块拆分，减少 `App.tsx` 体积 | 项目切换 P95 < 150 ms；迁移数量一致；项目删除不删 CAD 交付文件 |
| 第 3 周 | SolidWorks 参数修改、批量导出、属性/BOM、Pack and Go | 黄金工作流真实回归；产物账本不接受旧文件 |
| 第 4 周 | 工程图视图/孔标注、AutoCAD 图层/尺寸/图框检查、DXF 图层预览 | GB/T 图纸目视复核；复杂 DXF 失败时回退原生 PNG |
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
