# CAD Studio 用户说明书

本文面向第一次使用 CAD Studio 的机械工程师、学生和设计人员。CAD Studio 与 Skill/CLI/MCP 是平级入口，共用 CAD Core、任务协议、能力清单和证据系统；用户不安装桌面软件也可以直接运行 Skill/CLI/MCP。工程文件和任务记录默认保存在本机。

## 1. 软件能做什么

- 从自然语言规划并创建基础零件、外壳、夹具和装配体；钣金等未验证能力按能力清单进入人工复核或阻断。
- 修改已有 SLDPRT、SLDASM、STEP、STL、DWG、DXF、PDF 或参考图片。
- 创建通孔、盲孔、沉孔、沉头孔、螺纹孔、长圆孔、半圆槽和阵列孔。
- 无 CAD 软件时输出 `.cadstudio.json`、STL、OBJ、DXF、SVG、PDF、PNG 和复核报告；原生 SLDPRT/SLDASM/SLDDRW/DWG 需要对应 CAD 软件和已验证后端。
- 自动选择 CAD 软件、材料、工艺和执行阶段，也允许用户手动指定。
- 对综合工程执行“需求分析 -> 方案 -> 零件 -> 装配 -> 运动/干涉 -> 图纸 -> 交付”编排。
- 通过人工审批和复核门禁，避免未经确认直接控制桌面 CAD 或交付错误文件。

## 2. 系统要求

### 2.1 软件本体

- Windows 10 22H2 或 Windows 11，64 位。
- Microsoft Edge WebView2 Runtime。Windows 10/11 通常已内置；缺失时安装包会提示。
- 建议 8 GB 内存，复杂装配建议 16 GB 或更多。

### 2.2 执行 AI

至少安装并登录以下一种 CLI：

- Codex CLI
- Claude Code
- Gemini CLI
- OpenCode

CAD Studio 不附带模型额度，也不保存 API Key。模型账号、套餐、代理和路由由对应 CLI 或 CC Switch 管理。

首次安装可参考下表。使用 npm 安装前需先安装 Node.js 20 或更高版本；企业电脑无法执行全局安装时，请联系管理员或使用各项目的官方安装器。

| Agent | 官方说明 | 常用安装方式 | 检查命令 |
| --- | --- | --- | --- |
| Codex CLI | <https://developers.openai.com/codex/cli/> | `npm install -g @openai/codex` | `codex --version`、`codex login status` |
| Claude Code | <https://docs.anthropic.com/en/docs/claude-code/setup> | 按官方 Windows 安装器或 PowerShell 指引安装 | `claude --version`，再运行 `claude` 完成登录 |
| Gemini CLI | <https://github.com/google-gemini/gemini-cli> | `npm install -g @google/gemini-cli` | `gemini --version`，再运行 `gemini` 完成登录 |
| OpenCode | <https://opencode.ai/docs/> | `npm install -g opencode-ai` | `opencode --version`、`opencode auth login` |

安装后请关闭并重新打开 CAD Studio。若 PowerShell 能运行检查命令、软件仍检测不到，检查 npm 全局目录是否已加入当前用户 `PATH`；也可在系统环境变量中设置 `CODEX_BIN`、`CLAUDE_BIN`、`GEMINI_BIN` 或 `OPENCODE_BIN` 为对应可执行文件的完整路径。

### 2.3 真实 CAD 自动化

- Python 3.8 或更高版本，推荐 64 位 Python 3.11/3.12。
- Python 依赖：`pywin32`、`comtypes`。
- 当前真机基线为 SolidWorks 2024、SolidWorks 2026 SP01.1 和 AutoCAD 2024；SolidWorks 2026 仅对 `capabilities.yaml` 中明确列出 2026 的能力视为已验证，SolidWorks 2025 和其余能力仍是兼容性目标。
- Python、SolidWorks 和 AutoCAD 应与操作系统保持 64 位一致。

安装 Python 依赖：

```powershell
python -m pip install "pywin32>=305" "comtypes>=1.2.0"
```

### 2.4 无 CAD 软件开放格式后端

没有安装 SolidWorks/AutoCAD 时，不再只停留在需求整理和脚本生成。当前无头后端可以从 NeutralCadDocument 真实写出 `.cadstudio.json`、STEP、IGES、BREP、STL、OBJ、GLB、DXF、SVG、PDF、PNG，并生成几何证据、Preview Manifest、回退图片和 SHA-256：

```powershell
python scripts\cad_studio.py write-open-format `
  --input .\part.cadstudio.json `
  --out-dir .\output `
  --formats cadstudio step iges brep stl obj glb dxf svg pdf png
```

已有 DXF 可单独生成浏览器预览场景：

```powershell
python scripts\cad_studio.py preview-dxf `
  --input .\drawing.dxf `
  --output .\output\drawing.scene.json
```

该转换只读取 LINE、CIRCLE、ARC、LWPOLYLINE、POLYLINE、TEXT、MTEXT 和 DIMENSION，输入上限为 50 MB/200000 个实体；不支持实体会写入限制，不会执行脚本或覆盖旧场景文件。

OCCT 当前覆盖盒体、圆柱、布尔合并和圆柱孔切除，回读实体有效性、体积、包围盒和拓扑数量；复杂特征仍返回 `blocked`。原生 SLDPRT/SLDASM/SLDDRW/DWG 缺少厂商软件或授权 SDK 时必须返回 `blocked`，不能通过改扩展名伪造。

首次执行前建议运行：

```powershell
python scripts/cad_studio.py doctor
```

能力限制以仓库根目录 `capabilities.yaml` 为准。配置/设计表、钣金、焊件、Simulation/FEA 和 Routing 当前不会被标记为已交付；任务会进入“已阻断”并给出原因，除非明确选择人工复核模式。

工程图和 BOM 任务会额外返回视图、真实尺寸、BOM 行、模型/工程图关系和复核发现。SW2024 与 SW2026 SP01.1 中“模型尺寸自动插入并回读真实尺寸实体”已作为独立能力验证；SW2026 回归连续三次读取到 3 个真实视图和 6 个真实尺寸实体。完整工程图仍为 `pilot`，文件存在不等于交付完成，图幅、视图布局、尺寸链、孔表、标题栏和 BOM 仍需人工复核。

AutoCAD 后端分为 DXF 无头检查、白名单命令桥、COM 和 .NET。当前本机 AutoCAD 2024 的 COM 代理仍不稳定；独立的 .NET 后端已用本机 Managed API 连续完成白名单真机回归，可创建并重开真实 DWG，生成 PDF/PNG，并回读图元、图层和真实尺寸。前置检查会复验最近三次报告及产物哈希，完整时返回 `verified`，证据损坏时自动降级；这不代表任意 DWG 操作或任意插件代码均可用。可运行：

```powershell
python subskills\autocad-automation\scripts\acad_dotnet_preflight.py
python subskills\autocad-automation\scripts\acad_dotnet_regression.py
python subskills\autocad-automation\scripts\acad_dotnet_regression.py --real-cad
```

只有明确授权时才使用 `--install-sdk`；该操作会通过官方 Microsoft 安装源安装 .NET SDK，不会下载 Autodesk 专有 DLL。若系统 PATH 中的 `dotnet.exe` 只有运行时，检查器会继续探测当前用户目录中的真实 SDK。桌面 AutoCAD 加载未签名插件时仍需配置受信任路径或使用签名插件包；真机回归会先读取 `SECURELOAD/FILEDIA/BACKGROUNDPLOT` 原值，只在独占 Core Console 中临时调整，并在退出前恢复。

## 3. 安装与启动

### 安装版

1. 从 GitHub Releases 下载 `CAD-Studio-<版本>-Setup-x64.exe`。
2. 双击安装，按提示完成。
3. 从开始菜单启动 CAD Studio。

安装目录中的程序文件名为 `cad-studio.exe`；日常使用不需要手动进入安装目录。

### 便携版

1. 下载 `CAD-Studio-<版本>-Windows-x64-Portable.zip`。
2. 完整解压到一个可写目录。
3. 运行目录中的 `CAD Studio.exe`。
4. 不要只移动 exe；同目录 `skill` 资源是本地执行器的一部分。

Windows SmartScreen 可能提示“未知发布者”，因为当前开源构建未购买商业代码签名证书。可先核对 Release 页面 SHA-256，再选择运行。

## 4. 第一次使用

1. 打开顶部“帮助”，查看环境状态。
2. 进入“设置”，选择本机已安装的 Agent。
3. 使用 CC Switch 时，点击“读取 CC Switch 状态”。软件读取当前用户目录中的 CC Switch SQLite/JSON 配置，只返回路由名称、模型、端点和托管状态，不返回密钥。
4. 点击“选择输出文件夹”，创建一个独立项目目录。
5. 需要真实 CAD 操作时安装 Python 依赖，并启动 SolidWorks 或 AutoCAD。
6. 点击“启动本地执行器”。看到运行中和 PID 后即可提交任务。

## 5. 创建第一个模型

### 从零建模

1. 点击左侧“新建任务”或顶部“建模”。
2. 选择“通用零件”“装配体”“外壳”等模板。
3. 在目标框中输入完整需求，例如：

```text
创建一块 120 x 80 x 8 mm 的 6061 铝安装板。
四角各有一个直径 6.6 mm 通孔，孔中心距相邻边均为 10 mm。
上表面中心制作一个直径 20 mm、深 4 mm 的沉孔。
四周倒角 1 x 45 度。
输出 SLDPRT、STEP、PDF 工程图和四视角 PNG，保存到当前输出目录。
```

4. 未指定软件、材料或工艺时保留“AI 自动选择”。
5. 涉及孔槽时保持“真实开孔/切除”开启。
6. 需要操作 CAD 时开启“本机 CAD 自动化”。
7. 检查右侧执行计划，点击“交给当前 AI 执行”。
8. 危险能力出现审批提示时，核对原因后点击批准。

### 修改已有文件

1. 点击顶部“导入”。
2. 选择 CAD、图纸或参考图片。
3. 在对话框说明需要保留和修改的内容。
4. 明确要求另存新文件，避免覆盖原始工程。

## 6. 综合工程怎么用

装配、运动、图纸和交付同时存在时，不需要拆成多个互不相关的任务。直接描述最终目标，软件会创建阶段化工程计划：

1. 需求和约束提取。
2. CAD 软件与 skill 路由。
3. 零件建模和关键特征。
4. 装配关系与干涉检查。
5. Motion Study 或运动验证。
6. GB/T 工程图、BOM 和公差。
7. 格式导出、产物账本和人工复核。

后续对话只需说“把 M6 改成 M8，其他尺寸不变”之类的局部修改。系统会恢复上一次计划，只重跑受影响阶段及其下游。

失败、阻断、取消或待复核任务也可以从交付中心局部重新生成。软件会在清空本轮运行字段前，把上一轮状态、产物账本、工程图/BOM 证据、复核门禁和错误保存为只读版本快照；默认最多保留最近 20 轮任务元数据。重跑策略要求从失败阶段及其后继执行，并强制新产物使用新版本目录或文件名。历史快照只保存路径、大小、哈希和复核证据，不复制 CAD 文件内容，也不会删除旧交付文件。

关键尺寸、公差、载荷、材料强度和安全相关参数缺失时，AI 应询问或将结果标记为概念方案，不能擅自当作可制造定稿。

## 7. 页面说明

- 左侧任务列表：当前项目的历史任务。标题来自用户目标；旧版本显示“Codex 执行”只是历史内部标题，不代表固定使用 Codex。
- 总览：创建任务、导入参考文件、查看当前环境。
- 建模：零件、装配、治具、钣金、外壳、逆向等任务模板。
- 特征：孔、槽、螺纹、接口开口和阵列。
- 图纸：GB/T 图纸、公差、BOM 和格式转换。
- 复核：检查原生打开、尺寸、特征、产物和风险。
- 交付：统一判断“可交付 / 待人工复核 / 阻断 / 证据不完整”，展示本轮产物、历史版本、产物关系和后端诊断；STL、GLB/GLTF、OBJ 可旋转缩放，DXF 和图片可只读预览。只有机器证据完整并满足人工复核门禁后才显示“本轮可交付”。
- 设置：AI、CC Switch、本地执行器、输出和知识库。
- 帮助：首次使用步骤和环境状态。

## 8. Agent 与 CC Switch

“Agent”与“模型路由”是两层概念：

- Agent CLI 决定由 Codex、Claude Code、Gemini CLI 或 OpenCode 执行任务。
- CC Switch 路由决定该 CLI 使用哪个模型供应商、端点和模型。

选择 Claude Code 后，执行按钮、Executor 和路由列表都会切换为 Claude；同步 CC Switch 不会再自动切回 Codex。

CC Switch 不是必需依赖。不使用它时，CAD Studio 直接沿用所选 CLI 的本机登录态和配置。

## 9. 审批与复核

以下行为需要人工审批：

- 控制 SolidWorks / AutoCAD 桌面会话。
- 访问项目目录之外的文件。
- 使用外部网络或云知识库。
- 全权限沙箱、删除文件或 Git 推送。

完成任务后至少检查：

- 文件能在目标 CAD 软件原生打开。
- 关键尺寸、公差、基准和孔位定位正确。
- 孔槽为真实几何特征，不只是草图或标注。
- 装配配合、干涉和运动方向正确。
- 本轮输出文件存在、时间和版本正确。

只有填写复核说明并完成全部检查项后，任务才能标记为通过。

## 10. 文件保存与隐私

- 默认输出：当前用户 `Documents/CADAutomationWorkbench`。
- 队列和设置：当前用户应用数据目录 `com.wzyn.cadstudio`。
- 壁纸、项目路径、任务事件和交付物账本保存在本机。
- API Key 不写入 CAD Studio 设置或任务文件。
- 只有显式开启云 RAG 或所选 AI CLI 本身访问网络时，工程上下文才可能离开本机。

不要把包含公司机密的队列目录、日志和任务 JSON 直接上传到公开 Issue。

## 11. 常见问题

### “未检测到 Agent Provider”

确认 CLI 能在 PowerShell 中执行 `--version`，然后重启 CAD Studio。高级用户可通过 `CODEX_BIN`、`CLAUDE_BIN`、`GEMINI_BIN`、`OPENCODE_BIN` 指定可执行文件。

### “Python 未安装”

安装 64 位 Python 3，并在安装器中勾选 Add Python to PATH。重启软件后再启动本地执行器。

### “SolidWorks / AutoCAD 未检测到”

确认软件已正确安装；SolidWorks 自动化前建议先手动启动一次。CAD Studio 会综合检查 COM 注册、公共桌面快捷方式、标准目录以及 `D:`/`E:` 常见安装目录。检测到“已安装但未运行”不等于安装失败，可手动启动软件后重新检查。

### CC Switch 没有显示全部模型

先升级到较新 CC Switch，并确认配置已保存。CAD Studio 支持 `~/.cc-switch/cc-switch.db` 和旧版 `config.json`。

### 任务一直待审批

打开任务详情查看审批原因。只有用户主动批准后，本地执行器才会继续。

### 左侧为什么有很多任务

左侧是历史任务，不是功能菜单。可点击任务查看状态和结果。它们保存在本机队列目录，删除应用数据会清空历史，请先备份需要的交付物。

## 12. 获取帮助和反馈

提交 GitHub Issue 时请提供：

- CAD Studio 版本和安装方式。
- Windows、Python、SolidWorks/AutoCAD、Agent CLI 版本。
- 可复现步骤和脱敏后的错误消息。
- 是否使用 CC Switch，以及路由类型；不要提交 API Key。

项目地址：<https://github.com/wzyn20051216/solidworks-automation-skill>
