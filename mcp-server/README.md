# SolidWorks MCP Server

本目录提供一个本地 `stdio` MCP Server，把 `solidworks-automation-skill/scripts` 中的 Python COM 封装暴露为 MCP 工具。

SolidWorks 是 Windows 桌面 COM 应用，不适合远程多客户端并发；因此本 server 默认使用 `stdio`，并在内部用全局锁串行执行所有 SolidWorks 操作。

## 环境要求

- Windows 10/11
- SolidWorks 已安装并至少启动过一次，完成 COM 注册
- Python 3.8+
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

## Codex / Claude Desktop 配置示例

把路径替换为你的本地仓库路径：

```json
{
  "mcpServers": {
    "solidworks": {
      "command": "python",
      "args": [
        "C:\\Users\\23201\\.codex\\skills\\solidworks-automation\\mcp-server\\server.py"
      ]
    }
  }
}
```

如果你的客户端支持命令行注册，也可以使用类似命令：

```powershell
codex mcp add solidworks python C:\Users\23201\.codex\skills\solidworks-automation\mcp-server\server.py
```

## 已暴露工具

| 工具 | 说明 | 是否修改 SolidWorks |
|---|---|---|
| `solidworks_connect` | 连接/启动 SolidWorks 并返回活动文档摘要 | 否 |
| `solidworks_new_document` | 新建零件/装配体/工程图 | 是 |
| `solidworks_open_document` | 打开已有 SolidWorks 文档 | 是 |
| `solidworks_save_document` | 保存或另存为活动文档 | 是 |
| `solidworks_close_documents` | 关闭活动文档或全部文档 | 是，可能丢弃未保存修改 |
| `solidworks_export_active` | 导出活动文档为 STEP/STL/IGES/Parasolid/PDF/DXF | 是，写输出文件 |
| `solidworks_review_active` | 导出多视角 BMP 预览和 JSON 审查报告 | 是，写输出文件 |
| `solidworks_add_rotary_motor` | 在活动装配体中新建 Motion Study 并添加匀速旋转马达 | 是 |

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

## 设计原则

- 不开放任意 Python/VBA 执行工具，避免 MCP 客户端直接执行不受控脚本。
- 所有工具名使用 `solidworks_` 前缀，避免与其他 MCP server 冲突。
- 所有 COM 操作串行执行，降低 SolidWorks 桌面会话崩溃概率。
- 错误返回包含建议动作，方便 LLM 自行纠错。

## 已知限制

- 当前是第一阶段工具集，重点覆盖文档、导出、审查、Motion Study 旋转马达。
- 复杂零件建模原语尚未全部暴露为 MCP 工具，建议后续按 `sw_part.py`、`sw_assembly.py` 继续扩展。
- SolidWorks Motion / Simulation 许可证差异可能影响 Motion Study 的计算能力。
