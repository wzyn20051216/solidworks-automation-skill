---
name: solidworks-automation
description: "SolidWorks CAD 自动化技能，可通过 Python COM 接口与 OpenClaw / Codex / Claude 协作控制 Windows 上运行的 SolidWorks，用于零件建模、装配体、工程图、钣金、焊件、仿真、文件导出、自定义属性、设计表、配置管理，以及 OBJ/STL/STEP 等外来模型导入；当用户提到 SolidWorks、SW、OpenClaw、龙虾、3D 建模、CAD、零件、装配、工程图、钣金、焊件、导出 STEP/STL/PDF、BOM、设计表、公开三维模型、网格参考模型、原版外观复刻或高还原产品外观时使用。"
metadata: { "openclaw": { "homepage": "https://github.com/wzyn20051216/solidworks-automation-skill", "os": ["win32"], "requires": { "anyBins": ["python", "py"] } } }
---

# SolidWorks 自动化技能

## 快速开始

### 环境要求

- Windows 系统 + SolidWorks 已安装并运行
- Python 3.8+ + `pywin32` / `comtypes`
- MCP/工具化调用需要 `mcp` / `pydantic`
- 处理 GLB/GLTF/OBJ/STL 网格参考模型时，可能还需要 `trimesh` / `pygltflib` / `numpy` / `Pillow`
- 如果通过 OpenClaw 使用，确保技能目录位于 `~/.openclaw/skills/solidworks-automation/` 或 `~/.agents/skills/solidworks-automation/`

### 入口自检

所有代理在执行 SolidWorks 自动化前，先运行技能自检：

```bash
python SKILL_DIR/scripts/sw_preflight.py
```

规则：

1. 检测到缺少 `comtypes` / `win32com` / `pythoncom` 时，向用户弹出友好确认：
   `检测到当前 Python 环境缺少 comtypes / win32com 库，是否授权 AI 自动为您配置本地环境？[Y/N]`
2. 用户输入 `Y` / `yes` 后，代理可在本地 shell 中自动执行 `python -m pip install "pywin32>=305" "comtypes>=1.2.0"` 补齐依赖；用户拒绝时停止并给出手动安装命令。
3. 检测不到 SolidWorks 安装或 COM 注册时，直接停止，不要继续生成或执行 CAD 脚本；提示用户：需要先手动安装 SolidWorks，并至少启动一次完成 COM 注册。

### Python 依赖提醒

按任务最小化安装依赖，不要在普通零件建模时强制安装网格转换库：

```powershell
# 核心 SolidWorks COM 自动化依赖
python -m pip install -r SKILL_DIR\requirements.txt

# 仅在需要 GLB/GLTF/OBJ/STL 网格检查、缩放或转换时安装
python -m pip install -r SKILL_DIR\requirements-mesh.txt
```

执行涉及 GLB/GLTF/FBX/BLEND 转 OBJ/STL 的任务前，先用 `importlib.util.find_spec()` 检查
`trimesh`、`pygltflib`、`PIL` 是否可用；缺失时先提示用户需要安装哪些库和用途，再安装或给出手动命令。

### 连接 SolidWorks

```python
import sys; sys.path.insert(0, r"SKILL_DIR/scripts")
from sw_connect import mm
from sw_part import sketch, sketch_circle, extrude_boss
from sw_session import SolidWorksSession

session = SolidWorksSession()
model = session.new_part()

with sketch(model, "Front Plane") as sketch_name:
    sketch_circle(model, 0, 0, mm(25))

extrude_boss(model, sketch_name, mm(50))
session.save(model, r"C:\temp\cylinder.sldprt")
session.export(model, r"C:\temp\cylinder.step")
```

> 将 `SKILL_DIR` 替换为此技能的实际安装路径。

## 核心工作流

根据用户需求选择对应模块：

| 需求 | 脚本 | 参考文档 |
|---|---|---|
| 入口自检与依赖补齐 | `scripts/sw_preflight.py` | `references/troubleshooting.md` |
| 高级能力/类型库探测 | `scripts/sw_capability_probe.py` | `references/complex-mechanical-routing.md` |
| 多模型宏生成防护 | `scripts/sw_macro_guard.py` | `references/openclaw.md` |
| 友好会话 API | `scripts/sw_session.py` | - |
| 连接与文档管理 | `scripts/sw_connect.py` | - |
| 外观与材质 | `scripts/sw_appearance.py` | `references/appearance.md` |
| 零件建模（草图+特征） | `scripts/sw_part.py` | `references/part-modeling.md` |
| 盲孔/沉孔/沉头孔/半圆端槽与孔位验收 | `scripts/sw_hole_features.py`、`scripts/sw_review.py` | `references/complex-hole-features.md`、`references/review.md` |
| 自然语言到参数化设计计划 / VibeCAD | `subskills/solidworks-vibecad/scripts/plan_from_brief.py` | `subskills/solidworks-vibecad/SKILL.md`、`subskills/solidworks-vibecad/README.md` |
| 多圆角/倒角 CNC 机加工件 | `subskills/solidworks-fillet-chamfer-cnc/scripts/create_cnc_mount_template.py` | `subskills/solidworks-fillet-chamfer-cnc/SKILL.md`、`subskills/solidworks-fillet-chamfer-cnc/references/cnc-fillet-chamfer-lessons.md` |
| 螺丝孔/螺纹孔、攻丝底孔 | `subskills/solidworks-threaded-holes/scripts/create_threaded_hole_template.py` | `subskills/solidworks-threaded-holes/SKILL.md`、`subskills/solidworks-threaded-holes/references/threaded-hole-lessons.md` |
| AutoCAD DWG/DXF 二维绘图、线稿转 CAD、批量改图 | `subskills/autocad-automation/scripts/acad_draw.py`、`subskills/autocad-automation/scripts/acad_review.py` | `subskills/autocad-automation/SKILL.md`、`subskills/autocad-automation/references/troubleshooting.md` |
| 装配体操作、齿轮/铰链/可拖动运动配合 | `scripts/sw_assembly.py` | `references/assembly.md` |
| Motion Study 运动算例、旋转马达与结果审计 | `scripts/sw_motion.py` | `references/motion-study.md`、`references/complex-mechanical-routing.md` |
| 工程图出图 | `scripts/sw_drawing.py` | `references/drawing.md` |
| 文件导出 | `scripts/sw_export.py` | `references/export.md` |
| OBJ/STL 高还原网格参考导入 | `scripts/sw_import_mesh_reference.py` | `references/mesh-reference-import.md` |
| 结果自审查 | `scripts/sw_review.py` | `references/review.md` |
| 本地 MCP Server | `mcp-server/server.py` | `mcp-server/README.md`、`references/mcp-server.md` |
| MCP 协议验证 | `scripts/validate_mcp.py` | `mcp-server/README.md` |
| 未封装 API 查证 | - | `references/api-lookup.md` |
| OpenClaw 控制 SolidWorks | - | `references/openclaw.md` |
| 钣金/焊件/仿真/属性 | - | `references/advanced.md` |
| 企业 Agent / 本地优先与云 RAG | `apps/desktop/cad_workbench/knowledge_retrieval.py` | `references/enterprise-agent-rag.md` |
| Codex/Claude/Gemini/OpenCode Provider Adapter | `apps/desktop/cad_workbench/agent_providers.py` | `references/agent-provider-architecture.md` |
| 综合机械工程 DAG 自动编排 | `apps/desktop/cad_workbench/engineering_orchestrator.py` | `references/complex-mechanical-routing.md` |
| 常见错误排查 | - | `references/troubleshooting.md` |

## OpenClaw 协作方式

1. 先确认 SolidWorks 版本、界面语言、输入文件路径、输出路径，以及目标操作（建模 / 装配 / 出图 / 导出）。
2. 优先复用 `{baseDir}/scripts` 下已有模块，不要重复手写 COM 连接逻辑。
3. 在 OpenClaw 的 `exec` / `shell` 能力中执行短小、一次性的 Python 脚本，最小导入集如下：

```python
import sys
sys.path.insert(0, r"{baseDir}/scripts")
from sw_connect import connect_solidworks, mm, deg, new_document
```

4. 执行后检查返回对象是否为 `None`、保存/导出是否成功、输出文件是否落盘。
5. 生成或修改模型后必须做结果自审查：导出至少一个等轴测预览图，必要时导出前/俯/右视图，并通过截图或 BMP 目视检查几何是否符合用户意图。
6. 如果需要更完整的 OpenClaw 工作流、提示词示例和排障建议，再读取 `references/openclaw.md`。

## 使用流程

1. 先运行 `sw_preflight.py`：缺依赖则请求用户授权自动安装；缺 SolidWorks 则停止并提示手动安装。
2. 优先用 `SolidWorksSession()` 管理连接、打开、新建、保存、导出。
3. 需要底层控制时再组合 `sw_connect.py`、`sw_part.py` 等函数。
4. 当用户需求偏自然语言、参数不完整或需要“行业知识库 + 提示词模板 + 参数化设计计划”时，先读取 `subskills/solidworks-vibecad/SKILL.md`，生成 `design_plan.json` 和执行摘要。
5. 圆角/倒角很多的 CNC 件、安装座、连接块、支架，先读取 `subskills/solidworks-fillet-chamfer-cnc/SKILL.md`，按“基础体 -> 外轮廓圆角/倒角 -> 孔槽切除 -> 孔口倒角 -> 审查”的稳定顺序执行。
6. 螺丝孔、螺纹孔、攻牙孔、M3/M4/M5/M6/M8 盲孔或通孔任务，先读取 `subskills/solidworks-threaded-holes/SKILL.md`；默认按“攻丝底孔 -> 尝试 Thread/CosmeticThread -> 可见 3D 螺旋线兜底 -> 孔口倒角 -> 属性和审查”的稳定路线执行。
7. 普通盲孔、通孔、圆柱沉孔、锥形沉头孔、半圆端槽或孔阵列任务，读取 `references/complex-hole-features.md` 并优先调用 `scripts/sw_hole_features.py`；创建参数证据必须再与 `collect_geometry_measurements()`、`validate_hole_positions()` 和剖视图交叉复核。
8. CAD、机械图纸、工程图、3D 打印外壳、开孔图、DWG、DXF、二维图纸、线稿转 CAD、批量改 DWG 或 AutoCAD 原生预览任务，先读取 `subskills/autocad-automation/SKILL.md`。机械/3D 打印开孔交付必须按可制造图纸处理：所有孔、槽、接口、水口、螺丝孔和螺丝柱同时给出规格、数量和定位尺寸；图面拥挤时用孔表/槽表，不得用长引线替代关键尺寸。普通“照图画 CAD”只保留原图矢量化线条，最终审查必须确认没有手工猜测的外围轮廓、五官辅助线、Logo 几何、水波线、替代文字或图内审查说明。
9. 当用户要求真实产品“原版外观”“1:1 复刻”“不像概念版”，先读取 `references/mesh-reference-import.md`：公开网格/蓝图参考优先，不要在低保真手搓底稿上反复精修；需要导入 OBJ/STL 时优先用 `scripts/sw_import_mesh_reference.py`。
10. 如果必须由大模型生成 VBA 宏，先使用 `sw_macro_guard.py` 做模型分流、代码校验、重试和本地模板兜底。
11. 使用 `session.export()` 或 `sw_export.py` 保存/导出文件。
12. 使用 `sw_review.py` 导出预览图并自审查；如果有 GUI/桌面截图能力，打开 SolidWorks 视图截图复核。
13. 遇到钣金、焊件、复杂曲面、模具、Routing、Simulation/FEA、复杂 Motion 或配置族任务，先运行 `sw_capability_probe.py` 并读取 `references/complex-mechanical-routing.md`；`reference_only/not_implemented` 能力不能假装已自动化完成。
14. 需要企业/项目机械知识时读取 `references/enterprise-agent-rag.md`；默认只用本地知识，云 RAG 必须显式启用、声明 `external_network` 并完成人工审批。
15. 当一个需求同时跨越零件、孔槽/圆角、装配 Mate、Motion、工程图/BOM 和多格式交付中的两个以上工程域时，调用 `apps/desktop/cad_workbench/engineering_orchestrator.py` 生成阶段 DAG。必须按依赖串行执行关键 CAD 写操作，每阶段独立保存产物和验收证据；局部修改只重规划受影响阶段及其后继，禁止把整项工程塞进一条超长 Prompt 后一次性宣称完成。

### 机械图纸默认底线

以后凡是本技能参与 CAD/机械结构/3D 打印项目，都默认执行这些底线：

1. 不把“看得懂的示意图”当成“能制造的工程图”。只要涉及开孔、开槽、接口、装配孔或打印外壳，必须补齐外形尺寸、壁厚/底厚、孔槽规格和定位尺寸。
2. 用户要求“中国常用格式”“国标风格”“严格规范”时，必须采用国内机械制图习惯：规范图幅/图框/标题栏、仿宋中文、分层线型、中心线/虚线、真实标注实体和技术要求。
3. 长引线只能做局部说明，不能替代尺寸链；不得跨视图、压孔、压中心线、压尺寸文字或侵入标题栏。
4. 密集孔槽必须优先用孔表、槽表或孔槽明细表，表内写清部位、规格、数量和定位；表格不能成为逃避定位尺寸的借口。
5. 交付前必须目视复核预览图，发现漏标、重叠、压线或标题栏侵入时先返工再汇报。

### 高还原外观/公开网格参考模型

当用户要求汽车、消费电子、雕塑等真实对象外观高还原时，先区分“视觉参考模型”和“工程可制造参数模型”：

1. 若用户要“像原版”，优先索取或查找公开 3D 模型/多视图蓝图，并记录来源、作者、许可证和下载日期；不要声称生成的是官方 Class-A 或扫描级模型。
2. `.glb/.gltf/.fbx/.blend` 先转换为 `.obj/.stl`；OBJ 优先保留材质，STL 作为无材质兜底。
3. 导入前用包围盒确认坐标轴和尺度，再按真实公称尺寸缩放。
4. 如果需要 Python 转换/缩放，先确认 `requirements-mesh.txt` 中的可选依赖可用；缺失时说明用途并提示安装。
5. OBJ/STL 导入 SolidWorks 时用 `sw_import_mesh_reference.py`；关键写法是 `LoadFile4(path, "r", create_empty_dispatch_variant(), errors)`，不要用 `OpenDoc6()` 或把 `None` 传给 `LoadFile4()`。
6. 结果审查必须看四视图和关键识别特征；“预览非空白”不能替代“像用户指定对象”。
7. 若用户后续要工程可编辑结构，应基于网格参考分件逆向重建，并明确说明网格导入件不是参数化实体。

### 多色外观要求

当模型包含车身、玻璃、灯组、轮胎、轮毂或其他多种颜色时：

1. 读取 `references/appearance.md`，统一使用 `sw_appearance.py`，禁止把普通 Python `list` 直接传给 COM 材质属性。
2. 源零件先设置文档级颜色；装配体中需要覆盖时再用组件级颜色。
3. 每次设置后调用 `verify_appearance()` 或 `apply_component_palette()` 回读 RGB；只检查 setter 返回值不算通过。
4. 保存与截图前调用 `model.ClearSelection2(True)`；`sw_review.save_preview()` 已内置该清理。
5. 目视确认至少三种预期颜色真实可见；“预览非空白”不能替代颜色检查。
6. 外观异常时先运行 `tests/solidworks_appearance_regression.py`，再重建用户模型。

### MCP Server 使用

当用户要求“让 SolidWorks 支持 MCP”“接入 Codex/Claude Desktop 工具调用”“不要每次生成一大段 Python 脚本”时：

1. 读取 `mcp-server/README.md`。
2. 若用户要求自动配置 MCP，优先运行多客户端注册器：`powershell -ExecutionPolicy Bypass -File mcp-server/register_all_ai_mcp.ps1 -InstallDependencies`；它会尝试注册 Codex、Claude Code、Claude Desktop、Cursor、Windsurf。
3. 使用本地 `stdio` MCP server：`python mcp-server/server.py`。
4. 工具调用优先走 `solidworks_health_check`、`solidworks_create_basic_part`、`solidworks_create_hole_feature`、`solidworks_inspect_hole_features`、`solidworks_add_component`、`solidworks_add_coincident_mate`、`solidworks_add_distance_mate`、`solidworks_add_concentric_mate`、`solidworks_set_component_fixed`、`solidworks_export_active`、`solidworks_review_active`、`solidworks_add_rotary_motor`、`solidworks_inspect_motion_studies`、`solidworks_validate_motion_study`。
5. 不要暴露任意 Python/VBA 执行工具；新增 MCP 工具时应复用 `scripts/sw_*.py` 中已验证封装。
6. SolidWorks COM 操作必须串行执行；MCP server 内部已使用全局锁降低桌面会话冲突。
7. 基准 demo 使用 `examples/08_mini_fan_motion_assembly.py`；它验证自动建模、装配、Mate 和 Motion Study，不承诺圆角/倒角外观完美。

### 运动装配体要求

当用户要求“能动起来”“在 SolidWorks 里拖动”“铰链”“齿轮联动”“真实机械配合”时：

1. 先读取 `references/assembly.md` 的运动型装配工作流；如果用户明确要求 Motion Study / 运动算例 / 马达，再读取 `references/motion-study.md`。
2. 优先复用 `sw_assembly.py` 中的 `resolve_component()`、`get_assembly_entity()`、`find_largest_cylinder_face()`、`add_mate5_checked()`、`add_concentric_mate_by_cylinders()`、`add_gear_mate_by_cylinders()`。
3. 旋转件用同心 Mate 且 `lock_rotation=False`，不要用三基准面把轴、齿轮、上盖完全锁死。
4. 齿轮传动用真实 Gear Mate，不用脚本假动画冒充机械配合。
5. 创建后用 `collect_mate_feature_summary()` 或特征树遍历验证 MateGroup 下存在 `MateConcentric`、`MateGearDim` 等真实 Mate 特征。
6. 需要真实运动算例时，优先复用 `sw_motion.create_motion_study()`、`add_constant_speed_rotary_motor_by_cylinders()`、`calculate_and_play()` 创建 Motion Study 和马达。
7. 计算后调用 `sw_motion.validate_motion_studies()` 或 MCP `solidworks_validate_motion_study`，检查类型、时长、马达数量、结果存在性和 `results_out_of_date=False`；只看到时间轴、动画或 `Calculate=True` 不算验收通过。
8. 需要演示动画时可以额外脚本驱动组件位姿或 Mate Controller，但必须说明动画演示不等同于交互自由度；最终以 SolidWorks 中可拖动为准。

## GPT / Kimi / Claude 多模型策略

当代理需要让大模型生成 VBA 宏时，必须通过 `scripts/sw_macro_guard.py`：

1. **模型分流**：GPT 系列使用原有简洁提示词；Kimi / Claude / 未知模型自动加载强格式约束 Prompt，强制只输出 VBA 源码。
2. **本地模板兜底**：模型输出失败或解析失败时，不直接报错；按用户关键词（如“立方体”“圆柱”“拉伸”“草图”）选择内置 VBA 模板继续执行。
3. **输出校验**：执行前检查 `SldWorks`、`ModelDoc2`、`Sub`、`End Sub`，通过后才允许交给 SolidWorks；不通过则重试。
4. **超时/重试**：单次模型请求建议 `30s` 超时；解析失败自动重试 `1~2` 次，重试 Prompt 追加更强格式指令。

示例：

```python
from sw_macro_guard import build_prompt, fallback_macro_for_request, validate_vba_macro

prompt = build_prompt("画一个 50mm 圆柱", model_name="claude")
macro = fallback_macro_for_request("画一个 50mm 圆柱")
result = validate_vba_macro(macro)
assert result.ok, result.issues
```

## 未封装 API 规则

当任务需要调用 `scripts/` 中尚未封装的 SolidWorks API 时：

1. 先读取 `references/api-lookup.md`，再查询 SolidWorks 官方 API 文档，或本地 SolidWorks SDK / 参考资料，确认方法签名、参数含义、枚举值、返回值和版本差异。
2. 禁止凭记忆猜接口；尤其是长参数 COM 方法、`VARIANT` / by-ref 参数、枚举值、选择标记和 `SaveAs` 类接口。
3. 写代码时保留最小可运行脚本，并对每一步返回值做 `None` / `False` 检查。
4. 实现后必须真实运行，保存或导出目标文件，并使用 `sw_review.py` 生成预览图与审查报告。
5. 新发现的坑、错误码、兼容写法或稳定封装，要补充到 `references/troubleshooting.md` 或对应模块参考文档；常用逻辑再沉淀进 `scripts/`。

## 结果自审查

每次生成、修改、导入或导出 CAD 后都要做自审查，除非用户明确说不需要：

1. 检查 COM 返回值、特征对象、保存/导出返回值和输出文件大小。
2. 调用 `model.ForceRebuild3(False)`、`model.ViewZoomtofit2()` 刷新模型。
3. 用 `scripts/sw_review.py` 的 `run_review()` 导出 `isometric/front/top/right` 预览图并写入 `*_review_report.json`。
4. 读取报告里的 `evaluation.status`、`evaluation.issues`、`checks` 和预览图；通过截图或导出的 BMP 检查：主体是否存在、比例/方位是否合理、关键部件是否缺失、是否明显重叠或悬空、文件名和输出路径是否正确。
5. 若发现问题，先修脚本并重新生成，再汇报；不要只报告“保存成功”。

示例：

```python
from sw_review import run_review

model.ForceRebuild3(False)
report, report_path = run_review(
    model,
    r"C:\temp\review",
    basename="car",
    expected_outputs=[r"C:\temp\car.sldprt", r"C:\temp\car.step"],
)
print(report_path)
print(report["evaluation"])
```

## 关键注意事项

- **单位**：API 统一使用**米**。用 `mm(50)` 转换 50mm 为 0.05m，用 `deg(90)` 转换角度
- **版本**：使用 `SldWorks.Application` 自动连接，兼容所有版本
- **选择**：能拿到 COM 对象时优先用对象级 `Select2()`；基准面可用 `SelectByID2("PLANE")`，草图不要只依赖 `SelectByID2("SKETCH")`
- **草图**：推荐用 `with sketch(model, "Front Plane") as sketch_name:` 自动进入/退出草图；`sw_part.py` 会缓存草图对象引用，避免 SW2024 中文版按名称选择草图失败
- **添加组件**：装配体优先用 `sw_assembly.add_component()`；SW2024 中文版下 `AddComponent4` 可能返回 `None`，封装会用 `AddComponent5`、静默打开零件、重新激活装配体后重试
- **外观**：对颜色要求高的模型优先拆成多零件装配体；材质数组必须用 `SAFEARRAY(double)` 编组，并回读 RGB 验证
- **VARIANT**：by-ref 参数必须用 `VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)` 包装
- **基准面名称**：`start_sketch()` 会自动兼容英文版 "Front/Top/Right Plane" 与中文版 "前视/上视/右视基准面"
- **草图坐标**：基于草图平面的局部坐标系，单位为米
- **运动装配**：先解析组件再选 Mate 实体；`GetCorresponding()` 用于把零件内面/特征映射到装配体上下文；同心 Mate 默认不锁旋转
- **Motion Study**：`swmotionstudy.tlb` 需加载；pywin32 下 `CreateMotionStudy` / `Activate` / `Calculate` 可能表现为属性，优先用 `sw_motion.motion_member()` 兼容
