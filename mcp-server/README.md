# SolidWorks MCP Server

本目录提供一个本地 MCP Server，同时暴露无 CAD 开放格式工具和 SolidWorks COM 白名单工具。MCP 与 CAD Studio、Skill、CLI 共用能力清单和数据协议。

SolidWorks 是 Windows 桌面 COM 应用，不适合远程多客户端并发；因此本 server 默认使用 `stdio`，并在内部用全局锁串行执行所有 SolidWorks 操作。

除 `stdio` 外，还可用 `--transport streamable-http` 把同一套工具以 HTTP 方式暴露，供**不在同一台机器上**的 MCP 客户端连接（例如 Linux 上的 agent 远程驱动 Windows 上的 SolidWorks）。此时全局串行锁依然生效，请仍然只接一个客户端。

## 环境要求

- Windows 10/11
- 仅调用 `cadstudio_write_open_format` 时不需要安装 SolidWorks/AutoCAD
- 原生 SolidWorks 操作以 SolidWorks 2026 为支持与验收目标；安装后至少启动一次，完成 COM 注册
- Python 3.10+
- Python 依赖：

```powershell
pip install -r mcp-server\requirements.txt
```

## 启动

在仓库根目录运行：

```powershell
python mcp-server\server.py
```

该命令通常由 MCP 客户端作为子进程启动，不需要手动长期运行。

## 工具发现模式（默认）

默认 `SW_MCP_DISCOVERY=search`：`tools/list` 只暴露三个发现入口，69 个原生工具可按需检索。
默认信任客户端已取得当前任务授权，任务内调用不再逐次请求服务端批准；需要更严格控制时
可启用 `server` 模式。初始工具列表体积可通过
`python -m pytest -q tests/test_mcp_discovery_quality.py` 验证。

| 入口 | 作用 |
| --- | --- |
| `sw_search_tools` | 按中英文说法检索候选，返回名称、说明、相关度和副作用等级；不执行操作 |
| `sw_describe_tool` | 读取单个工具的完整输入 Schema、副作用等级和是否需要人工批准 |
| `sw_call_tool` | 按名称执行；经过策略检查，审批行为取决于所选模式及其信任边界 |

直接点名调用被隐藏的原生工具同样会经过网关，未知工具一律拒绝。

需要客户端逐工具展示权限提示时，用 `SW_MCP_DISCOVERY=full` 显示全部 69 个命名工具。
两种模式共用同一套执行检查；`stdio` 和 `--transport streamable-http` 行为一致。

### 环境变量

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `SW_MCP_DISCOVERY` | `search` | `search` 发现模式；`full` 原生命名工具 |
| `SW_MCP_APPROVAL` | `auto` | `auto`：发现模式用 `task`、完整模式用 `client`；`task`：信任客户端的任务授权，不逐次确认；`server`：本地逐次审批账本；`client`：交给客户端逐工具审批，仅允许完整模式；`elicit`：走 MCP elicitation（可能被 agent 自动应答）；`off`：关闭服务端审批 |
| `SW_MCP_APPROVAL_DIR` | `%LOCALAPPDATA%\SolidWorksMCP\approvals` | 审批账本目录 |
| `SW_API_LOOKUP_NETWORK` | `on` | 设置 `off` 禁止本项目 API 查证访问官方文档；不控制客户端自己的搜索 |
| `SW_API_LOOKUP_AUTO_INSTALL` | `on` | 设置 `off` 禁止 API 查证自动安装依赖和恢复帮助文件 |
| `SW_AUTO_INSTALL_DEPENDENCIES` | `on` | 设置 `off` 禁止基础 COM 预检和桌面执行器自动安装依赖 |

`solidworks_lookup_api` 支持 `interface` + `member` 或自然语言 `task`，按目标版本查证本机类型库、API Help 和官方文档；直读失败且无缓存时使用匿名 Parallel，仅发送公开版本、接口、成员及官方链接。默认按需自动配置依赖，MCP 注解因此标记为可能修改环境；`auto_install=false` 禁用安装，`offline=true` 禁用联网和安装。服务端会按参数区分副作用，用户配置的服务端审批模式仍然生效。结果区分版本证据、来源和获取时间，不能代替真机验证。多个目标无法确定时不会猜测或启动 SolidWorks。`solidworks_connect` 支持可选 `version` 年份并检查实际连接版本。

### 任务授权和可选逐次审批

默认 `task` 模式由客户端或用户负责界定任务授权；MCP 服务端**不能验证**客户端是否实际
询问过用户，不提供逐工具权限隔离。服务端仍会拒绝未登记的工具，并沿用参数校验、
目标限制与 SolidWorks 串行执行；具备相同本机权限的进程可以绕过本服务。

已保存文档的活动文档操作可选传入 `document_target`（绝对 `path` 和 `process_id`），
服务端将核对目标；不传时沿用工具原有的活动文档行为，以支持未保存文档和现有工作流。

以下是显式选择 `SW_MCP_APPROVAL=server` 时的逐次审批机制。

**信任边界：**审批账本和命令行运行在同一操作系统用户权限下。TTY 检查不能证明
输入来自真人：具有该用户权限的进程可能模拟终端或直接访问账本和签名密钥。因此，
账本适用于可信本地环境中的操作确认，不是隔离同用户 Agent 或恶意进程的安全边界。
需要可靠逐操作的人审时，应使用经过验证的可信客户端/独立审批机制；`client`、
`elicit` 和 `off` 模式也不能单凭配置名称保证存在人工确认。

工具可能使用活动文档、间接路径或输入文件中的引用。目前范围授权已停用，旧范围授权也不会
被消费。`server` / `elicit` 模式下，支持绑定的活动文档操作必须经 `sw_call_tool` 提供
`document_target`，包含已保存文档的绝对 `path` 和 SolidWorks `process_id`。例如先使用
`solidworks_connect` 读取 `process_id` 与 `document.path`，再把两者放进 `document_target`；
服务端将目标与参数一起展示并绑定到批准，在持锁获取活动文档时复核 PID 和路径。

未保存的文档、关闭文档、文档单位设置、添加组件、模型审查、Pack and Go 及原生子进程
操作暂不支持此绑定并保持阻止。PID 和路径用于定位，
不能证明文档内容或外部引用未变化，也不能隔离具有相同系统用户权限的进程。`full` +
`client` 或 `off` 保持原有客户端控制，但服务端不保证其审批有效。本机制尚未完成真实
SolidWorks 的目标切换验证，不应将其当作已验收的安全边界。

模型传入 `approved: true` 或类似参数不会生效。写操作被阻止时，返回内容会给出审批请求 ID，
需要在能访问本机的终端执行：

```powershell
python scripts\sw_mcp_approve.py list
python scripts\sw_mcp_approve.py approve <请求ID>
```

批准与「工具 + 完整参数摘要 + 服务端会话 + 有效期」绑定，一次性使用（默认 15 分钟）；
参数改变、服务端重启或更换会话后需重新请求批准。显式路径包含在参数中，但不代表
已校验输入文件内容、隐式引用或文档状态；不能将该机制用于不可信环境。
请求记录和授权记录各有 1000 条上限；达到上限时服务端安全拒绝新增记录，不自动删除
历史文件。用户需确认记录归属后自行备份和归档，才能继续使用审批。

### 回滚到旧行为

在 MCP 客户端配置里给 server 进程加环境变量：

```jsonc
{
  "command": "python",
  "args": ["C:\\path\\to\\mcp-server\\server.py"],
  "env": { "SW_MCP_DISCOVERY": "full", "SW_MCP_APPROVAL": "client" }
}
```

即恢复全部原生工具可见，并由客户端决定是否逐工具审批。不改环境变量、仅升级版本的客户端默认使用发现模式。

### 协议验证

```powershell
python scripts\validate_mcp.py            # 同时校验 full 和 search
python scripts\validate_mcp.py --mode search
```

发现模式校验会确认 3 个入口可见、每个必需工具都能按名称检索并读到 Schema；完整模式校验
69 个工具全部可见。

## HTTP 传输（streamable-http）

当 MCP 客户端与 SolidWorks 不在同一台机器上时（例如 Linux 上的 agent 驱动 Windows 上的 SolidWorks），无法让客户端直接拉起本机的 stdio 子进程，此时改用 HTTP 传输：

```powershell
python -m pip install uvicorn
$env:SW_MCP_TOKEN = "<替换为随机共享密钥>"
python mcp-server\server.py --transport streamable-http --host 0.0.0.0 --port 8000 `
  --allow-host "192.168.1.10:*" --output-root "C:\cad-output"
```

- 端点：`http://<本机IP>:8000/mcp`（Streamable HTTP，FastMCP 默认路径 `/mcp`）
- `--host` 默认 `127.0.0.1`；局域网访问需显式传 `0.0.0.0`，并放行对应端口的防火墙
- `--port` 默认 `8000`
- 也可用环境变量 `SW_MCP_HOST` / `SW_MCP_PORT` 提供默认值，命令行参数优先
- **`uvicorn` 是可选依赖**：仅在 `--transport streamable-http` 时需要；缺失时会给出明确提示
- 默认值仍是 `stdio`，现有 MCP 客户端配置无需改动
- 非回环监听必须设置 `SW_MCP_TOKEN` 和显式 `--allow-host`；Host 填客户端访问的实际 IP/域名，可重复指定
- 客户端请求携带 `Authorization: Bearer <共享密钥>`；浏览器客户端另需明确 `--allow-origin "https://客户端域名"`
- Host/Origin 校验保持开启；用本机私有测试端点验证过握手、401、错误 Host 与错误 Origin 拒绝
- 通过公网或不可信网络连接时，使用带 TLS 的反向代理或受控隧道保护传输

客户端配置示例（OpenCode / 其他支持 remote MCP 的客户端）：

```jsonc
{
  "mcp": {
    "servers": {
      "solidworks": {
        "type": "remote",
        "url": "http://192.168.1.10:8000/mcp",
        "headers": { "Authorization": "Bearer <共享密钥>" }
      }
    }
  }
}
```

客户端的 URL/headers 配置字段以对应客户端文档为准。该传输使用现有 MCP 进程和 COM 串行锁。

### 取回预览与交付文件

输出文件位于 `--output-root`（或 `SW_MCP_OUTPUT_ROOT`）内时，工具结果附加 `artifact_refs`，包含不透明 `artifact_id`、`uri`、文件大小和 SHA-256。未配置时只允许系统临时目录下的 `solidworks-automation-artifacts`；建议明确指定交付目录。

- 调用 `cadstudio_read_artifact`，参数为 `{"params":{"artifact_id":"<结果中的 ID>"}}`，小图返回标准 PNG 内容块。
- 用 `resources/read` 读取结果中的 `cad-artifact://delivery/...` URI，取回不超过 8 MiB 的原始二进制文件。
- 大文件用 `cadstudio_read_artifact`，设置 `as_preview:false`、`offset`、`max_bytes`，按 `next_offset` 拼接 base64 块；完成后比对 SHA-256。
- 读取适配复用既有 Artifact Ledger；文件改变、目录越界或任意路径参数均不能作为已验证产物读取。

远端输入仍需预先放到 CAD 主机；产物读取接口只服务已有交付文件。
工具**当前共 69 个**。发现模式下这些工具不出现在 `tools/list` 中，但检索、Schema 读取和执行行为与完整模式一致。`cadstudio_list_drc_rules` 列出设计审计规则；`cadstudio_check_drc` 检查中性文档并写报告，属于写操作，严格模式需要审批。API 查证可按需配置依赖，其权限行为见上文。

## Smithery 发布

根目录 `manifest.json` 遵循 MCPB 规范，并使用 `tools_generated: true`。先用 `mcpb pack` 生成标准包，再运行以下命令生成包含 FastMCP 实际 `inputSchema` 的 Smithery 发布包：

```powershell
mcpb pack . .\dist\solidworks-automation-skill-1.3.0.mcpb
python .\scripts\build_smithery_mcpb.py `
  .\dist\solidworks-automation-skill-1.3.0.mcpb `
  .\dist\solidworks-automation-skill-1.3.0-smithery.mcpb
smithery mcp publish .\dist\solidworks-automation-skill-1.3.0-smithery.mcpb `
  -n wzyn20051216/solidworks-automation-skill
```

Smithery 当前发布接口要求工具卡包含 `inputSchema`，而 MCPB 0.4 的静态 `tools` 项不允许该字段，因此发布包由脚本从 MCP Server 注册表自动生成，避免手工维护两套 schema。工具卡来自完整注册表（72 项：69 个原生工具 + 3 个发现入口），与运行时 `SW_MCP_DISCOVERY` 的选择无关。

## 多客户端自动注册

本仓库提供多客户端注册器，会自动尝试把 `solidworks` MCP Server 注册到：

- Codex
- Claude Code
- Claude Desktop
- Cursor
- Windsurf

在仓库根目录运行：

```powershell
powershell -ExecutionPolicy Bypass -File .\mcp-server\register_all_ai_mcp.ps1 -InstallDependencies
```

只注册指定客户端：

```powershell
powershell -ExecutionPolicy Bypass -File .\mcp-server\register_all_ai_mcp.ps1 -InstallDependencies -Clients codex,claude-code,cursor
```

Node.js 版本可直接用于 `npx` 安装器或 CI：

```powershell
node .\mcp-server\register_all_ai_mcp.js --install-dependencies
```

注册后可按客户端检查：

```powershell
codex mcp list
claude mcp list
```

> 通过本仓库 `npx` 安装时会自动运行多客户端注册器。某些 AI 客户端的纯 skill 导入不会执行安装脚本，需要在本地运行上述注册命令。

## Codex 专用注册

如果只想注册 Codex：

```powershell
powershell -ExecutionPolicy Bypass -File .\mcp-server\register_codex_mcp.ps1 -InstallDependencies
```

## 手动配置

把路径替换为你的本地仓库路径：

```json
{
  "mcpServers": {
    "solidworks": {
      "command": "python",
      "args": [
        "C:\\path\\to\\solidworks-automation-skill\\mcp-server\\server.py"
      ]
    }
  }
}
```

如果你的客户端支持命令行注册，也可以使用类似命令：

```powershell
codex mcp add solidworks -- python C:\path\to\solidworks-automation-skill\mcp-server\server.py
claude mcp add --scope user solidworks -- python C:\path\to\solidworks-automation-skill\mcp-server\server.py
```

## 已暴露工具

| 工具 | 说明 | 是否修改 SolidWorks |
|---|---|---|
| `cadstudio_resolve_backend` | 按能力真源、接口语义、可用运行时、Revision 和加载项条件选择 Python/C#/C++/SWBasic/OCCT 等后端 | 否 |
| `cadstudio_write_open_format` | 从本地 `.cadstudio.json` 白名单写出 STEP/IGES/BREP/STL/OBJ/GLB/DXF/SVG/PDF/PNG、Preview Manifest/Scene 和几何/哈希证据 | 否 |
| `cadstudio_build_dxf_preview_scene` | 只读 DXF 白名单转换为不覆盖旧文件的 `.scene.json` | 否 |
| `cadstudio_read_artifact` | 按交付 ID 返回 PNG 预览或有界二进制块，校验已有 Ledger 的 SHA-256 | 否 |
| `cadstudio_check_dfm` | 对 NeutralCadDocument 执行机加工、钣金、激光切割、3D 打印或注塑声明型 DFM 检查；缺关键输入返回 blocked，规则通过仍需人工复核 | 否 |
| `cadstudio_check_routing` | 校验中性 Routing 端点、分段、长度、弯曲半径、碰撞/间隙、支撑和 Routing BOM | 否 |
| `cadstudio_routing_preflight` | 探测 SOLIDWORKS Routing 类型库、加载项注册和许可证证据；缺证据返回 blocked | 否 |
| `solidworks_addin_host_status` | 只读检查 C# Add-in 程序集、HKCU/HKLM 注册层级、进程内 UI/事件诊断和阻塞码 | 否 |
| `solidworks_lookup_api` | 按目标版本查证 API；默认联网并按需自动安装依赖，不启动或修改 CAD | 按参数：默认可能修改环境；可关闭自动安装 |
| `cadstudio_fea_preflight` | 探测 CalculiX/Elmer 求解器，不执行任意命令 | 否 |
| `cadstudio_prepare_fea` | 从 FEA 1.0/1.1 请求生成版本化 CalculiX `.inp`，不运行任意脚本 | 否 |
| `cadstudio_run_fea` | 运行白名单 CalculiX 线性或受限非线性静力任务并解析位移、应力和收敛证据 | 否 |
| `cadstudio_run_fea_convergence` | 运行 3-8 档白名单网格并比较末两档位移/应力变化 | 否 |
| `cadstudio_review_advanced_geometry` | 校验复杂曲面/模具中性计划并返回 pilot/blocked 门禁证据 | 否 |
| `cadstudio_create_ocp_loft` | 从白名单封闭截面生成真实直纹 Loft STEP/BREP/STL，并重开验证 B-Rep | 否 |
| `cadstudio_create_ocp_surface` | 从严格 JSON 生成平滑 Loft、直线/圆弧 Sweep、闭壳 Knit 或开放面 Thicken，并返回连续性采样证据 | 否 |
| `solidworks_health_check` | 检查 Python 依赖、SolidWorks 检测、Motion 类型库和可选实时连接 | 否 |
| `solidworks_connect` | 连接/启动 SolidWorks 并返回活动文档摘要 | 否 |
| `solidworks_new_document` | 新建零件/装配体/工程图 | 是 |
| `solidworks_create_basic_part` | 创建基础盒体/圆柱零件，可保存并设置文档颜色 | 是 |
| `solidworks_open_document` | 打开已有 SolidWorks 文档 | 是 |
| `solidworks_add_component` | 向活动装配体添加零件/子装配体，可选固定组件 | 是 |
| `solidworks_set_component_fixed` | 按组件名关键字固定或浮动装配体组件 | 是 |
| `solidworks_save_document` | 保存或另存为活动文档 | 是 |
| `solidworks_close_documents` | 关闭活动文档或全部文档 | 是，可能丢弃未保存修改 |
| `solidworks_add_coincident_mate` | 在两个组件的指定基准面/特征之间添加重合 Mate | 是 |
| `solidworks_add_distance_mate` | 在两个组件的指定基准面/特征之间添加距离 Mate | 是 |
| `solidworks_add_concentric_mate` | 按圆柱面半径范围添加同心 Mate，可选择是否锁转 | 是 |
| `solidworks_set_appearance` | 设置活动文档或指定组件外观颜色 | 是 |
| `solidworks_export_active` | 导出活动文档为 STEP/STL/IGES/Parasolid/PDF/DXF | 是，写输出文件 |
| `solidworks_inspect_configurations` | 读取配置清单和当前活动配置 | 否 |
| `solidworks_create_configuration` | 用 AddConfiguration3 创建/复用配置，可激活、重建、保存并回读 | 是 |
| `solidworks_activate_configuration` | 切换配置并用活动配置名和重建结果回读验证 | 是 |
| `solidworks_update_dimension` | 按准确尺寸名修改参数，返回修改前后、重建和保存证据 | 是 |
| `solidworks_set_custom_properties` | 写入并回读文件级或配置级自定义属性 | 是 |
| `solidworks_batch_export_files` | 多文件、多格式批量导出并核验本轮产物 | 是，写输出文件 |
| `solidworks_export_assembly_bom` | 导出装配组件/属性 BOM CSV，强制人工复核 | 是，写输出文件 |
| `solidworks_pack_and_go` | 使用原生 Pack and Go 打包文档与引用 | 是，写输出文件 |
| `solidworks_review_active` | 导出多视角 BMP 预览和 JSON 审查报告 | 是，写输出文件 |
| `solidworks_generate_drawing` | 按 DrawingSpec v1 生成 GB/T/ISO 工程图、SLDDRW、PDF、预览和审查报告；将 COM 尺寸位置与最终 PDF 文字框关联 | 是，写输出文件 |
| `solidworks_review_drawing` | 按 DrawingSpec 审查工程图结构、布局、尺寸链、孔槽和最终 PDF 尺寸文字边界 | 否，写审查输出 |
| `solidworks_inspect_drawing` | 只读读取工程图页、视图、尺寸、注释、表格和 BMP 预览证据 | 否，写审查输出 |
| `solidworks_create_hole_feature` | 创建盲孔、通孔、沉孔、沉头孔或半圆端槽，并返回参数证据 | 是 |
| `solidworks_inspect_hole_features` | 读取 B-Rep 孔段、复合孔、槽端圆弧并验证孔位 | 否 |
| `solidworks_add_rotary_motor` | 在活动装配体中新建 Motion Study 并添加匀速旋转马达 | 是 |
| `solidworks_inspect_motion_studies` | 读取算例、马达/外力数量和结果新鲜度 | 否 |
| `solidworks_validate_motion_study` | 对时长、类型、马达数量、结果存在性和过期状态执行交付门禁 | 否 |

## 基础装配工具示例

创建圆柱零件：

```json
{
  "shape": "cylinder",
  "radius_mm": 25,
  "depth_mm": 50,
  "output_path": "C:\\temp\\cylinder.SLDPRT",
  "color": "#BFC4C8"
}
```

向活动装配体添加组件并固定：

```json
{
  "path": "C:\\temp\\base.SLDPRT",
  "x_mm": 0,
  "y_mm": 0,
  "z_mm": 0,
  "fix_component": true
}
```

添加保留旋转自由度的同心 Mate：

```json
{
  "component_a_keyword": "stand",
  "component_b_keyword": "impeller",
  "radius_a_min_mm": 4.5,
  "radius_a_max_mm": 5.5,
  "radius_b_min_mm": 11,
  "radius_b_max_mm": 13,
  "lock_rotation": false
}
```

添加轴向距离 Mate：

```json
{
  "component_a_keyword": "stand",
  "component_b_keyword": "impeller",
  "feature_a_name": "Front Plane",
  "feature_b_name": "Front Plane",
  "distance_mm": 42
}
```

## Motion Study 示例

前提：活动文档是装配体，里面有一个静止轴/立柱组件和一个叶轮组件；叶轮的同心 Mate 未锁定旋转，且叶轮组件未固定。

调用参数示例：

```json
{
  "shaft_component_keyword": "stand",
  "rotor_component_keyword": "impeller",
  "shaft_radius_min_mm": 4.5,
  "shaft_radius_max_mm": 5.5,
  "rotor_radius_min_mm": 10.5,
  "rotor_radius_max_mm": 11.5,
  "rpm": 60,
  "study_name": "叶轮_60RPM_循环转动",
  "motor_name": "叶轮旋转马达_60RPM",
  "duration_seconds": 4,
  "calculate": true,
  "play": false
}
```

创建复杂沉孔：

```json
{
  "feature_kind": "counterbore",
  "center_x_mm": 20,
  "center_y_mm": 15,
  "diameter_mm": 6,
  "secondary_diameter_mm": 12,
  "secondary_depth_mm": 4,
  "plane_name": "Front Plane",
  "feature_name": "H1_沉孔"
}
```

验证 Motion Study：

```json
{
  "study_name": "叶轮_60RPM_循环转动",
  "expected_study_type": 1,
  "minimum_duration_seconds": 4,
  "minimum_motor_count": 1,
  "require_results": true
}
```

## 设计原则

- 不开放任意 Python/VBA 执行工具，避免 MCP 客户端直接执行不受控脚本。
- CAD Studio 无头/门禁工具使用 `cadstudio_` 前缀，SolidWorks 原生工具使用 `solidworks_` 前缀，避免与其他 MCP server 冲突。
- 所有 COM 操作串行执行，降低 SolidWorks 桌面会话崩溃概率。
- 错误返回包含建议动作，方便 LLM 自行纠错。

## 已知限制

- MCP 已覆盖基础盒体/圆柱、复杂孔槽、添加组件、常用 Mate、固定/浮动、外观、导出、审查、旋转马达、Motion 结果门禁，以及 DFM/Routing/FEA/复杂几何的受控入口。
- 受限封闭直纹 Loft 可生成并重开真实 STEP/BREP；平滑 Loft、扫描、自由曲面、G1/G2 和模具仍只开放结构化计划门禁。
- SolidWorks Motion / Simulation 许可证差异可能影响计算能力；缺少合法加载项或授权时返回 `blocked`，不尝试绕过。

## 原生圆截面路径工具

五个受保护的试验性工具支持原生扫描、STEP 导入、实体审查/排除和保持位置的组件替换。规格、限制和审查要求见 [工具说明](../docs/native-wire-tools.md)。
