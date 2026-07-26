# CAD Studio 桌面工作台

这是 CAD Studio 的正式 React + Tauri 桌面客户端。

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
- 本地自动化队列，桌面端把新建 CAD 任务、导入模型、生成交付包任务保存为 JSON。
- Agent Bridge 面板，把图形化配置转换为 Codex、Claude Code、Gemini CLI 或 OpenCode 可执行任务。
- CC Switch 同步读取当前用户的 SQLite/旧版 JSON 配置，按所选 Agent 显示模型路由，不读取或展示密钥。
- 默认 `AI 自动选择最佳方案`，用户不指定时自动判断任务类型、工艺、材料、输出格式和检查项。
- Policy Gate 审批门禁，危险任务会先进入待审批状态。
- Artifact Ledger 交付物账本，记录输出文件存在性、大小和 SHA-256。
- 队列面板可在桌面端启动/停止本地 Python worker，并显示运行状态和 PID。
- Worker Health 健康心跳和 Reviewer Gate 交付物/格式特征复核。
- 待复核任务支持人工“通过复核/驳回”，并记录复核人、时间、结论和审计事件。
- 默认樱花动态壁纸（已移除音轨和定位元数据），另有 Aurora、Blueprint、Studio、Mist；支持任意本地图片/GIF/视频导入与切换。
- 本地优先专业知识库：自动检索 SolidWorks、制造和图纸规范；可添加企业标准目录。
- 可选 HTTPS 云 RAG：仅在显式启用并通过外部网络审批后调用，令牌只从环境变量读取。
- macOS 风格窗口栏、浅色 Dock 导航、项目工作台和右侧 Inspector 参数面板。
- 按钮 hover、按压反馈和主按钮光泽扫过效果。
- 桌面与移动端响应式预览截图。

发布版安装包会内置 skill、Python worker 和机械知识文档。用户仍需安装 Python、至少一个 Agent CLI，以及真实操作所需的 SolidWorks/AutoCAD。

完整用户说明：[CAD Studio 用户说明书](../../docs/CAD_STUDIO_USER_MANUAL.md)。

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

正式桌面启动启用统一 Agent handler，不加载 mock。`create_shell`、`import_model`、`delivery_package` 的 mock 仅能通过 `--enable-mock` 显式开启，用于队列协议开发测试，不能作为产品交付结果。

启用统一 Agent 执行器：

```powershell
python -m apps.desktop.cad_workbench.queue_worker --watch --enable-codex --queue-dir "<队列目录>"
```

桌面端可以直接在“设置 -> 本地执行”点击启动。开发版优先使用当前仓库，安装版使用内置 skill 资源。点击停止会终止软件托管的 worker 进程树，并把未完成任务重新排队；Alt+F4 和系统退出执行同样清理。

Agent Bridge 的职责边界:

- UI 负责收集点击配置、工程规则、目标输出和 prompt 预览。
- 队列负责把任务持久化为 JSON，并通过 `.lock`、lease、stale 恢复、quarantine、Worker Health、Artifact Ledger 和 Reviewer Gate 保证本地可靠执行。
- worker 负责校验任务、执行 Policy Gate、限制工作区、固定输出路径并调用 `codex exec`。
- 所选 Agent 负责执行 skill、调用本机 CAD、运行验证并返回统一结构化结果。

危险能力会进入 `approval_required`，包括 Git push、`danger-full-access`、CAD 宏、外部网络、跨工作区写入和删除文件。桌面端点击“批准”后，任务才会回到 `queued`。

默认 Codex 沙箱为 `workspace-write`。如确需全权限，需要任务先通过审批，并在 worker 启动时显式增加:

```powershell
python -m apps.desktop.cad_workbench.queue_worker --watch --enable-codex --codex-full-access --queue-dir "<队列目录>"
```

企业控制平面说明:

```text
docs\agent-framework\enterprise-agent-control-plane.md
```
