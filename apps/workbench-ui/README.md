# CAD 自动化交付工作台 UI

这是桌面软件的新一代前端界面原型，目标是替换 PySide6 原型里偏普通的控件观感。

设计方向:

```text
Apple-style 本地工程软件，浅色悬浮窗口、动态壁纸切换、柔和按钮动效、清晰 P0 门禁和可执行工作流。
```

当前运行方式是本地 Vite 预览。后续可以嵌入 Tauri、Electron 或 PySide WebEngine。

当前界面包含:

- 4 套可切换动态壁纸: Aurora、Blueprint、Studio、Mist。
- macOS 风格窗口栏、浅色 Dock 导航和玻璃材质主面板。
- 按钮 hover、按压反馈和主按钮光泽扫过效果。
- 桌面与移动端响应式预览截图。

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
