# 第 1 周：JS CAD 预览调研

调研日期：2026-07-31。数据来自 GitHub REST 仓库公开元数据，Stars/Forks 会随时间变化。

| 项目 | Stars | Forks | 许可证 | 适合用途 | 本周结论 |
|---|---:|---:|---|---|---|
| [three.js](https://github.com/mrdoob/three.js) | 114,133 | 36,455 | MIT | WebGL 场景、GLTF/STL/OBJ Loader、交互控制 | 作为 CAD Studio 预览底座 |
| [Online3DViewer](https://github.com/kovacsv/Online3DViewer) | 3,617 | 759 | MIT | 多格式浏览器查看器，支持 STEP/IGES/STL/OBJ 等 | 后续评估其格式适配和 UI 能力 |
| [replicad](https://github.com/sgenoud/replicad) | 661 | 78 | MIT | 浏览器 OpenCascade 参数化建模 | 作为未来浏览器端参数化实验参考，不进入本周运行时 |
| [three-cad-viewer](https://github.com/bernhard-42/three-cad-viewer) | 380 | 65 | MIT | 基于 Three.js 的 CAD Viewer 组件 | 参考树结构、选择与相机交互 |
| [occt-import-js](https://github.com/kovacsv/occt-import-js) | 278 | 54 | LGPL-2.1 | OpenCascade WASM 导入 STEP/IGES/BREP | 暂不直接并入 MIT 主包，先做隔离进程/许可证评估 |
| [ThatOpen/engine_components](https://github.com/ThatOpen/engine_components) | 691 | 204 | MIT | BIM/IFC 组件和 3D 引擎 | 与机械 CAD 目标不完全匹配，暂不引入 |

## 本周实现边界

- SolidWorks 产物优先显示 STL、GLB/GLTF、OBJ；Three.js Loader 使用动态导入，避免首屏阻塞。
- DXF 使用浏览器只读解析回退，覆盖 `LINE`、`CIRCLE` 和 `LWPOLYLINE`，解析失败明确显示错误，不伪造 CAD 成功。
- STEP/IGES、DWG 的真实几何预览仍以原生 SolidWorks/AutoCAD 导出 PNG 或网格产物为准；不把线框占位图当作实体预览。
- 本地路径仅通过 Tauri `convertFileSrc` 访问；诊断包仍脱敏，不上传 CAD 文件、Prompt 或密钥。

## 后续评估

1. 用独立 Worker 评估 `occt-import-js` 的 LGPL 组合方式，完成法务和发布包体积检查后再决定是否支持 STEP 浏览器预览。
2. 对比 Online3DViewer 与当前 Three.js 组件的大模型加载时间、内存和移动窗口交互。
3. 增加 DXF 图层、尺寸和图框结构化显示；复杂实体回退到 AutoCAD 原生 BMP/PNG 预览。
