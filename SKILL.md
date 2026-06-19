---
name: solidworks-automation
description: "SolidWorks CAD 自动化技能，可通过 Python COM 接口与 OpenClaw / Codex / Claude 协作控制 Windows 上运行的 SolidWorks，用于零件建模、装配体、工程图、钣金、焊件、仿真、文件导出、自定义属性、设计表与配置管理；当用户提到 SolidWorks、SW、OpenClaw、龙虾、3D 建模、CAD、零件、装配、工程图、钣金、焊件、导出 STEP/STL/PDF、BOM、设计表或 FEA 仿真等需求时使用。"
metadata: { "openclaw": { "homepage": "https://github.com/wzyn20051216/solidworks-automation-skill", "os": ["win32"], "requires": { "anyBins": ["python", "py"] } } }
---

# SolidWorks 自动化技能

## 快速开始

### 环境要求

- Windows 系统 + SolidWorks 已安装并运行
- Python 3.8+ + `pywin32` / `comtypes`
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
| 多模型宏生成防护 | `scripts/sw_macro_guard.py` | `references/openclaw.md` |
| 友好会话 API | `scripts/sw_session.py` | - |
| 连接与文档管理 | `scripts/sw_connect.py` | - |
| 外观与材质 | `scripts/sw_appearance.py` | `references/appearance.md` |
| 零件建模（草图+特征） | `scripts/sw_part.py` | `references/part-modeling.md` |
| 多圆角/倒角 CNC 机加工件 | `subskills/solidworks-fillet-chamfer-cnc/scripts/create_cnc_mount_template.py` | `subskills/solidworks-fillet-chamfer-cnc/SKILL.md`、`subskills/solidworks-fillet-chamfer-cnc/references/cnc-fillet-chamfer-lessons.md` |
| 螺丝孔/螺纹孔、攻丝底孔 | `subskills/solidworks-threaded-holes/scripts/create_threaded_hole_template.py` | `subskills/solidworks-threaded-holes/SKILL.md`、`subskills/solidworks-threaded-holes/references/threaded-hole-lessons.md` |
| 装配体操作、齿轮/铰链/可拖动运动配合 | `scripts/sw_assembly.py` | `references/assembly.md` |
| Motion Study 运动算例与旋转马达 | `scripts/sw_motion.py` | `references/motion-study.md` |
| 工程图出图 | `scripts/sw_drawing.py` | `references/drawing.md` |
| 文件导出 | `scripts/sw_export.py` | `references/export.md` |
| 结果自审查 | `scripts/sw_review.py` | `references/review.md` |
| 本地 MCP Server | `mcp-server/server.py` | `mcp-server/README.md`、`references/mcp-server.md` |
| MCP 协议验证 | `scripts/validate_mcp.py` | `mcp-server/README.md` |
| 未封装 API 查证 | - | `references/api-lookup.md` |
| OpenClaw 控制 SolidWorks | - | `references/openclaw.md` |
| 钣金/焊件/仿真/属性 | - | `references/advanced.md` |
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
4. 圆角/倒角很多的 CNC 件、安装座、连接块、支架，先读取 `subskills/solidworks-fillet-chamfer-cnc/SKILL.md`，按“基础体 -> 外轮廓圆角/倒角 -> 孔槽切除 -> 孔口倒角 -> 审查”的稳定顺序执行。
5. 螺丝孔、螺纹孔、攻牙孔、M3/M4/M5/M6/M8 盲孔或通孔任务，先读取 `subskills/solidworks-threaded-holes/SKILL.md`；默认按“攻丝底孔 -> 尝试 Thread/CosmeticThread -> 可见 3D 螺旋线兜底 -> 孔口倒角 -> 属性和审查”的稳定路线执行。
6. 如果必须由大模型生成 VBA 宏，先使用 `sw_macro_guard.py` 做模型分流、代码校验、重试和本地模板兜底。
7. 使用 `session.export()` 或 `sw_export.py` 保存/导出文件。
8. 使用 `sw_review.py` 导出预览图并自审查；如果有 GUI/桌面截图能力，打开 SolidWorks 视图截图复核。

### MCP Server 使用

当用户要求“让 SolidWorks 支持 MCP”“接入 Codex/Claude Desktop 工具调用”“不要每次生成一大段 Python 脚本”时：

1. 读取 `mcp-server/README.md`。
2. 若用户要求自动配置 MCP，优先运行多客户端注册器：`powershell -ExecutionPolicy Bypass -File mcp-server/register_all_ai_mcp.ps1 -InstallDependencies`；它会尝试注册 Codex、Claude Code、Claude Desktop、Cursor、Windsurf。
3. 使用本地 `stdio` MCP server：`python mcp-server/server.py`。
4. 工具调用优先走 `solidworks_health_check`、`solidworks_create_basic_part`、`solidworks_add_component`、`solidworks_add_coincident_mate`、`solidworks_add_distance_mate`、`solidworks_add_concentric_mate`、`solidworks_set_component_fixed`、`solidworks_export_active`、`solidworks_review_active`、`solidworks_add_rotary_motor`。
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
7. 需要演示动画时可以额外脚本驱动组件位姿或 Mate Controller，但必须说明动画演示不等同于交互自由度；最终以 SolidWorks 中可拖动为准。

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
- **外观**：对颜色要求高的模型优先拆成多零件装配体，并用 `sw_appearance.py` 设置文档级或组件级外观
- **VARIANT**：by-ref 参数必须用 `VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)` 包装
- **基准面名称**：`start_sketch()` 会自动兼容英文版 "Front/Top/Right Plane" 与中文版 "前视/上视/右视基准面"
- **草图坐标**：基于草图平面的局部坐标系，单位为米
- **运动装配**：先解析组件再选 Mate 实体；`GetCorresponding()` 用于把零件内面/特征映射到装配体上下文；同心 Mate 默认不锁旋转
- **Motion Study**：`swmotionstudy.tlb` 需加载；pywin32 下 `CreateMotionStudy` / `Activate` / `Calculate` 可能表现为属性，优先用 `sw_motion.motion_member()` 兼容
