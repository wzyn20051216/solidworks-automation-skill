# SolidWorks MCP Server

本目录提供一个本地 `stdio` MCP Server，同时暴露无 CAD 开放格式工具和 SolidWorks COM 白名单工具。MCP 与 CAD Studio、Skill、CLI 共用能力清单和数据协议。

SolidWorks 是 Windows 桌面 COM 应用，不适合远程多客户端并发；因此本 server 默认使用 `stdio`，并在内部用全局锁串行执行所有 SolidWorks 操作。

## 环境要求

- Windows 10/11
- 仅调用 `cadstudio_write_open_format` 时不需要安装 SolidWorks/AutoCAD
- 调用 `solidworks_*` 原生工具时需要 SolidWorks 已安装并至少启动过一次，完成 COM 注册
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
| `cadstudio_write_open_format` | 从本地 `.cadstudio.json` 白名单写出 STEP/IGES/BREP/STL/OBJ/GLB/DXF/SVG/PDF/PNG、Preview Manifest/Scene 和几何/哈希证据 | 否 |
| `cadstudio_build_dxf_preview_scene` | 只读 DXF 白名单转换为不覆盖旧文件的 `.scene.json` | 否 |
| `cadstudio_check_dfm` | 对 NeutralCadDocument 执行机加工、钣金、激光切割或 3D 打印 DFM 规则检查，支持 supplier profile 与 B-Rep 证据；缺关键输入返回 blocked，规则通过仍需人工复核 | 否 |
| `cadstudio_check_routing` | 校验中性 Routing 端点、分段、长度、弯曲半径、碰撞/间隙、支撑和 Routing BOM | 否 |
| `cadstudio_routing_preflight` | 探测 SOLIDWORKS Routing 类型库、加载项注册和许可证证据；缺证据返回 blocked | 否 |
| `cadstudio_fea_preflight` | 探测 CalculiX/Elmer 求解器，不执行任意命令 | 否 |
| `cadstudio_prepare_fea` | 从 FEA 1.0 请求生成版本化 CalculiX `.inp`，不运行任意脚本 | 否 |
| `cadstudio_run_fea` | 运行白名单 CalculiX 线性静力任务并解析位移、应力和收敛证据 | 否 |
| `cadstudio_review_advanced_geometry` | 校验复杂曲面/模具中性计划并返回 pilot/blocked 门禁证据 | 否 |
| `cadstudio_create_ocp_loft` | 从白名单封闭截面生成真实直纹 Loft STEP/BREP/STL，并重开验证 B-Rep | 否 |
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
| `solidworks_update_dimension` | 按准确尺寸名修改参数，返回修改前后、重建和保存证据 | 是 |
| `solidworks_set_custom_properties` | 写入并回读文件级或配置级自定义属性 | 是 |
| `solidworks_batch_export_files` | 多文件、多格式批量导出并核验本轮产物 | 是，写输出文件 |
| `solidworks_export_assembly_bom` | 导出装配组件/属性 BOM CSV，强制人工复核 | 是，写输出文件 |
| `solidworks_pack_and_go` | 使用原生 Pack and Go 打包文档与引用 | 是，写输出文件 |
| `solidworks_review_active` | 导出多视角 BMP 预览和 JSON 审查报告 | 是，写输出文件 |
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
