# SolidWorks MCP Server 设计说明

## 架构

```text
Codex / Claude / 其他 MCP Client
        ↓ stdio MCP
mcp-server/server.py
        ↓ Python COM / pywin32
SolidWorks Desktop
```

SolidWorks 是 Windows 桌面 COM 应用，不是原生 MCP 服务。MCP Server 的职责是把已经验证过的 `scripts/sw_*.py` 封装成受控工具，避免代理每次临时生成大段脚本。

## Transport 选择

默认使用 `stdio`：

- 适合本地桌面软件。
- 客户端作为子进程启动 server，配置简单。
- 不暴露网络端口，减少安全面。

暂不默认使用 HTTP：

- SolidWorks COM 一般绑定当前桌面用户会话。
- 多客户端并发容易让 SolidWorks 文档状态混乱。
- 远程访问还需要身份认证、Origin 校验和桌面会话隔离。

## 工具发现与审批

默认模式 `SW_MCP_DISCOVERY=search` 只暴露三个入口（`sw_search_tools` / `sw_describe_tool` /
`sw_call_tool`），69 个原生命名工具按需检索。`SW_MCP_DISCOVERY=full` 保留全部命名工具，
用于需要客户端逐工具权限提示的场景。

使用 `sw_search_tools` 搜索“API 接口签名”，再调用 `solidworks_lookup_api`；提供 `interface` 和 `member`，或改为提供自然语言 `task`，可选 `version` / `process_id`。默认按需自动配置依赖，因此工具注解标记为可能修改环境；`auto_install=false` 禁用安装，`offline=true` 禁用联网和安装，服务端会按参数区分副作用级别，保留客户端与服务端原有授权模式。官网直读失败且本地无缓存时，默认使用匿名 Parallel 提取对应版本的官方页面，使用 `parallel_fallback=false` 关闭。Parallel 的版本依据弱于官网结构化数据；所有结果都不能代替目标版本的真机验证。详情见 `references/api-lookup.md`。

实现上把 FastMCP 的 `_tool_manager` 换成 `ToolGate` 代理。`list_tools` 和 `call_tool` 都在
调用时读取这个属性，因此 stdio、streamable-http、以及客户端直接点名调用被隐藏工具，全部
经过同一套检查：

- `mcp-server/discovery.py`：离线检索，只读工具元数据，不承担授权与执行。
- `mcp-server/policy.py`：副作用唯一真源（READ / WRITE / DESTRUCTIVE / UNKNOWN）；
  未登记的工具默认拒绝，新增工具必须先补分级，`tests/test_mcp_discovery.py` 会强制对齐注册表。
- `mcp-server/gate.py`：可见性控制、执行前策略检查、写操作审批。
- `mcp-server/approval.py`：可选的 HMAC 签名一次性批准账本；批准绑定工具、参数摘要、服务端会话和有效期。严格模式可绑定已保存文档的进程 ID 与路径，但不能证明文档内容未改变。
- `scripts/sw_mcp_approve.py`：通过交互式终端确认；模型在 MCP 参数里传 `approved: true` 不生效。TTY 不证明真人，同一操作系统用户的进程可模拟终端或访问账本，不能将它视作隔离不可信 Agent 的安全边界。

审批模式 `SW_MCP_APPROVAL`：`auto`（默认，发现模式→`task`，完整模式→`client`）、
`task`、`server`、`client`、`elicit`、`off`。`task` 信任客户端任务授权，服务端不会验证其是否经过用户确认。
`elicit` 依赖客户端支持 MCP elicitation，且可能被
agent 自动应答，不作为默认。服务端账本同样不隔离具有相同操作系统权限的进程。

## 多客户端注册策略

安装器会调用 `mcp-server/register_all_ai_mcp.js`，尽量自动注册常见本地 AI 客户端：

- Codex：通过 `codex mcp add solidworks -- <python> <server.py>` 注册。
- Claude Code：通过 `claude mcp add --scope user solidworks -- <python> <server.py>` 注册。
- Claude Desktop：写入用户级 `claude_desktop_config.json`。
- Cursor：写入全局 `~/.cursor/mcp.json`。
- Windsurf：写入全局 `~/.codeium/windsurf/mcp_config.json`。

注意：

1. 只有执行 `npx` 安装器或注册脚本时，才能自动修改本机 MCP 配置；纯 skill 导入通常不会运行安装脚本。
2. 不同客户端可能需要重启或人工确认信任后才会加载新 MCP。
3. 云端网页产品没有本机配置入口时，skill 无法替用户直接安装本地 MCP。
4. JSON 配置写入前会创建 `.bak-*` 备份；命令行客户端会先移除同名 server 再重新注册。

## 并发策略

`mcp-server/server.py` 使用全局 `RLock` 串行执行所有工具。原因：

- SolidWorks COM 自动化不是线程安全的通用服务。
- 多个工具同时切换活动文档、选择实体或保存文件，会互相破坏状态。
- Motion Study / Mate 创建依赖当前选择集，必须避免并发污染。

每个工具调用前会尝试 `pythoncom.CoInitialize()`，保证当前 MCP worker 线程可使用 COM。

## 工具命名

工具名前缀按能力边界区分：`cadstudio_` 用于无头开放格式、DFM、Routing、FEA 和复杂几何门禁；`solidworks_` 用于真实 SolidWorks COM 操作。

CAD Studio 门禁工具：

- `cadstudio_resolve_backend`
- `cadstudio_write_open_format`
- `cadstudio_build_dxf_preview_scene`
- `cadstudio_check_dfm`
- `cadstudio_check_routing`
- `cadstudio_routing_preflight`
- `cadstudio_fea_preflight`
- `cadstudio_prepare_fea`
- `cadstudio_run_fea`
- `cadstudio_run_fea_convergence`
- `cadstudio_review_advanced_geometry`
- `cadstudio_create_ocp_loft`
- `cadstudio_create_ocp_surface`

SolidWorks 原生工具：

- `solidworks_connect`
- `solidworks_new_document`
- `solidworks_open_document`
- `solidworks_inspect_configurations`
- `solidworks_create_configuration`
- `solidworks_activate_configuration`
- `solidworks_save_document`
- `solidworks_close_documents`
- `solidworks_export_active`
- `solidworks_review_active`
- `solidworks_add_rotary_motor`

## 安全边界

第一阶段不开放：

- 任意 Python 执行。
- 任意 VBA 宏执行。
- 直接删除文件。
- 批量关闭/覆盖用户文件的隐藏动作。

如需新增危险工具，至少要：

1. 明确工具名含 `delete` / `overwrite` / `close_all` 等动作。
2. 输入 schema 限制路径和参数范围。
3. 返回结构化结果，包含实际影响范围。
4. 在文档中标注 `destructiveHint=True`。

## 扩展顺序建议

优先扩展高价值、低歧义工具：

1. 文档与导出：打开、保存、导出、审查。
2. 装配体：添加组件、按组件名查找、创建同心/重合 Mate。
3. Motion Study：旋转马达、线性马达、计算/播放。
4. 零件建模：受控草图原语和特征原语。
5. 工程图：三视图、BOM、PDF 导出。
6. 无头能力：DFM profile、Routing 中性复核、CalculiX 受限线性/非线性与网格序列、OCP 直纹/平滑 Loft、Sweep/Knit/Thicken 和其余复杂几何计划复核。

暂缓扩展：

- 任意草图约束求解。
- 平滑 Loft、复杂扫描、G1/G2/Class-A 和模具质量 B-Rep 生成。
- 大型接触、自动穿透验收、碰撞等高阶仿真与安全认证。

## 返回格式

工具默认返回 JSON，便于 LLM 继续解析。也支持 `response_format="markdown"` 用于人工阅读。

错误返回应包含：

- `error_type`
- `message`
- `suggestion`

不要把 Python traceback 原样暴露给 MCP 客户端。
