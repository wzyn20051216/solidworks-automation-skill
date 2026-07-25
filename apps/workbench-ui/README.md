# CAD 自动化交付工作台 UI

这是桌面软件的新一代前端界面原型，目标是替换 PySide6 原型里偏普通的控件观感。

设计方向:

```text
Apple-style 本地工程软件，浅色悬浮窗口、外观中心、本地壁纸导入、右侧 Inspector、清晰 P0 门禁和可执行工作流。
```

当前运行方式是本地 Vite 预览。后续可以嵌入 Tauri、Electron 或 PySide WebEngine。

当前界面包含:

- 右上角外观浮层，支持导入本地图片、GIF、视频壁纸，并可调节亮度、模糊和暗角。
- 4 套默认壁纸: Aurora、Blueprint、Studio、Mist。
- macOS 风格窗口栏、浅色 Dock 导航、项目工作台和右侧 Inspector 参数面板。
- 按钮 hover、按压反馈和主按钮光泽扫过效果。
- 桌面与移动端响应式预览截图。

桌面化目标:

- Tauri / Electron 外壳承载当前 React UI。
- 本地配置持久化，保存最近壁纸、外观参数和用户项目路径。
- 接入真实 SolidWorks / AutoCAD 自动化队列。
- 支持离线运行、系统托盘、任务通知和导出目录管理。

## 安装

```powershell
cd apps\workbench-ui
npm install
```

## 开发预览

```powershell
npm run dev
```

## 构建

```powershell
npm run build
```
