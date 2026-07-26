# CAD 自动化交付工作台 MVP 产品规格

版本: v0.1  
日期: 2026-07-25  
关联调研: `docs/market-research-2026.md`

## 1. 产品定位

产品名暂定:

```text
CAD 自动化交付工作台
```

一句话:

```text
面向机械工程师和 3D 打印打样用户，把常见结构件从参数输入到建模、出图、规范复核和交付归档做成一个本地软件流程。
```

第一版不做新 CAD，不做云端协同，不做完整 PLM。第一版只解决一个真实闭环:

```text
3D 打印外壳自动交付
```

## 2. MVP 成功标准

用户能在本地 Windows 电脑上完成:

1. 新建一个 3D 打印外壳项目。
2. 填写外形、壁厚、孔、槽、螺丝柱、接口等参数。
3. 调用 SolidWorks 自动生成真实切除的 3D 模型。
4. 调用 SolidWorks Drawing 或 AutoCAD 生成工程图。
5. 自动检查图纸是否满足 P0 规范。
6. 输出一个完整交付包。

### 验收指标

| 指标 | MVP 目标 |
|---|---|
| 项目创建到参数确认 | 5 分钟内 |
| 建模脚本执行 | 10 分钟内 |
| 工程图初稿生成 | 5 分钟内 |
| P0 图纸漏标 | 必须为 0 |
| 输出文件可追溯 | 每个文件在 manifest 中有记录 |
| 失败可定位 | 每个失败必须给出阶段、原因、建议 |

## 3. 技术边界

### 必须本地运行

不租服务器，不依赖云端任务队列。所有 CAD 文件、参考图、参数和复核报告都保存在用户本机。

推荐技术栈:

```text
桌面界面: PySide6 / Qt
自动化脚本: Python + pywin32/comtypes
CAD 控制: SolidWorks COM + AutoCAD COM
项目数据: 本地 JSON / Markdown / 文件夹
打包: PyInstaller
版本更新: GitHub 仓库
```

### 不做的功能

- 不做 CAD 几何内核。
- 不做浏览器网页服务。
- 不做多人协作。
- 不做账号系统。
- 不做任意复杂零件的全自动生成承诺。
- 不做企业 PDM/PLM 集成。
- 不开放任意 Python/VBA/AutoLISP 执行口给普通用户。

## 4. 第一版用户画像

### 主要用户

个人机械设计师、自动化设备工程师、创客、3D 打印打样用户。

他们最关心:

- 是否真的能开孔。
- 是否能直接 3D 打印。
- 图纸是否按中国工程师习惯出。
- 孔位、槽位、接口是否标完整。
- 文件是否能直接发给加工/打印/客户。

### 使用前提

用户本机需要:

- Windows。
- SolidWorks 已安装并至少启动过一次。
- AutoCAD 已安装并至少启动过一次，若只做 SolidWorks Drawing 可暂不强制。
- Python 3.8+。
- `pywin32` / `comtypes`。

## 5. 信息架构

桌面软件第一版采用左侧导航 + 中央任务表单 + 右侧复核/输出面板。

```text
┌────────────────────────────────────────────────────────────────┐
│ CAD 自动化交付工作台                                            │
├──────────────┬──────────────────────────┬──────────────────────┤
│ 项目          │ 任务: 3D 打印外壳          │ 复核状态              │
│ 新建项目      │                          │ P0 规范检查            │
│ 参数模板      │ 外形尺寸 / 开孔 / 螺丝柱   │ 输出文件              │
│ 生成模型      │ 工程图 / 技术要求          │ 执行日志              │
│ 生成图纸      │                          │                      │
│ 规范复核      │ [保存参数] [生成模型]      │ [打开输出目录]        │
│ 输出交付      │ [生成图纸] [一键复核]      │                      │
│ Skills 管理   │                          │                      │
└──────────────┴──────────────────────────┴──────────────────────┘
```

## 6. 核心流程

### 6.1 新建项目

用户输入:

- 项目名称。
- 项目类型: `3d_print_shell`。
- 输出目录。
- 单位: 默认 `mm`。
- 图纸风格: 默认 `GB/T 风格`。
- 是否需要 AutoCAD DWG/DXF: 默认需要。
- 是否需要 SolidWorks 原生工程图: 可选。

系统动作:

1. 创建项目目录。
2. 写入 `project.json`。
3. 创建 `inputs/`、`outputs/`、`reviews/`、`previews/`、`logs/`。
4. 检查 SolidWorks/AutoCAD/Python 依赖。

### 6.2 上传参考图

支持:

- `jpg`
- `png`
- `jpeg`
- `bmp`

用途:

- 作为外观参考。
- 辅助填写孔位和接口位置。
- 不直接作为可制造尺寸依据。

规则:

参考图不能替代尺寸。任何孔、槽、接口、水口、螺丝孔、螺丝柱都必须在参数表中有规格和定位。

### 6.3 填写参数

采用结构化表单，prompt 只作为补充说明。

必填区域:

- 外形尺寸。
- 壁厚/底厚。
- 圆角/倒角。
- 开孔/开槽。
- 螺丝柱/安装孔。
- 工程图设置。
- 技术要求。

### 6.4 生成模型

系统动作:

1. 读取 `parameters.json`。
2. 生成或调用 SolidWorks 建模脚本。
3. 建立外壳主体。
4. 做壳体抽壳或布尔切除。
5. 对所有孔、槽、接口做真实切除。
6. 添加螺丝柱、加强筋、圆角/倒角。
7. 保存 `SLDPRT`。
8. 导出 `STEP` 和 `STL`。
9. 执行模型复核。

必须检查:

- 模型非空。
- 外形尺寸符合参数。
- 壁厚存在。
- 孔/槽数量和参数表一致。
- 孔/槽不是草图装饰线，而是真实切除。
- STL 文件存在且大小合理。

### 6.5 生成工程图

支持两条路线:

| 路线 | 场景 |
|---|---|
| SolidWorks Drawing | 从模型生成三视图/等轴测、尺寸、PDF |
| AutoCAD DWG/DXF | 生成国内常用 DWG/DXF 工程图、孔槽表、标题栏 |

MVP 优先保证 AutoCAD DWG/DXF 工程图，因为用户明确要求中国常用格式和严格标注规范。

工程图必须包含:

- 图框。
- 标题栏。
- 单位。
- 比例。
- 主视图。
- 俯视图。
- 右视图或必要剖视图。
- 等轴测参考图。
- 外形总尺寸。
- 壁厚/底厚。
- 孔槽规格和数量。
- 孔槽定位尺寸。
- 技术要求。
- 孔槽明细表。

### 6.6 规范复核

复核分为机器检查和目视检查。

机器检查:

- 文件是否存在。
- DWG/DXF 包围盒是否合理。
- 图层是否齐全。
- 尺寸实体数量是否达标。
- 孔槽实体数量是否和参数一致。
- 标题栏是否存在。
- 孔槽明细表是否存在。
- review.json schema 是否完整。

目视检查:

- 尺寸线是否压图。
- 引线是否跨视图。
- 文字是否重叠。
- 标题栏是否被侵入。
- 孔槽定位是否能读懂。
- 图纸是否像中国机械工程师会接受的样子。

## 7. 页面规格

### 7.1 首页 / 项目列表

显示:

- 最近项目。
- 项目名称。
- 类型。
- 最近修改时间。
- 最后一次状态。
- 输出目录。

操作:

- 新建项目。
- 打开项目。
- 打开输出目录。
- 复制项目。
- 删除项目记录，不删除源文件，除非用户明确选择删除文件。

### 7.2 新建项目页

字段:

| 字段 | 类型 | 默认值 | 必填 | 说明 |
|---|---|---|---|---|
| project_name | text | 空 | 是 | 项目名称 |
| project_type | select | 3D 打印外壳 | 是 | MVP 只有一种 |
| output_root | folder | 用户选择 | 是 | 输出根目录 |
| unit | select | mm | 是 | 暂只支持 mm |
| drawing_standard | select | GB/T 风格 | 是 | 后续可扩展企业模板 |
| need_dwg | checkbox | true | 否 | 输出 DWG |
| need_dxf | checkbox | true | 否 | 输出 DXF |
| need_pdf | checkbox | true | 否 | 输出 PDF |
| need_stl | checkbox | true | 否 | 输出 STL |
| need_step | checkbox | true | 否 | 输出 STEP |

### 7.3 参数填写页

#### 外形参数

| 字段 | 类型 | 单位 | 必填 | 校验 |
|---|---|---|---|---|
| outer_length | number | mm | 是 | > 0 |
| outer_width | number | mm | 是 | > 0 |
| outer_height | number | mm | 是 | > 0 |
| wall_thickness | number | mm | 是 | >= 0.8 |
| bottom_thickness | number | mm | 是 | >= 0.8 |
| corner_radius | number | mm | 否 | >= 0 |
| edge_chamfer | number | mm | 否 | >= 0 |
| shell_open_direction | select | - | 是 | top / bottom / side |

#### 3D 打印参数

| 字段 | 类型 | 单位 | 默认 | 说明 |
|---|---|---|---|---|
| print_process | select | - | FDM | FDM / SLA / SLS，MVP 优先 FDM |
| nozzle_diameter | number | mm | 0.4 | FDM 喷嘴 |
| hole_compensation | number | mm | 0.2 | 孔径放量建议 |
| fit_clearance | number | mm | 0.3 | 装配间隙 |
| min_wall_warning | number | mm | 1.2 | 低于则警告 |

#### 孔参数

所有孔必须有:

- 类型。
- 规格。
- 数量。
- 所在面。
- 基准边。
- 中心定位。

字段:

| 字段 | 类型 | 单位 | 必填 | 说明 |
|---|---|---|---|---|
| id | text | - | 是 | 如 H1 |
| name | text | - | 是 | 如 显示屏安装孔 |
| hole_type | select | - | 是 | round / counterbore / countersink / threaded / slot |
| face | select | - | 是 | front / back / left / right / top / bottom |
| diameter | number | mm | 条件 | 圆孔直径 |
| width | number | mm | 条件 | 槽宽 |
| length | number | mm | 条件 | 槽长 |
| quantity | number | 个 | 是 | >= 1 |
| datum_x | select | - | 是 | left / right / centerline |
| datum_y | select | - | 是 | bottom / top / centerline |
| center_x | number | mm | 是 | 相对 X 基准 |
| center_y | number | mm | 是 | 相对 Y 基准 |
| pitch_x | number | mm | 条件 | 多孔横向节距 |
| pitch_y | number | mm | 条件 | 多孔纵向节距 |
| through | checkbox | - | 是 | 是否通孔 |
| note | text | - | 否 | 工艺备注 |

#### 接口开孔

接口孔属于孔槽硬规则，不能只写文字说明。

常见类型:

- USB-C。
- DC 圆孔。
- HDMI。
- RJ45。
- 按键孔。
- 指示灯孔。
- 屏幕窗口。
- 水口。
- 散热槽。

接口字段:

| 字段 | 类型 | 单位 | 必填 |
|---|---|---|---|
| id | text | - | 是 |
| interface_type | select | - | 是 |
| face | select | - | 是 |
| cutout_width | number | mm | 条件 |
| cutout_height | number | mm | 条件 |
| cutout_diameter | number | mm | 条件 |
| corner_radius | number | mm | 否 |
| center_x | number | mm | 是 |
| center_y | number | mm | 是 |
| quantity | number | 个 | 是 |
| clearance | number | mm | 否 |

#### 螺丝柱参数

| 字段 | 类型 | 单位 | 必填 | 说明 |
|---|---|---|---|---|
| id | text | - | 是 | 如 B1 |
| screw_size | select | - | 是 | M2 / M2.5 / M3 / M4 |
| boss_outer_diameter | number | mm | 是 | 螺丝柱外径 |
| hole_diameter | number | mm | 是 | 螺丝孔或预埋孔 |
| boss_height | number | mm | 是 | 螺丝柱高度 |
| face | select | - | 是 | 所在面 |
| center_x | number | mm | 是 | X 定位 |
| center_y | number | mm | 是 | Y 定位 |
| quantity | number | 个 | 是 | 数量 |
| rib_enabled | checkbox | - | 否 | 是否加加强筋 |

### 7.4 生成执行页

显示阶段:

```text
preflight -> build_model -> export_model -> build_drawing -> export_drawing -> review -> package
```

每个阶段显示:

- 状态: waiting / running / passed / warning / failed。
- 开始时间。
- 结束时间。
- 日志摘要。
- 失败原因。
- 建议动作。

### 7.5 复核报告页

分四块:

1. 模型复核。
2. 图纸复核。
3. 3D 打印复核。
4. 交付包复核。

状态:

- `pass`: 可交付。
- `warning`: 可交付但需要人工确认。
- `fail`: 不可交付，必须返工。

P0 规则失败时，总状态必须为 `fail`。

## 8. 项目目录结构

每个项目保存为独立文件夹:

```text
<output_root>/<project_slug>/
├── project.json
├── parameters.json
├── inputs/
│   ├── reference_001.png
│   └── brief.md
├── generated/
│   ├── build_model.py
│   ├── build_drawing.py
│   └── drawing_plan.json
├── outputs/
│   ├── model/
│   │   ├── <project>.sldprt
│   │   ├── <project>.step
│   │   └── <project>.stl
│   ├── drawing/
│   │   ├── <project>.dwg
│   │   ├── <project>.dxf
│   │   └── <project>.pdf
│   └── package/
│       └── <project>_delivery.zip
├── previews/
│   ├── model_iso.png
│   ├── model_front.png
│   ├── drawing_preview.png
│   └── package_cover.png
├── reviews/
│   ├── model_review.json
│   ├── drawing_review.json
│   ├── printability_review.json
│   └── final_review.json
├── logs/
│   └── run_YYYYMMDD_HHMMSS.log
└── README_交付说明.md
```

## 9. 数据文件规格

### 9.1 project.json

```json
{
  "schema_version": "0.1",
  "project_id": "20260725_001",
  "project_name": "ai_cpu_cooling_shell",
  "project_type": "3d_print_shell",
  "unit": "mm",
  "drawing_standard": "GB_T_style",
  "created_at": "2026-07-25T20:00:00+08:00",
  "updated_at": "2026-07-25T20:00:00+08:00",
  "output_root": "C:/Users/current/Documents/CADAutomationWorkbench",
  "status": "draft"
}
```

### 9.2 parameters.json

```json
{
  "schema_version": "0.1",
  "units": "mm",
  "shell": {
    "outer_length": 120,
    "outer_width": 80,
    "outer_height": 35,
    "wall_thickness": 1.6,
    "bottom_thickness": 2.0,
    "corner_radius": 4,
    "edge_chamfer": 0.5,
    "open_direction": "top"
  },
  "printing": {
    "process": "FDM",
    "nozzle_diameter": 0.4,
    "hole_compensation": 0.2,
    "fit_clearance": 0.3,
    "min_wall_warning": 1.2
  },
  "features": {
    "holes": [],
    "cutouts": [],
    "bosses": [],
    "vents": []
  },
  "drawing": {
    "paper_size": "A3",
    "scale": "1:1",
    "title": "3D打印外壳",
    "material": "PLA/PETG",
    "projection": "first_angle",
    "required_exports": ["dwg", "dxf", "pdf", "png"]
  }
}
```

### 9.3 final_review.json

```json
{
  "schema_version": "0.1",
  "overall_status": "fail",
  "project_id": "20260725_001",
  "checked_at": "2026-07-25T20:30:00+08:00",
  "checks": [
    {
      "id": "drawing-hole-position-complete",
      "severity": "P0",
      "status": "fail",
      "target": "drawing",
      "message": "接口孔 I1 缺少 X/Y 中心定位尺寸",
      "suggestion": "补充相对左边和底边的中心定位尺寸"
    }
  ],
  "outputs": {
    "sldprt": "outputs/model/project.sldprt",
    "step": "outputs/model/project.step",
    "stl": "outputs/model/project.stl",
    "dwg": "outputs/drawing/project.dwg",
    "dxf": "outputs/drawing/project.dxf",
    "pdf": "outputs/drawing/project.pdf",
    "preview": "previews/drawing_preview.png"
  }
}
```

## 10. P0 规范检查清单

### 10.1 模型 P0

| ID | 检查项 | 失败条件 |
|---|---|---|
| model-file-exists | 模型文件存在 | SLDPRT/STEP/STL 缺失或大小异常 |
| model-solid-body | 主体存在 | 没有实体或实体数量异常 |
| model-shell-thickness | 壁厚/底厚存在 | 壁厚未建模或低于用户参数 |
| model-cut-through | 开孔真实切除 | 孔槽只是草图/线条/装饰，不贯穿指定面 |
| model-feature-count | 特征数量匹配 | 参数表孔槽数量与模型不一致 |
| model-print-scale | 尺寸单位正确 | 输出 STL 尺寸不是 mm 对应尺度 |

### 10.2 工程图 P0

| ID | 检查项 | 失败条件 |
|---|---|---|
| drawing-frame-title | 图框标题栏 | 缺少图框、标题栏、单位、比例 |
| drawing-main-dimensions | 外形总尺寸 | 长宽高任一漏标 |
| drawing-wall-dimensions | 壁厚/底厚 | 3D 打印壳体未标壁厚或底厚 |
| drawing-hole-spec | 孔槽规格 | 孔槽缺规格、数量或类型 |
| drawing-hole-position | 孔槽定位 | 孔槽缺 X/Y 定位、中心距或基准尺寸 |
| drawing-real-dimensions | 真实尺寸实体 | 关键尺寸用手画线或纯文字冒充 |
| drawing-leader-crossing | 引线穿越 | 长引线跨视图、穿孔、穿中心线或压字 |
| drawing-overlap | 图面重叠 | 尺寸/文字/表格重叠影响读取 |
| drawing-title-intrusion | 标题栏侵入 | 尺寸线或文字进入标题栏 |
| drawing-hole-table | 孔槽明细表 | 密集孔槽没有表，或表缺规格/数量/定位 |

### 10.3 3D 打印 P0

| ID | 检查项 | 失败条件 |
|---|---|---|
| print-min-wall | 最小壁厚 | 小于用户设定硬下限 |
| print-open-hole | 必要开孔 | 用户要求开孔但模型未切除 |
| print-fit-clearance | 装配间隙 | 参数中要求装配但没有间隙 |
| print-stl-valid | STL 导出 | 文件缺失、空文件或尺度异常 |

## 11. 图纸默认样式

MVP 默认采用国内机械图纸习惯。

默认设置:

| 项目 | 默认值 |
|---|---|
| 图幅 | A3，必要时 A4 |
| 单位 | mm |
| 比例 | 1:1，放不下时 1:2 / 2:1 |
| 字体 | 仿宋风格中文，缺字体时使用可用中文字体并记录 |
| 线型 | 粗实线、细实线、中心线、虚线、尺寸线分层 |
| 标题栏 | 右下角 |
| 视图 | 主视图、俯视图、右视图/剖视图、等轴测参考 |
| 表格 | 孔槽明细表优先 |

注意:

```text
“参照 GB/T 风格”不是替代企业审图。若用户提供企业模板，必须优先使用企业模板。
```

## 12. 交付包规格

交付包必须包含:

```text
01_model/
  project.sldprt
  project.step
  project.stl

02_drawing/
  project.dwg
  project.dxf
  project.pdf
  drawing_preview.png

03_review/
  model_review.json
  drawing_review.json
  printability_review.json
  final_review.json

04_source/
  project.json
  parameters.json
  generated_scripts/

README_交付说明.md
```

`README_交付说明.md` 必须写:

- 项目名称。
- 单位。
- 材料/打印工艺假设。
- 输出文件说明。
- 图纸标准说明。
- 复核状态。
- 仍需人工确认项。

## 13. 状态机

项目状态:

```text
draft -> ready -> running -> generated -> reviewing -> pass
                                      -> warning
                                      -> failed
```

阶段状态:

```text
waiting
running
passed
warning
failed
skipped
```

规则:

- P0 任一失败，项目状态为 `failed`。
- P1 失败，项目状态可以是 `warning`。
- 所有必需输出存在且 P0 通过，项目状态才可为 `pass`。

## 14. 错误处理

错误必须结构化记录。

```json
{
  "stage": "build_drawing",
  "error_code": "AUTOCAD_COM_REJECTED",
  "message": "AutoCAD COM 调用被拒绝",
  "retryable": true,
  "suggestion": "等待 AutoCAD 空闲后重试，必要时关闭弹窗或重启 AutoCAD"
}
```

常见错误:

| 错误码 | 阶段 | 处理 |
|---|---|---|
| SOLIDWORKS_NOT_FOUND | preflight | 提示安装或启动 SolidWorks |
| PYWIN32_MISSING | preflight | 提示安装依赖 |
| AUTOCAD_NOT_FOUND | preflight | 提示安装或启动 AutoCAD |
| AUTOCAD_COM_REJECTED | build_drawing | 串行重试，必要时提示用户关闭弹窗 |
| FEATURE_PARAM_INCOMPLETE | validate_parameters | 阻止生成，要求补孔槽定位 |
| MODEL_CUT_MISSING | review_model | 返工模型 |
| DRAWING_DIM_MISSING | review_drawing | 返工图纸 |
| EXPORT_FILE_MISSING | package | 重新导出 |

## 15. MVP 界面优先级

### P0 页面

- 首页/项目列表。
- 新建项目。
- 3D 打印外壳参数页。
- 执行日志页。
- 复核报告页。
- 输出文件页。

### P1 页面

- Skills 版本管理。
- 规则库配置。
- 企业模板导入。
- 历史项目复制。

### P2 页面

- 可视化孔位编辑器。
- 3D 预览。
- 图纸在线批注。
- 多模板市场。

## 16. 开发拆分

### 第一个可运行版本

目标:

```text
能创建项目、保存参数、跑一次 mock 执行、生成 review.json 和交付目录。
```

任务:

1. 建立桌面项目目录。
2. 实现主窗口和导航。
3. 实现项目创建。
4. 实现参数表单。
5. 实现本地 JSON 保存。
6. 实现 mock 执行状态机。
7. 实现输出目录打开。

### 第二个版本

目标:

```text
接入 SolidWorks，生成真实 3D 打印外壳模型。
```

任务:

1. 接入 `sw_preflight.py`。
2. 接入 SolidWorks 建模脚本。
3. 导出 SLDPRT/STEP/STL。
4. 生成模型预览。
5. 生成模型复核报告。

### 第三个版本

目标:

```text
接入 AutoCAD，生成符合 P0 规则的 DWG/DXF 工程图。
```

任务:

1. 接入 `acad_preflight.py`。
2. 生成 drawing_plan.json。
3. 调用 AutoCAD 绘图。
4. 导出 DWG/DXF/PDF/PNG。
5. 实现 P0 图纸复核。

### 第四个版本

目标:

```text
一键交付包。
```

任务:

1. 汇总所有输出。
2. 写交付说明。
3. 压缩交付包。
4. 做最终状态页。

## 17. 首版不确定项

需要后续验证:

- AutoCAD 预览导出在不同版本上的稳定性。
- SolidWorks Drawing 和 AutoCAD Drawing 哪条路线更省返工。
- 真实几何中如何稳定检测孔槽“已经切穿”。
- P0 图纸复核哪些能机器判断，哪些必须保留人工目视确认。
- 默认图框模板是否采用内置模板，还是要求用户导入企业模板。

## 18. 下一步

建议下一步进入原型设计:

```text
apps/desktop/
```

最小实现:

- PySide6 主窗口。
- 项目创建。
- 参数表单。
- 本地项目目录生成。
- mock 执行和 review.json。

在 mock 原型跑通后，再接 SolidWorks 和 AutoCAD。这样可以先验证用户流程，而不是一开始被 COM 稳定性拖住。
