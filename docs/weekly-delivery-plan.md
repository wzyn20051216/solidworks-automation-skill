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
