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
- 本地自动化队列，桌面端把新建外壳、导入模型、生成交付包任务保存为 JSON。
- Codex Bridge 面板，把图形化配置转换为 `codex exec` 可执行任务。
- Policy Gate 审批门禁，危险任务会先进入待审批状态。
- Artifact Ledger 交付物账本，记录输出文件存在性、大小和 SHA-256。
- 4 套默认壁纸: Aurora、Blueprint、Studio、Mist。
- macOS 风格窗口栏、浅色 Dock 导航、项目工作台和右侧 Inspector 参数面板。
- 按钮 hover、按压反馈和主按钮光泽扫过效果。
- 桌面与移动端响应式预览截图。

桌面化目标:

- Tauri 外壳承载当前 React UI。
- 接入真实 SolidWorks / AutoCAD 自动化执行器。
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

## 本地自动化队列

协议文档:

```text
apps\workbench-ui\docs\automation-queue-protocol.md
```

桌面端任务保存到 Tauri 应用数据目录的 `queue` 文件夹。Python worker 原型:

```powershell
python -m apps.desktop.cad_workbench.queue_worker --queue-dir "<队列目录>"
```

持续监听:

```powershell
python -m apps.desktop.cad_workbench.queue_worker --watch --queue-dir "<队列目录>"
```

当前 worker 使用 mock handler，只验证任务流转和文件回写。后续真实接入时替换 `create_shell`、`import_model`、`delivery_package` 三类 handler。

启用 Codex 执行器:

```powershell
python -m apps.desktop.cad_workbench.queue_worker --watch --enable-codex --queue-dir "<队列目录>"
```

Codex Bridge 的职责边界:

- UI 负责收集点击配置、工程规则、目标输出和 prompt 预览。
- 队列负责把任务持久化为 JSON，并通过 `.lock`、lease、stale 恢复、quarantine 和 Artifact Ledger 保证本地可靠执行。
- worker 负责校验任务、执行 Policy Gate、限制工作区、固定输出路径并调用 `codex exec`。
- Codex 负责真正执行 skill、修改文件、运行验证、提交和推送。

危险能力会进入 `approval_required`，包括 Git push、`danger-full-access`、CAD 宏、外部网络、跨工作区写入和删除文件。桌面端点击“批准”后，任务才会回到 `queued`。

默认 Codex 沙箱为 `workspace-write`。如确需全权限，需要任务先通过审批，并在 worker 启动时显式增加:

```powershell
python -m apps.desktop.cad_workbench.queue_worker --watch --enable-codex --codex-full-access --queue-dir "<队列目录>"
```

企业控制平面说明:

```text
docs\agent-framework\enterprise-agent-control-plane.md
```
