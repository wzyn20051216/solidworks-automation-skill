# CAD 自动化交付工作台 UI

这是桌面软件的新一代前端界面原型，目标是替换 PySide6 原型里偏普通的控件观感。

设计方向:

```text
Apple-style 本地工程软件，浅色悬浮窗口、外观中心、本地壁纸导入、右侧 Inspector、清晰 P0 门禁和可执行工作流。
```

当前运行方式支持两种:

- Vite 浏览器预览，用于快速调 UI。
- Tauri 桌面软件，用于生成 Windows `.exe`。

当前界面包含:

- 右上角外观浮层，支持导入本地图片、GIF、视频壁纸，并可调节亮度、模糊和暗角。
- 本地配置持久化，自动记住当前壁纸、最近壁纸、亮度、模糊、暗角和最近导入模型路径。
- 4 套默认壁纸: Aurora、Blueprint、Studio、Mist。
- macOS 风格窗口栏、浅色 Dock 导航、项目工作台和右侧 Inspector 参数面板。
- 按钮 hover、按压反馈和主按钮光泽扫过效果。
- 桌面与移动端响应式预览截图。

桌面化目标:

- Tauri 外壳承载当前 React UI。
- 接入真实 SolidWorks / AutoCAD 自动化队列。
- 支持离线运行、系统托盘、任务通知和导出目录管理。

说明:

- 浏览器预览模式只能临时预览用户导入的本地图片，因为浏览器刷新后无法重新访问原文件路径。
- Tauri 桌面模式会使用原生文件选择器，能保存本地文件路径并在下次启动时恢复壁纸。

## 安装

```powershell
cd apps\workbench-ui
npm install
```

## 开发预览

```powershell
npm run dev
```

## 桌面开发

```powershell
npm run desktop:dev
```

## 构建

```powershell
npm run build
```

## 生成桌面程序

```powershell
npm run desktop:build
```

该命令会生成可运行 `.exe`，暂不打安装包。

如需生成安装包:

```powershell
npm run desktop:bundle
```

输出程序:

```text
apps\workbench-ui\src-tauri\target\release\cad-studio.exe
```
