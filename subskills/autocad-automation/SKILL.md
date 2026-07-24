---
name: autocad-automation
description: "AutoCAD 自动化技能。用于让 Codex/Claude 在 Windows 上通过 Python COM/ActiveX 直连本机 AutoCAD 进行二维绘图、图层/文字/标注/块处理、DWG/DXF/PDF 导出、批量修改、工程图自检，以及在 COM 不足时切换到 AutoLISP/SCR 或 AutoCAD .NET 插件路线；当用户提到 AutoCAD、CAD、DWG、DXF、画图、出图、图层、标注、块、批量改图、AutoLISP、ObjectARX、.NET 插件、Codex 接入 CAD 软件时都应优先使用。"
metadata: { "os": ["win32"], "requires": { "anyBins": ["python", "py"], "pythonPackages": ["pywin32"] } }
---

# AutoCAD 自动化技能

> 本目录作为 `solidworks-automation-skill` 的 AutoCAD/DWG 子技能使用。父技能负责 SolidWorks 建模、装配、工程图和三维导出；本子技能负责 AutoCAD 二维 DWG/DXF 绘制、批量改图、线稿矢量化、出图预览和图纸自检。涉及 SolidWorks 原生零件/装配体建模时回到父技能，涉及 AutoCAD 图纸或 DWG/DXF 时读取本子技能。

## 目标

让代理在本机 Windows 桌面环境中可靠控制 AutoCAD，而不是每次凭记忆临时拼命令。默认路线是 Python + COM/ActiveX 直连正在运行或新启动的 `AutoCAD.Application`，并且默认把 AutoCAD 窗口切到前台、逐步绘制，让用户能直接看到画图过程；适合快速建图、批量修改、导入导出和检查 DWG。遇到 COM 无法稳定表达的事务、动态交互、复杂数据库遍历或企业级部署时，再切换到 AutoLISP/SCR、AutoCAD .NET、ObjectARX 或 APS Design Automation。

## 适用场景

使用本技能处理：

- 新建或修改 DWG/DXF 图纸，绘制线、圆、圆弧、多段线、矩形、文字、块、图层和简单标注。
- 批量打开 DWG，检查图层、实体数量、文字、块参照、外部参照或输出文件。
- 让 Codex 直接连接本机 AutoCAD、保存 DWG、导出 DXF/PDF，并生成复核报告。
- 编写 AutoLISP、`.scr` 命令脚本或 C# AutoCAD .NET 插件。
- 需要查 Autodesk 官方 API、ADN/GitHub 示例、ObjectARX SDK 或 APS Design Automation 模式。

不要把本技能用于纯渲染效果图、BIM/Revit 模型、机械 STEP-first 建模、CAM 刀路或工程认证结论；这些需求优先转给相应 CAD、BIM、仿真或制造流程。

## 默认假设

- 操作系统：Windows。
- AutoCAD：用户本机已安装，最好已手动启动一次完成 COM 注册。
- 自动化入口：`AutoCAD.Application` COM ProgID。
- 可视化默认：新建绘图任务默认先显示并激活 AutoCAD，再逐步落图元；只有批处理或用户明确要求提速时才关闭。
- 绘图单位：默认按毫米理解；AutoCAD 数据库本身是无单位数值，必须在图纸说明中记录单位。
- 空间：几何默认进入 ModelSpace；版面、标题栏和打印配置单独处理。
- 坐标：默认 WCS，二维对象使用 `Z=0`。
- 输出：优先保存 DWG，同时按用户需求导出 DXF/PDF；所有输出路径使用绝对路径。
- 文件安全：修改既有 DWG 前先另存副本，除非用户明确允许覆盖。

缺少版本、单位、图纸标准、输出路径或是否允许覆盖时，先做一次简短确认。简单草图可以直接假设毫米、ModelSpace、新建 DWG，并在结果中说明。

## 入口自检

执行 AutoCAD 自动化前先运行：

```powershell
python subskills\autocad-automation\scripts\acad_preflight.py
```

如果用户允许自动启动 AutoCAD：

```powershell
python subskills\autocad-automation\scripts\acad_preflight.py --launch
```

自检失败时：

- 缺 `pywin32`：提示用户安装 `python -m pip install pywin32`，得到明确同意后再安装。
- 找不到 AutoCAD COM：提示用户安装 AutoCAD、启动一次 AutoCAD，或确认安装的是 LT/受限环境。
- AutoCAD 已运行但无活动文档：可以新建文档，不要误判为连接失败。

## 核心工作流

1. **分类任务**：判断是新建图纸、修改既有 DWG、批处理、出图导出、API 开发、插件开发还是故障排查。
2. **确认关键约束**：单位、版本、目标文件、输出格式、是否允许覆盖、图层/线型/标注标准、是否需要按企业模板绘图。
3. **运行自检**：先用 `acad_preflight.py` 确认 Python COM 和 AutoCAD 状态。
4. **查证 API**：未封装 API 必须先读 `references/api-lookup.md`，再查 Autodesk 官方文档或可信 GitHub 示例；不要猜长参数、枚举值和命令行为。
5. **制定绘图计划**：写明图层、坐标基准、对象清单、尺寸、文本、输出路径和复核点。
6. **先把软件拉起来**：连接或启动 AutoCAD，确保窗口可见并尽量切到前台，再开始落图。
7. **优先复用脚本**：简单几何用 `scripts/acad_draw.py` 的 JSON 输入；复杂逻辑用 `scripts/acad_session.py` 组合 COM 调用。
8. **串行执行 COM**：AutoCAD 桌面 COM 操作不要并行；一个脚本连接、逐步绘制、保存、复核后退出。
9. **保存和导出**：保存 DWG/DXF/PDF 前确保目录存在；修改原图时保留备份或另存。
10. **复核结果**：运行 `scripts/acad_review.py` 统计实体、图层、包围盒和目标文件；再运行 `scripts/acad_preview.py` 导出 AutoCAD 原生 BMP/PNG 预览，并用图片查看工具做视觉审查。窗口截图可作为补充，但若被其它窗口遮挡，不可作为通过依据。
11. **沉淀经验**：遇到新坑、命令差异、版本限制或稳定封装，补进 `references/troubleshooting.md` 或脚本。

### 机械零件图和 3D 打印开孔图硬性要求

当用户要求“严格遵守规范”“中国人正常喜欢的格式”“国标图纸”“加工图”“3D打印开孔”或类似机械制图交付时，必须按机械图纸而不是示意图处理：

1. 优先使用用户或企业模板；没有模板时，按国内常用 GB/T 风格出图，至少包含 A3/A4 图幅、装订边、右下标题栏、仿宋中文、粗实线/细实线/中心线/虚线/尺寸/文字/开孔分层，并在交付说明中写清“参照国标风格，未替代企业审图”。
2. 所有实际切除、开孔、开槽、接口、水口、螺丝孔和螺丝柱必须同时给出规格和定位尺寸。仅写 `4×φ3.4`、`7×4×30`、`2×φ13.5` 而没有相对基准边、中心距、节距或高度定位，视为未完成。
3. 孔槽密集或会造成长引线跨视图时，优先使用“孔槽明细表/孔表/槽表”，表内至少包含部位、规格、数量和定位；图面尺寸线负责关键基准、中心距和总尺寸。
4. 不允许用随意长引线替代尺寸链；引线不得穿越其它视图、中心线、孔轮廓或尺寸文字。无法清爽标注时，移动视图、拆分视图或改用表格。
5. 3D 打印外壳图必须标清壁厚、底厚、外形总尺寸、接口开孔尺寸、接口中心定位、装配孔中心距和水口/散热槽定位；否则用户无法按图开孔。
6. 标注必须优先使用 AutoCAD 真实尺寸实体，例如 `AcDbRotatedDimension`，不要手画尺寸线冒充尺寸。
7. 视觉验收不能只看实体统计。必须导出预览并目视检查：尺寸是否漏标、文字是否重叠、尺寸线是否压视图、引线是否跨视图、孔表是否可读、标题栏是否被尺寸侵入。发现问题先返工再汇报。

## Codex 直连绘图

简单任务可让 Codex 生成一个绘图 JSON，然后调用：

```powershell
python subskills\autocad-automation\scripts\acad_draw.py `
  --input C:\temp\plate_plan.json `
  --output C:\temp\plate.dwg `
  --new
```

这个入口默认是“可见逐步绘图”模式：会先打开或切到 AutoCAD，再一点点把图元画出来。只有批量任务、回放太慢或用户明确要求快时，才加 `--fast`：

```powershell
python subskills\autocad-automation\scripts\acad_draw.py `
  --input C:\temp\batch_plan.json `
  --output C:\temp\batch.dwg `
  --new `
  --fast
```

JSON 结构示例：

```json
{
  "units": "mm",
  "live_preview": true,
  "live_zoom_every": 6,
  "layers": [
    {"name": "OUTLINE", "color": 7},
    {"name": "CENTER", "color": 1},
    {"name": "TEXT", "color": 3}
  ],
  "entities": [
    {"type": "rectangle", "origin": [0, 0], "width": 120, "height": 80, "layer": "OUTLINE"},
    {"type": "circle", "center": [20, 20, 0], "radius": 4.5, "layer": "CENTER"},
    {"type": "text", "text": "MOUNTING PLATE", "point": [8, 88, 0], "height": 5, "layer": "TEXT"}
  ]
}
```

复杂任务使用 Python：

```python
import sys
sys.path.insert(0, r"subskills\autocad-automation\scripts")
from acad_session import AutoCADSession

session = AutoCADSession(create_if_missing=True, visible=True).connect()
session.new_document()
session.activate_window()
session.create_layer("OUTLINE", color=7)
session.add_rectangle((0, 0), width=120, height=80, layer="OUTLINE")
session.live_update(step_delay_s=0.15, zoom=True)
session.save_as(r"C:\temp\plate.dwg")
```

## 技术路线选择

| 需求 | 首选路线 | 说明 |
|---|---|---|
| 快速绘制、改图、批量检查 | Python COM/ActiveX | 本技能默认路线，可由 Codex 直接通过 shell 执行 |
| 执行 AutoCAD 命令、调用已有命令习惯 | `SendCommand` / `.scr` / AutoLISP | 命令可能异步，必须保存和复核结果 |
| 大量数据库事务、复杂选择过滤、插件菜单 | AutoCAD .NET | 适合 C# 插件，按官方 .NET Developer Guide 做事务和文档锁 |
| 高性能原生扩展、深层数据库/图形系统 | ObjectARX C++ | 成本高，版本绑定强，先确认必要性 |
| 云端批处理 DWG | APS Design Automation | 适合无桌面、批量生产或 CI，但需要 Autodesk APS 凭据 |

## 工程规则

- 图层先建后画，颜色用 ACI 编号；不要把所有对象堆到 `0` 层。
- 明确单位和比例，模型空间画 1:1；打印比例放到 Layout/Plot。
- 坐标、尺寸、文字高度、孔径等关键参数写成变量，不把魔法数字散在代码里。
- 机械图纸不要把“看得懂”当成“能制造”。开孔开槽必须有可复核基准和完整定位尺寸；图面空间不足时用孔表/槽表，不要用飞线式引出文字糊弄。
- 根据图片生成线稿时，普通“照图画 CAD”的最终交付必须以原图矢量化线条为准。不要用大弧线、长折线、椭圆、三角形、彩色水波线、替代文字等手工猜测元素去补人物轮廓、五官、Logo、衣纹或水花；这些线容易像错误的 CAD 辅助线，用户会把它们理解成“这都是啥”。
- 如果为了定位、调试或临时增强识别绘制了 `BODY_OUTLINE`、`JERSEY_OUTLINE`、`PORTRAIT_OUTLINE`、`OUTER_GUIDE`、`CONSTRUCTION`、`FACE_FEATURES`、`LOGO_GEOMETRY`、`WATER_SPLASH`、`JERSEY_STRIPE`、`TEXT_LOGO`、`TEXT_BRAND` 等构造/增强层，最终保存、预览和评分前必须删除、冻结、关闭或设为不打印，并在预览和图层统计中确认不可见、实体数为 0。
- 只有当用户明确要求“重构标识”“增强五官”“补画水花”“加文字/标注”等创作型改图时，才可保留手工增强层；保留前要说明这些不是原图自然矢量线，并优先用独立图层，便于一键关闭。
- 审查说明、评分、生成参数放到 JSON/Markdown 报告，不要作为可见文字写入最终 CAD 模型空间，除非用户明确要求图内标注。
- COM 返回对象要检查，保存/导出后检查文件是否存在和大小是否合理。
- `SendCommand` 是最后手段；优先调用对象模型方法，命令脚本要用 `_.COMMAND` 形式降低界面语言影响。
- 用户明确说“我要看着它画”时，不要后台闷头生成；先把 AutoCAD 打开并前置，再逐步落图元。
- SelectionSet 名称可能残留；创建前先删除同名选择集。
- 批处理 DWG 时每张图单独 try/finally，失败要记录文件名、错误和阶段。
- 对用户原图默认只读打开或另存副本；覆盖必须得到明确授权。
- 不把任意 Python/VBA/AutoLISP 执行口暴露成通用 MCP 工具；如做 MCP，只提供白名单绘图/导出/复核工具。

## GitHub 与官方文档策略

优先来源：

- Autodesk AutoCAD API 概览、ActiveX/VBA、Managed .NET、ObjectARX 和 APS 官方文档。
- ADN-DevTech / Autodesk Platform Services GitHub 示例。
- `pyautocad` 等成熟开源项目可借鉴坐标、迭代和 COM 封装模式，但不要复制不明许可证代码。
- 论坛、博客和 Stack Overflow 只作排错补充；关键 API 仍回到官方文档确认。

当资料冲突时，以目标 AutoCAD 版本的官方文档和本机实测结果为准。

## 渐进参考

按需读取，不要一次塞满上下文：

- `references/api-lookup.md`：官方文档、GitHub 示例和 API 查证路线。
- `references/engineering-patterns.md`：资深工程师绘图、图层、单位、块、标注和批处理经验。
- `references/troubleshooting.md`：COM、AutoCAD 会话、SendCommand、保存导出和版本问题排查。

## 验收与汇报

完成 AutoCAD 操作后，最终回复要包含：

- 输入假设：单位、版本、模板、是否新建/修改原图。
- 输出文件：DWG/DXF/PDF/JSON 报告和 BMP/PNG 预览的绝对路径。
- 实际执行的验证：自检、实体统计、图层统计、包围盒、保存/导出检查、AutoCAD 原生预览图审查；根据图片生成线稿时，还要确认最终预览中没有额外外围辅助轮廓线、内部辅助几何、彩色装饰线或图内审查说明显示；若使用窗口截图，还要说明是否无遮挡。
- 仍需人工确认的事项：图框、打印机、企业标准、线宽、字体、比例、专业审图。
