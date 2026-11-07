import type { AutomationJobStatus } from "../types";

export type PipelineStageKey = "requirements" | "summary" | "design" | "verify" | "drawing";
export type PipelineStageState = "pending" | "ready" | "running" | "passed" | "failed" | "blocked";

export type RequirementSpec = {
  purpose: string;
  dimensions: string;
  interfaces: string;
  material: string;
  process: string;
  tolerance: string;
  outputs: string;
  assumptions: string[];
  openQuestions: string[];
};

export type PipelineStageRecord = {
  state: PipelineStageState;
  jobId?: string;
  updatedAt?: string;
  message?: string;
};

export type ProjectPipeline = {
  schemaVersion: "1.0";
  projectId: string;
  projectName: string;
  requirementText: string;
  attachments: string[];
  spec?: RequirementSpec;
  specConfirmedAt?: string;
  stages: Record<PipelineStageKey, PipelineStageRecord>;
  updatedAt: string;
};

export type PipelineJobLookup = Record<
  string,
  { status?: AutomationJobStatus; lastMessage?: string; result?: { message?: string } } | undefined
>;

export type StageMeta = {
  label: string;
  short: string;
  detail: string;
  action: string;
};

export const PIPELINE_STAGE_ORDER: PipelineStageKey[] = [
  "requirements",
  "summary",
  "design",
  "verify",
  "drawing",
];

export const PIPELINE_STAGE_META: Record<PipelineStageKey, StageMeta> = {
  requirements: {
    label: "说需求",
    short: "需求",
    detail: "用自然语言写清用途、关键尺寸、材料、工艺和输出格式，缺口由总结阶段标出。",
    action: "生成需求总结",
  },
  summary: {
    label: "需求总结",
    short: "总结",
    detail: "整理成可核对的结构化清单，逐项确认后才会开始建模。",
    action: "确认需求",
  },
  design: {
    label: "三维设计",
    short: "三维",
    detail: "按确认后的需求在 SolidWorks 里建模，必须真实切除孔槽并回读几何。",
    action: "开始三维设计",
  },
  verify: {
    label: "验证",
    short: "验证",
    detail: "核对尺寸、孔位、壁厚、干涉、质量属性和特征树，留下结构化证据。",
    action: "运行验证",
  },
  drawing: {
    label: "工程图",
    short: "工程图",
    detail: "用 AutoCAD 出 A3 图框、三视图、真实尺寸、孔表和标题栏，并重开复核。",
    action: "生成工程图",
  },
};

const MATERIAL_KEYWORDS = [
  "6061",
  "7075",
  "Q235",
  "45#",
  "304",
  "316",
  "铝合金",
  "不锈钢",
  "碳钢",
  "黄铜",
  "亚克力",
  "ABS",
  "PETG",
  "PLA",
  "尼龙",
  "POM",
];

const PROCESS_KEYWORDS = [
  "3D打印",
  "CNC",
  "数控",
  "钣金",
  "激光切割",
  "注塑",
  "车削",
  "铣削",
  "冲压",
  "折弯",
  "焊接",
];

const OUTPUT_KEYWORDS = ["SLDPRT", "SLDASM", "STEP", "STP", "STL", "DWG", "DXF", "PDF", "BOM"];

/** @brief 创建一条空流水线，五阶段全部处于待开始。 */
export function createEmptyPipeline(projectId: string, projectName: string): ProjectPipeline {
  return {
    schemaVersion: "1.0",
    projectId,
    projectName,
    requirementText: "",
    attachments: [],
    stages: {
      requirements: { state: "ready" },
      summary: { state: "pending" },
      design: { state: "pending" },
      verify: { state: "pending" },
      drawing: { state: "pending" },
    },
    updatedAt: new Date().toISOString(),
  };
}

function uniqueMatches(text: string, candidates: string[]) {
  const upper = text.toUpperCase();
  return candidates.filter((candidate) => upper.includes(candidate.toUpperCase()));
}

function extractDimensions(text: string) {
  const pattern = /(\d+(?:\.\d+)?)\s*[x×*]\s*(\d+(?:\.\d+)?)(?:\s*[x×*]\s*(\d+(?:\.\d+)?))?/i;
  const match = text.match(pattern);
  if (!match) return "";
  const [, a, b, c] = match;
  return c ? `${a} × ${b} × ${c} mm` : `${a} × ${b} mm`;
}

const CHINESE_COUNTS: Record<string, number> = {
  一: 1,
  二: 2,
  两: 2,
  三: 3,
  四: 4,
  五: 5,
  六: 6,
  七: 7,
  八: 8,
  九: 9,
  十: 10,
};

function numberize(token: string): number | null {
  if (/^\d+$/.test(token)) return Number(token);
  return CHINESE_COUNTS[token] ?? null;
}

function extractHoles(text: string) {
  const found = new Set<string>();
  const cornerCount = /(四角|四个角|四边各|每角)/.test(text) ? 4 : null;
  const explicit = text.match(
    /(\d+|[一二两三四五六七八九十]+)\s*(?:个|处)?\s*(?:Ø|Φ|φ|直径)\s*(\d+(?:\.\d+)?)/i,
  );
  if (explicit) {
    const parsed = numberize(explicit[1]);
    const count = parsed === 1 && cornerCount ? cornerCount : parsed;
    if (count) found.add(`${count} × Ø${explicit[2]}`);
  } else {
    const diameters = Array.from(
      new Set(
        Array.from(text.matchAll(/(?:Ø|Φ|φ|直径)\s*(\d+(?:\.\d+)?)/gi)).map((match) => match[1]),
      ),
    );
    for (const diameter of diameters) {
      found.add(cornerCount ? `${cornerCount} × Ø${diameter}` : `Ø${diameter}`);
    }
  }
  for (const match of text.matchAll(/\bM(\d+(?:\.\d+)?)\b/gi)) {
    found.add(`M${match[1]} 螺纹`);
  }
  for (const match of text.matchAll(/(?<![ØΦφ径])(\d+|[一二两三四五六七八九十]+)\s*(?:个)?\s*(通孔|沉头孔|长圆孔|槽)/g)) {
    const count = numberize(match[1]);
    if (count) found.add(`${count} 个 ${match[2]}`);
  }
  return Array.from(found).join("；");
}

/**
 * @brief 从自然语言需求里提取可核对的结构化草稿。
 *
 * 这是确定性提取，不调用模型；确认面板允许用户逐项改写后再进入建模阶段。
 */
export function summarizeRequirement(
  text: string,
  fallback: { material?: string; process?: string; outputs?: string } = {},
): RequirementSpec {
  const normalized = text.replace(/\s+/g, " ").trim();
  const materials = uniqueMatches(normalized, MATERIAL_KEYWORDS);
  const processes = uniqueMatches(normalized, PROCESS_KEYWORDS);
  const outputs = uniqueMatches(normalized, OUTPUT_KEYWORDS);
  const dimensions = extractDimensions(normalized);
  const interfaces = extractHoles(normalized);
  const openQuestions: string[] = [];
  if (!dimensions) openQuestions.push("缺少整体外形尺寸，需要补充长 × 宽 × 高。");
  if (!interfaces) openQuestions.push("没有识别到孔位或接口，请确认是否确实不需要。");
  if (materials.length === 0 && !fallback.material) openQuestions.push("未指定材料。");
  if (processes.length === 0 && !fallback.process) openQuestions.push("未指定制造工艺。");
  if (outputs.length === 0) openQuestions.push("未指定交付格式，默认按 SLDPRT + STEP + DWG + PDF。");

  return {
    purpose: normalized,
    dimensions,
    interfaces,
    material: materials.join(" / ") || fallback.material || "",
    process: processes.join(" / ") || fallback.process || "",
    tolerance: "",
    outputs: outputs.join(" / ") || fallback.outputs || "SLDPRT / STEP / DWG / PDF",
    assumptions: [
      "单位默认毫米。",
      "未标注公差按一般公差，关键配合仍由工程师确认。",
      "孔槽必须是真实几何切除，不用草图或注释代替。",
    ],
    openQuestions,
  };
}

/** @brief 把结构化需求拼成一句话目标，供任务标题和模型提示复用。 */
export function specToObjective(spec: RequirementSpec) {
  return [
    spec.purpose,
    spec.dimensions && `外形 ${spec.dimensions}`,
    spec.interfaces && `接口 ${spec.interfaces}`,
    spec.material && `材料 ${spec.material}`,
    spec.process && `工艺 ${spec.process}`,
    spec.outputs && `输出 ${spec.outputs}`,
  ]
    .filter(Boolean)
    .join("；");
}

/** @brief 把任务状态映射为流水线阶段状态。 */
export function stageStateForJob(status: AutomationJobStatus | undefined): PipelineStageState {
  switch (status) {
    case "queued":
    case "running":
      return "running";
    case "passed":
      return "passed";
    case "review_required":
    case "approval_required":
    case "blocked":
      return "blocked";
    case "failed":
    case "cancelled":
      return "failed";
    default:
      return "pending";
  }
}

/** @brief 优先用真实任务状态，其次用流水线里保存的状态。 */
export function resolveStageState(
  pipeline: ProjectPipeline,
  stage: PipelineStageKey,
  jobs: PipelineJobLookup = {},
): PipelineStageState {
  const record = pipeline.stages[stage];
  if (record?.jobId) {
    const job = jobs[record.jobId];
    if (job) return stageStateForJob(job.status);
  }
  return record?.state ?? "pending";
}

/** @brief 统计已完成阶段比例，范围 0 到 100。 */
export function pipelineProgress(pipeline: ProjectPipeline, jobs: PipelineJobLookup = {}) {
  const done = PIPELINE_STAGE_ORDER.filter(
    (stage) => resolveStageState(pipeline, stage, jobs) === "passed",
  ).length;
  return Math.round((done / PIPELINE_STAGE_ORDER.length) * 100);
}

/** @brief 判断某个阶段当前是否允许启动，并给出阻断原因。 */
export function canRunStage(
  pipeline: ProjectPipeline,
  stage: PipelineStageKey,
  jobs: PipelineJobLookup = {},
): { ok: boolean; reason?: string } {
  if (stage === "requirements") {
    return { ok: true };
  }
  if (stage === "summary") {
    return pipeline.requirementText.trim().length >= 10
      ? { ok: true }
      : { ok: false, reason: "先把需求写清楚，至少说明要做什么。" };
  }
  if (stage === "design") {
    return pipeline.specConfirmedAt
      ? { ok: true }
      : { ok: false, reason: "需求总结还没确认。" };
  }
  if (stage === "verify") {
    return resolveStageState(pipeline, "design", jobs) === "passed"
      ? { ok: true }
      : { ok: false, reason: "三维设计还没通过。" };
  }
  return resolveStageState(pipeline, "verify", jobs) === "passed"
    ? { ok: true }
    : { ok: false, reason: "验证还没通过。" };
}

function specBlock(spec?: RequirementSpec) {
  if (!spec) return "（尚无结构化需求）";
  return [
    `用途：${spec.purpose || "未填写"}`,
    `外形尺寸：${spec.dimensions || "未填写"}`,
    `孔位与接口：${spec.interfaces || "未填写"}`,
    `材料：${spec.material || "未填写"}`,
    `制造工艺：${spec.process || "未填写"}`,
    `公差与配合：${spec.tolerance || "未填写"}`,
    `交付格式：${spec.outputs || "未填写"}`,
    spec.openQuestions.length ? `待确认项：${spec.openQuestions.join(" ")}` : "待确认项：无",
  ].join("\n");
}

/**
 * @brief 生成阶段提示词。
 *
 * 提示词只描述本阶段职责，阶段之间的准入由流水线状态机保证。
 */
export function buildStagePrompt(
  stage: PipelineStageKey,
  pipeline: ProjectPipeline,
  context: { outputDir: string; skillRoot: string },
) {
  const headline = `CAD Studio 项目流水线 · ${PIPELINE_STAGE_META[stage].label}`;
  const base = [
    `# ${headline}`,
    `项目：${pipeline.projectName}`,
    `输出目录：${context.outputDir}`,
    `技能根目录：${context.skillRoot}`,
    "",
    "## 已确认需求",
    specBlock(pipeline.spec),
    "",
    "## 原始需求",
    pipeline.requirementText.trim() || "（空）",
  ];

  if (stage === "design") {
    return [
      ...base,
      "",
      "## 本阶段要求",
      "1. 用 SolidWorks 原生建模，不先生成开放格式再导入。",
      "2. 草图、拉伸、切除、孔阵列等要保持可编辑特征树，禁止用注释或贴图代替孔槽。",
      "3. 每完成一批特征就回读一次几何，记录体积、质量、特征数和包围盒。",
      "4. 保存 SLDPRT 与 STEP，文件名使用项目名加 _design。",
      "5. 结束时输出中文结论：输出路径、关键尺寸实测值、未解决项。",
      "6. 必须额外写出门禁可读的规格证据文件 verification/<项目名>_design_cad_spec.json，格式严格如下：",
      '{"cad_spec":{"measurement_source":"SolidWorks API GetBoundingBox/Face2.GetSurface","length_mm":120.0,"width_mm":80.0,"thickness_mm":12.0,"holes":[{"diameter_mm":9.0,"count":4,"centers_mm":[[15,15],[105,15],[105,65],[15,65]]}]}}',
      "   其中所有数值必须是本次通过 SolidWorks API 回读得到的实测值，禁止照抄需求文本。",
      "7. 本阶段只交付 SLDPRT、STEP 和建模证据；DWG、DXF、PDF、PNG 留给工程图阶段。",
      "",
      "## 验收",
      "- 关键尺寸与需求偏差超过 0.05 mm 必须报失败。",
      "- 孔槽数量或坐标与需求不一致必须报失败。",
      "- 任一必填项缺失时不要猜测，回到需求总结阶段。",
      "- 自动修正最多 1 次；第二次复核仍失败必须立即返回失败，禁止继续自循环。",
    ].join("\n");
  }

  if (stage === "verify") {
    return [
      ...base,
      "",
      "## 本阶段要求",
      "只做验证，不修改设计。逐项核对并记录证据：",
      "1. 尺寸链：外形、孔距、孔径、壁厚实测值。",
      "2. 几何健康：实体数、干涉、零厚度、开放边。",
      "3. 质量属性：体积、质量、重心、材料密度来源。",
      "4. 特征树：切除特征数量、是否全部为真实几何。",
      `5. 生成 ${context.outputDir}\\verification.json，字段包含 status、checks、measurements、retryFromStage。`,
      "6. 本阶段只验证已有设计，不重做需求分析，不重新建模，不生成二维工程图。",
      "",
      "## 验收",
      "- 全部检查通过才写 status=passed。",
      "- 任一检查失败写 status=failed，并给出 retryFromStage。",
      "- 自动修正最多 1 次；第二次复核仍失败必须立即返回失败，禁止继续自循环。",
    ].join("\n");
  }

  return [
    ...base,
    "",
    "## 本阶段要求",
    "使用本机 AutoCAD，通过 autocad-automation 的 COM 封装出工程图：",
    "1. 真实尺寸实体（AcDbAlignedDimension/AcDbRotatedDimension/AcDbDiametricDimension），禁止用文字冒充尺寸。",
    "2. 输出 DWG、DXF、PDF 与 PNG 预览到输出目录，文件名使用项目名加 _drawing。",
    "3. 保存后重开复核：实体数、图层、真实尺寸数、标题栏关键字。",
    "4. 同步复核 verification/<项目名>_design_cad_spec.json，确保外形与孔径与 API 回读一致。",
    "5. 本阶段只消费已通过验证的设计，不重新建模、不修改 SLDPRT/STEP，只交付二维工程图及图纸证据。",
    "",
    "## 制图规范（强制，必须逐条满足）",
    "- 图幅格式 GB/T 14689：A3 横向 420×297；留装订边 a=25（左）、c=5（其余三边）；图框粗实线、纸边界细实线。",
    "- 比例 GB/T 14690：优先 1:1，写入标题栏；不同比例视图须单独标注；尺寸数字始终为实物值。",
    "- 字体 GB/T 14691 / GB/T 18229 表 4：汉字 5 mm、数字 3.5 mm、图内最小 2.5 mm；优先工程长仿宋或宋体。",
    "- 图线 GB/T 17450 / GB/T 4457.4 / GB/T 14665：A3 用第 3 组，粗 0.5、细 0.25，粗细比 2:1。",
    "- 颜色与 CTB：粗实线白、细实线绿、虚线黄、细点画线红、粗点画线棕、双点画线粉；必须配置颜色→线宽映射。",
    "- 图层按 GB/T 18229 表 13 的 01–13 编号含义分层（粗实线/细实线/粗虚线/细虚线/细点画线/粗点画线/细双点画线/尺寸线/参考圆/剖面符号/细文本/尺寸值/粗文本）。",
    "- 单位 INSUNITS=4（mm）；模型空间 1:1 绘制实物，图框与标题栏按 1:1 出图。",
    "- 视图 GB/T 14692 / GB/T 4458.1：第一角画法，主视图 + 俯视图 + 左视图，长对正、高平齐、宽相等。",
    "- 尺寸注法 GB/T 4458.4：尺寸界线留间隙并超出，箭头形式唯一，数字不被图线穿过，避免封闭尺寸链。",
    "- 表面结构 GB/T 131：未指定时按 Ra 3.2，写入技术要求。",
    "- 几何公差 GB/T 1182；未注线性/角度公差按 GB/T 1804-m。",
    "- 标题栏 GB/T 10609.1：180×56，8 行 × 7 mm，含更改区/签字区/其他区/名称及代号区，置于图框右下角。",
    "- 明细栏 GB/T 10609.2：装配图置于标题栏上方、自下而上；单件可省略。",
    "- 孔标注：4×Ø9 用 Ø 引出并配孔表；中心线用 CENTER 线型。",
    "",
    "## 验收",
    "- 中文文字必须使用本地化 TrueType 字体样式，禁止出现问号占位。",
    "- 原生预览不得为空，导出前确认视口已恢复。",
    "- 必须由 Worker 再执行 scripts/gb_drawing_check.py <DXF> --json verification/gb_checklist.json；12 项全部 pass 且报告进入交付账本才算完成。",
    "- 任一条 GB 检查不通过，本阶段必须报 fail，不能标记完成。",
    "- 标题栏外框必须实测 180×56 mm；图框与标题栏应能在 DXF 中独立量取。",
    "- 自动修正最多 1 次；第二次 GB 复核仍失败必须立即返回失败，禁止反复重画。",
  ].join("\n");
}
