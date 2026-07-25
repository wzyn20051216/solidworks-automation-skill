# SolidWorks Automation Skill 市场调研与产品定位

调研日期: 2026-07-25

## 1. 结论先行

不要把项目做成一个新的 CAD 软件，也不要先做一个漂亮但空的可视化外壳。

更值得做的是:

```text
面向机械工程师和打样团队的本地 CAD 自动化交付助手
```

核心价值:

```text
传参考图/填参数 -> 自动建模 -> 自动出工程图 -> 按国标和制造规则复核 -> 输出可交付文件包
```

这个方向避开了和 SolidWorks、Inventor、Fusion、NX、Creo 的正面竞争，重点解决工程师每天重复、容易出错、但又必须做对的工作。

## 2. 市场信号

### 2.1 CAD 和工业研发设计软件仍在增长

- Research and Markets 的 2026 CAD 市场报告显示，CAD 软件市场按 3D/2D、部署方式、建模方式、应用行业等细分，工程公司、工业设计公司是主要终端用户之一。
- 智研咨询 2025 年报告提到，2024 年全球工业研发设计软件市场规模约 550 亿美元，中国工业研发设计软件市场规模约 350 亿元，受智能制造、数字化转型、国产替代推动。

判断:

CAD 本体市场很大，但大厂垄断强，做完整 CAD 的投入极高。我们应该做 CAD 周边的自动化增效工具。

### 2.2 AI 在机械工程中的落点已经清晰

Colab Software 在 2026 年机械工程 AI 工具梳理中，把 AI 落点归纳到五类:

- 工程知识管理
- 生成式设计和 AI CAD 建模
- AI 仿真
- 自动设计审查和 DFM
- PLM 与数字线程

其中最适合本项目切入的是:

```text
自动设计审查和 DFM + 工程图自动化 + 本地知识库/规范库
```

原因是这些工作有明确输入、明确规则、明确交付物，适合自动化，也便于验证是否做对。

### 2.3 大厂正在做 AI，但仍留下垂直机会

SOLIDWORKS 官方已经把 AI CAD automation、Virtual Companions、AURA/LEO 等作为设计流程的一部分，强调让工程师聚焦高价值工作、减少重复劳动。

Autodesk Fusion 强调的不只是 CAD，而是设计、仿真、生成式设计、网格编辑、塑料件规则和生命周期管理。

AutoCAD Mechanical 2026 强调机械工程任务自动化、BOM、零件明细、气泡序号、自动尺寸、GD&T 符号和标准化标注。

判断:

大厂方向证明了需求存在，但大厂产品通常更偏通用、企业化、订阅化。我们的机会在:

- 本地 Windows 工作流
- 中文机械工程师习惯
- 国标工程图复核
- SolidWorks + AutoCAD 联动
- 3D 打印/小批量打样交付
- 可由 AI 代理直接调用

## 3. 竞品观察

| 产品/方向 | 主要能力 | 对我们的启发 | 我们不应硬碰的点 |
|---|---|---|---|
| SOLIDWORKS AI | 嵌入式 AI、虚拟助手、设计流程提效 | 证明 CAD 内 AI 助手是趋势 | 不做完整 CAD 内核 |
| Autodesk Fusion | CAD + 仿真 + 生成式设计 + 生命周期 | 设计到制造一体化是主线 | 不做云端全平台 CAD |
| AutoCAD Mechanical | 机械制图自动化、标准化标注、BOM | 图纸标准和自动标注是刚需 | 不做 AutoCAD 替代品 |
| Siemens Solid Edge 2D Drafting | 2D 图纸、标注、标准兼容 | 2D 工程图仍有生命力 | 不做独立 2D CAD |
| DraftAid | 从 3D 模型自动生成 2D 制造图 | 工程图自动化是强痛点 | 避免只做英文/国外标准 |
| CoLab AutoReview | 设计审查、DFM、问题跟踪、知识沉淀 | 审查比生成更容易进入企业流程 | 不先做大型协同平台 |
| Leo AI | CAD-aware 知识管理、工程知识复用 | 工程知识库和历史经验很有价值 | 不承诺复杂 B-rep AI 语义能力 |
| Zoo.dev | Text-to-CAD、现代几何引擎、API | 文本生成 CAD 是趋势 | 不自研几何内核 |

## 4. 目标用户

### 4.1 第一目标用户

个人机械设计师、创客、小型工作室、自动化设备工程师、3D 打印打样用户。

共同特征:

- 有 SolidWorks 或 AutoCAD 使用习惯
- 经常做结构外壳、支架、安装板、面板、散热壳
- 需要快速出 STL/STEP/DWG/DXF/PDF
- 不想每次重复画孔、倒角、螺丝柱、工程图
- 对国标图纸和可制造交付有要求

### 4.2 第二目标用户

中小制造企业、非标自动化团队、教学/培训机构。

需求:

- 统一制图规范
- 降低新人工程师出图错误
- 建立模板库和检查清单
- 缩短从需求到打样的时间

### 4.3 暂不优先服务的用户

- 大型汽车/航空/军工企业的完整 PLM 流程
- 超复杂曲面和拓扑优化场景
- 云端多人协同 CAD 平台
- 替代 SolidWorks/NX/CATIA 的完整 CAD 系统

## 5. 机械工程师高频痛点

| 痛点 | 具体表现 | 自动化机会 |
|---|---|---|
| 相似零件重复建模 | 外壳、支架、面板、安装板反复改尺寸 | 参数化模板库 |
| 图纸标注返工 | 孔有规格但没有定位尺寸，尺寸线压线，引线穿视图 | 国标图纸复核引擎 |
| 3D 打印不可用 | 壁厚太薄、孔没真实打穿、孔径没补偿、装配间隙不足 | 3D 打印制造规则库 |
| 导出交付繁琐 | STL、STEP、DWG、DXF、PDF、预览图分散导出 | 一键交付包 |
| 经验不可复用 | 老工程师知道的规则没有沉淀 | 规则库 + 项目复盘 |
| Prompt 不稳定 | 用户一句话说不全孔位、公差、材料 | 表单化输入 + AI 追问 |
| 软件链割裂 | SolidWorks 建模，AutoCAD 出图，文件再手动整理 | 本地任务编排 |

## 6. 本项目当前资产

已有资产:

- SolidWorks 自动化脚本
- AutoCAD 自动化子技能
- 工程图生成经验
- 开孔/开槽/定位尺寸的规范教训
- GitHub skill 仓库
- MCP server 雏形
- 示例脚本和测试脚本

短板:

- 没有面向用户的任务入口
- 没有结构化模板库
- 缺少正式的国标制图规则库
- 缺少系统化 DFM/3D 打印规则库
- 缺少图纸自动复核报告的稳定 schema
- 缺少项目文件管理和历史记录
- 缺少可打包的 Windows 软件壳

## 7. 产品定位

建议产品名:

```text
CAD 自动化交付工作台
```

一句话:

```text
把机械工程师重复的建模、出图、开孔检查和交付文件整理，变成可复核的一键流程。
```

不是:

- 不是新 CAD
- 不是纯 AI 聊天机器人
- 不是云端协同平台
- 不是只会生成漂亮预览图的玩具

是:

- SolidWorks/AutoCAD 的本地自动化控制台
- 中国机械图纸规范检查器
- 3D 打印/打样交付助手
- 机械结构模板库
- AI + 规则 + CAD 脚本的任务编排器

## 8. MVP 功能建议

### MVP 目标

让用户完成一个真实任务:

```text
做一个可 3D 打印的外壳，并输出符合中国机械制图习惯的工程图和交付包。
```

### 必做功能

1. 项目创建
   - 选择项目类型: 3D 打印外壳
   - 设置输出目录
   - 上传参考图

2. 参数表单
   - 外形长宽高
   - 壁厚
   - 圆角/倒角
   - 显示孔、接口孔、螺丝孔、水口、散热槽
   - 每类孔槽必须填写规格、数量、定位基准

3. 生成模型
   - 调 SolidWorks 脚本
   - 确保孔/槽真实切除
   - 导出 STL/STEP/SLDPRT

4. 生成图纸
   - 调 AutoCAD 或 SolidWorks Drawing
   - 输出 DWG/DXF/PDF/PNG
   - 默认 A3 或 A4 图框、标题栏、比例、单位 mm

5. 规范复核
   - 图纸幅面和标题栏
   - 孔/槽规格、数量、定位尺寸
   - 尺寸线、引线、文字重叠
   - 开孔是否真实存在
   - 3D 打印壁厚/孔径/间隙基础规则

6. 交付包
   - 输出文件统一归档
   - 生成 `review.json`
   - 生成 `README_交付说明.md`

### 暂缓功能

- 云账号
- 多人协作
- PLM/PDM 集成
- 拓扑优化
- 复杂曲面生成
- 自动报价
- 全自动大模型生成任意 CAD

## 9. 图纸规范能力优先级

### P0 硬规则

- 任何孔、槽、接口、水口、螺丝孔、螺丝柱都必须有规格、数量、定位尺寸。
- 不能用长引线代替关键尺寸链。
- 引线不能跨视图、穿孔、穿中心线、穿标题栏。
- 尺寸不能压线、压字、压图框。
- 图纸必须有图框、标题栏、单位、比例、视图名称、技术要求。
- 3D 打印件的开孔必须在模型中真实切除，不能只在图纸上画示意。

### P1 建议规则

- 拥挤区域优先使用孔表/槽表/孔槽明细表。
- 对称孔优先用中心线和基准尺寸表达。
- 重复孔使用 `n×Φd` 或孔表表达，避免散乱标注。
- 对 3D 打印孔径给出工艺补偿建议。
- 对装配配合给出推荐间隙。

### P2 增强规则

- 自动检测未约束草图。
- 自动检测过薄壁、尖角、悬垂、孤岛小特征。
- 自动检测 STL 非流形、反法线、开边。
- 自动生成 DFM 建议。

## 10. 3D 打印规则库初版

FDM 方向优先，因为个人用户和小工作室最常见。

建议默认值:

| 项目 | 初版建议 |
|---|---|
| 结构壁厚 | 优先 1.6 mm 以上 |
| 最低可打印壁厚 | 不低于 0.8-1.0 mm，具体看喷嘴 |
| 螺丝柱外径 | 至少为螺丝直径 2-2.5 倍，后续按 M2/M3/M4 模板细化 |
| 普通孔补偿 | FDM 孔通常偏小，可给 0.2-0.4 mm 放量选项 |
| 装配间隙 | 滑配/插接预留 0.2-0.5 mm |
| 水平圆孔 | 优先提示水滴孔或加支撑 |
| 小孔精度要求高 | 提示后钻/铰孔 |

这些规则必须可配置，不能写死。不同打印机、材料、喷嘴、切片参数会改变最终建议。

## 11. 软件形态建议

第一阶段做 Windows 本地软件，不做云端服务。

推荐形态:

```text
PySide6 桌面软件 + Python 自动化脚本 + 本地项目目录 + GitHub 更新 skill
```

理由:

- 不需要租服务器
- 能直接调用 SolidWorks/AutoCAD COM
- 能复用现有 Python 脚本
- 更容易打包成 exe
- 数据留在用户本机，更符合工程文件隐私需求

后续如要做更漂亮界面，可再考虑:

```text
Tauri/Electron + 本地 Python 后端
```

## 12. MVP 验证指标

不要先追求功能多，先验证是否真的省时间、少返工。

建议指标:

| 指标 | 目标 |
|---|---|
| 外壳建模到 STL | 10 分钟内完成 |
| 工程图初稿 | 5 分钟内生成 |
| 孔/槽漏标率 | P0 规则漏标为 0 |
| 可打印性问题 | 至少检查壁厚、孔径、真实切除、间隙 |
| 返工次数 | 从多轮返工降到 1 轮以内 |
| 用户输入 | 以表单为主，prompt 为辅 |

## 13. 90 天路线图

### 第 1-2 周: 产品骨架

- 建立 `apps/desktop` 或独立桌面项目
- 做 PySide6 主窗口
- 做项目创建、输出目录、日志面板
- 能读取本地 skill 状态和版本

### 第 3-4 周: 外壳模板

- 做 3D 打印外壳参数表
- 打通 SolidWorks 建模脚本
- 输出 STL/STEP/SLDPRT
- 加真实开孔检查

### 第 5-6 周: 工程图与复核

- 打通 AutoCAD/SolidWorks Drawing 出图
- 输出 DWG/DXF/PDF/PNG
- 实现 P0 图纸规范检查
- 生成 review.json

### 第 7-8 周: 交付包

- 一键归档交付文件
- 生成交付说明
- 做历史项目列表
- 做失败原因可视化

### 第 9-12 周: 模板扩展

- 安装板模板
- 支架模板
- 散热壳模板
- 螺丝柱/嵌件模板
- 3D 打印规则库可配置

## 14. 风险

| 风险 | 应对 |
|---|---|
| SolidWorks/AutoCAD COM 不稳定 | 任务串行执行，增加重试和超时恢复 |
| 用户需求尺寸不完整 | 表单强约束 + AI 追问 |
| 图纸规范难完全自动化 | 先做 P0 规则，保留人工复核预览 |
| 不同公司制图习惯不同 | 规则库可配置，默认国标风格 |
| 3D 打印参数差异大 | 默认建议 + 用户打印机配置 |
| 产品边界膨胀 | 坚持外壳/支架/安装件高频模板优先 |

## 15. 下一步任务

建议下一步直接做产品原型规格，而不是马上写代码。

需要产出:

```text
docs/product-mvp-spec.md
```

内容:

- 软件首页信息架构
- 第一个任务向导: 3D 打印外壳
- 参数字段定义
- 输出文件结构
- review.json schema
- P0 规范检查清单
- 首版界面草图

完成这个规格后，再开始写 PySide6 原型，方向会稳很多。

## 16. 调研来源

- Research and Markets: Computer Aided Design CAD Software Market Report 2026  
  https://www.researchandmarkets.com/reports/5972859/computer-aided-design-cad-software-market-report
- 智研咨询: 2025 年中国工业研发设计软件行业市场规模、产业链、竞争格局及行业发展趋势研判  
  https://www.chyxx.com/industry/1217927.html
- SOLIDWORKS: AI Product Design with Embedded AI Tools  
  https://www.solidworks.com/product/solidworks-design/ai-overview
- SOLIDWORKS: AI CAD Tools for Workflow Optimization  
  https://www.solidworks.com/solution/solidworks-ai-cad-tools-workflow-optimization
- Autodesk Fusion: Design AI solutions  
  https://www.autodesk.com/solutions/generative-design-ai-software
- Autodesk AutoCAD Mechanical Toolset  
  https://www.autodesk.com/products/autocad/included-toolsets/autocad-mechanical
- Siemens Solid Edge 2D Drafting  
  https://resources.sw.siemens.com/en-US/download-free-2d-cad-software/
- CoLab Software: Best AI Tools & Agents for Mechanical Engineers 2026  
  https://www.colabsoftware.com/ai-tools-for-mechanical-engineers-guide
- CoLab Software: Design for Manufacturability Reviews  
  https://www.colabsoftware.com/use-case/design-for-manufacturability
- DraftAid: AI CAD Drawing Automation  
  https://draftaid.io/
- Zoo.dev: Zookeeper and Text-to-CAD  
  https://zoo.dev/zookeeper
- Leo AI: Engineering-grade AI for mechanical engineers  
  https://www.getleo.ai/
- 国家标准全文公开: GB/T 4458.4-2003 机械制图 尺寸注法  
  https://openstd.samr.gov.cn/bzgk/std/newGbInfo?hcno=08588A5F3FE19F16B9EE8D5D87E064D5
- 国家标准全文公开: GB/T 4457.4-2002 机械制图 图样画法 图线  
  https://openstd.samr.gov.cn/bzgk/std/newGbInfo?hcno=5B789BF5B537CF6F89B5D743DA71D883
- 国家标准全文公开: GB/T 10609.1-2008 技术制图 标题栏  
  https://openstd.samr.gov.cn/bzgk/std/newGbInfo?hcno=0F8577CB9AB82D5819048A87920CABAB
- JLC3DP: 3D Printing Design Guideline  
  https://jlc3dp.com/help/article/3d-printing-design-guideline
- Prusa Knowledge Base: Modeling with 3D printing in mind  
  https://help.prusa3d.com/article/modeling-with-3d-printing-in-mind_164135
- Formlabs: Minimum Wall Thickness for 3D Printing  
  https://formlabs.com/blog/minimum-wall-thickness-3d-printing/
