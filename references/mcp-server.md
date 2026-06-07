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

所有工具使用 `solidworks_` 前缀，避免和其他 MCP server 冲突：

- `solidworks_connect`
- `solidworks_new_document`
- `solidworks_open_document`
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

暂缓扩展：

- 任意草图约束求解。
- 复杂扫描/放样。
- 接触、摩擦、碰撞等高阶运动仿真。

## 返回格式

工具默认返回 JSON，便于 LLM 继续解析。也支持 `response_format="markdown"` 用于人工阅读。

错误返回应包含：

- `error_type`
- `message`
- `suggestion`

不要把 Python traceback 原样暴露给 MCP 客户端。
