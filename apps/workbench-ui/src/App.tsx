import {
  Aperture,
  Archive,
  CaretDown,
  ChatCircleText,
  CubeFocus,
  Export,
  FilePlus,
  FolderOpen,
  GearSix,
  Graph,
  ImageSquare,
  Layout,
  Lightning,
  Minus,
  PaperPlaneTilt,
  Play,
  Ruler,
  ShieldCheck,
  SlidersHorizontal,
  Sparkle,
  Square,
  UploadSimple,
  WarningCircle,
  X,
} from "@phosphor-icons/react";
import { convertFileSrc, invoke } from "@tauri-apps/api/core";
import { getCurrentWindow } from "@tauri-apps/api/window";
import { open as openDialog } from "@tauri-apps/plugin-dialog";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { type CSSProperties, type ChangeEvent, type DragEvent, useEffect, useMemo, useRef, useState } from "react";

type StageState = "ready" | "running" | "passed" | "attention";
type PresetWallpaperId = "aurora" | "blueprint" | "studio" | "mist";
type WallpaperId = PresetWallpaperId | "custom";
type WallpaperFile = { url: string; name: string; kind: "image" | "video"; sourcePath?: string };
type RecentWallpaper = { path: string; name: string; kind: "image" | "video" };
type AppSettings = {
  activeWallpaper: WallpaperId;
  customWallpaperPath?: string;
  wallpaperBrightness: number;
  wallpaperBlur: number;
  wallpaperVignette: number;
  recentWallpapers: RecentWallpaper[];
  recentProjectPath?: string;
  apiConfig?: ApiIntegrationConfig;
};
type ApiIntegrationMode = "codex_cli" | "cc_switch" | "openai_compatible" | "manual";
type ApiProviderSummary = {
  id?: string;
  name?: string;
  active?: boolean;
  endpoint?: string;
  model?: string;
  hasApiKey?: boolean;
  redactedApiKey?: string;
};
type CcSwitchSync = {
  source?: string;
  rootPath?: string;
  configPath?: string;
  settingsPath?: string;
  syncedAt?: string;
  codexCurrent?: string;
  claudeCurrent?: string;
  codexProviders?: ApiProviderSummary[];
  claudeProviders?: ApiProviderSummary[];
  settings?: {
    currentProviderCodex?: string;
    currentProviderClaude?: string;
    enableLocalProxy?: boolean;
    enableFailoverToggle?: boolean;
    skillSyncMethod?: string;
  };
};
type ApiIntegrationConfig = {
  mode: ApiIntegrationMode;
  providerName: string;
  endpoint: string;
  model: string;
  keyStatus: "missing" | "configured" | "synced";
  lastSyncAt?: string;
  sourcePath?: string;
};
type CodexConfig = {
  objective: string;
  cadApplication: "auto" | "solidworks" | "autocad" | "both";
  target: "auto" | "general_part" | "assembly" | "shell" | "fixture" | "sheet_metal" | "holes" | "drawing" | "package" | "reverse" | "skill";
  expectedOutput: "auto" | "cad_files" | "drawing_package" | "research_report";
  process: "auto" | "FDM" | "SLA" | "CNC" | "sheet_metal";
  material: "auto" | "PLA" | "PETG" | "ABS" | "Al6061";
  unit: "mm";
  length: number;
  width: number;
  height: number;
  wallThickness: number;
  outputDir: string;
  strictGbDrawing: boolean;
  realCutouts: boolean;
  localCadAutomation: boolean;
};
type AutomationJobKind = "create_shell" | "import_model" | "delivery_package" | "codex_task";
type AutomationJobStatus = "queued" | "running" | "passed" | "failed" | "cancelled" | "approval_required";
type WorkerLogEntry = {
  status?: string;
  message?: string;
  at?: string;
  worker?: string;
  runnerId?: string;
  data?: unknown;
};
type AutomationJob = {
  schemaVersion: "1.0";
  id: string;
  runId: string;
  kind: AutomationJobKind;
  title: string;
  detail: string;
  status: AutomationJobStatus;
  progress: number;
  createdAt: string;
  updatedAt: string;
  requestedBy: string;
  createdByAppVersion: string;
  projectPath?: string;
  executor?: "mock" | "codex";
  objective?: string;
  targetSoftware?: string;
  target?: string;
  expectedOutput?: string;
  strictRules?: string[];
  capabilities?: string[];
  prompt?: string;
  cwd?: string;
  skillPath?: string;
  lastMessage?: string;
  workerLog?: Array<WorkerLogEntry | string>;
  leaseUntil?: string;
  heartbeatAt?: string;
  runnerId?: string;
  workerPid?: number;
  result?: {
    mode?: string;
    outputPath?: string;
    message?: string;
  };
  uiConfig?: Record<string, unknown>;
  policy?: {
    sandbox: "read-only" | "workspace-write" | "danger-full-access";
    approval: "never" | "manual-required";
    requireSkillRead: boolean;
    requireTests: boolean;
    requireCommit: boolean;
    requirePush: boolean;
    requireReviewerPass: boolean;
  };
  artifacts?: Array<Record<string, unknown>>;
  approvalReasons?: string[];
  approvedAt?: string;
  approvedBy?: string;
  approvedPolicyReasons?: string[];
  artifactLedgerPath?: string;
  reviewGatePath?: string;
  reviewGate?: {
    status?: "pass" | "warning" | "fail";
    checks?: Array<Record<string, unknown>>;
  };
  error?: string;
};
type QueueEvent = {
  type?: string;
  jobId?: string;
  status?: string;
  message?: string;
  at?: string;
  progress?: number;
  worker?: string;
  runId?: string;
  runnerId?: string;
  data?: unknown;
};
type QueueLogTail = {
  stdoutPath?: string;
  stderrPath?: string;
  stdout?: string;
  stderr?: string;
};
type AgentChatMessage = {
  id: string;
  role: "user" | "assistant" | "system";
  content: string;
  at: string;
  jobId?: string;
};
type WorkerStatus = {
  running: boolean;
  pid?: number | null;
  message: string;
  health?: {
    status?: string;
    heartbeatAt?: string;
    queue?: Record<string, number>;
  } | null;
};

type Stage = {
  key: string;
  label: string;
  state: StageState;
  detail: string;
};

const wallpapers: Array<{ id: PresetWallpaperId; name: string; hint: string }> = [
  { id: "aurora", name: "Aurora", hint: "柔和蓝青流光" },
  { id: "blueprint", name: "Blueprint", hint: "淡蓝工程网格" },
  { id: "studio", name: "Studio", hint: "白色摄影棚光" },
  { id: "mist", name: "Mist", hint: "晨雾玻璃质感" },
];

const navItems = [
  ["project", "项目", Layout],
  ["model", "建模", CubeFocus],
  ["holes", "开孔", Ruler],
  ["drawing", "图纸", FilePlus],
  ["check", "检查", ShieldCheck],
  ["export", "导出", Export],
  ["settings", "设置", GearSix],
] as const;
type ActiveTab = (typeof navItems)[number][0];

const pageCopy: Record<ActiveTab, { title: string; subtitle: string }> = {
  project: {
    title: "项目工作台",
    subtitle: "拖入草图、参数表或模型文件，把零件、装配、外壳、治具、钣金、图纸和交付包交给本地 CAD Agent 流程处理。",
  },
  model: {
    title: "建模中心",
    subtitle: "从通用零件、装配体、治具夹具、钣金件、外壳、逆向重建等模板发起任务，不再局限于单一外壳。",
  },
  holes: {
    title: "孔槽与连接",
    subtitle: "管理通孔、沉头孔、螺纹孔、长圆孔、接口开槽、阵列孔和装配定位特征，要求真实几何切除。",
  },
  drawing: {
    title: "图纸工程",
    subtitle: "面向中国机械工程师的 GB/T 风格图纸、尺寸链、孔表、技术要求、标题栏和 DWG/DXF/PDF 输出。",
  },
  check: {
    title: "检查门禁",
    subtitle: "汇总 Policy Gate、Artifact Ledger、Reviewer Gate、格式检查和 3D 打印/CNC/钣金制造风险。",
  },
  export: {
    title: "交付中心",
    subtitle: "整理 SLDPRT、SLDASM、STEP、STL、DWG、DXF、PDF、PNG 预览、复核报告和 Git 交付记录。",
  },
  settings: {
    title: "软件设置",
    subtitle: "管理本地 worker、Codex Bridge、审批策略、壁纸外观、默认规范库和输出目录。",
  },
};

const stages: Stage[] = [
  { key: "preflight", label: "环境", state: "passed", detail: "SolidWorks COM 可用" },
  { key: "model", label: "建模", state: "ready", detail: "等待参数输入" },
  { key: "drawing", label: "图纸", state: "attention", detail: "缺少 DWG 实体复核" },
  { key: "package", label: "交付", state: "ready", detail: "STEP / STL / PDF 打包" },
];

const features = [
  { name: "通孔 H1", spec: "4 x Φ3.4", pos: "基准 A/B, pitch 100 x 60", status: "真实切除" },
  { name: "长圆孔 S1", spec: "18 x 6 R3", pos: "Front, X60 Y15", status: "待复核" },
  { name: "螺纹孔 T1", spec: "M3x0.5, 深 8", pos: "Boss / Plate", status: "已生成" },
  { name: "接口槽 C1", spec: "10 x 4 R1", pos: "侧面居中", status: "待复核" },
];

const reviewItems = [
  { label: "真实开孔", state: "通过", note: "孔槽将参与实体切除" },
  { label: "壁厚检查", state: "通过", note: "最小壁厚 2.0 mm" },
  { label: "国标图纸", state: "注意", note: "缺少完整尺寸链" },
  { label: "交付清单", state: "注意", note: "等待真实导出器" },
];

const SETTINGS_KEY = "cad-studio.settings.v1";
const QUEUE_KEY = "cad-studio.queue.v1";
const CHAT_KEY = "cad-studio.agent-chat.v1";
const APP_VERSION = "0.1.1";
const CODEX_CWD = "C:/Users/23201/.codex/skills/solidworks-automation";
const CODEX_SKILL_PATH = `${CODEX_CWD}/SKILL.md`;
const AUTOCAD_SKILL_PATH = `${CODEX_CWD}/subskills/autocad-automation/SKILL.md`;

const defaultApiConfig: ApiIntegrationConfig = {
  mode: "codex_cli",
  providerName: "Codex CLI",
  endpoint: "本机 Codex 登录态",
  model: "由 Codex 配置决定",
  keyStatus: "configured",
};

const cadApplicationLabels: Record<CodexConfig["cadApplication"], string> = {
  auto: "AI 自动选软件",
  solidworks: "SolidWorks 三维建模",
  autocad: "AutoCAD 二维图纸",
  both: "SolidWorks + AutoCAD 联动",
};

const cadApplicationRoutes: Record<CodexConfig["cadApplication"], string> = {
  auto: "AI 根据任务自动选择: 三维实体/装配/开孔优先 SolidWorks；DWG/DXF/PDF、国标图纸和批量改图优先 AutoCAD；交付包可联动两者。",
  solidworks: "必须优先调用本机 SolidWorks，通过 solidworks-automation 的 Python COM 封装完成三维建模、装配、真实开孔、STEP/STL/SLDPRT 导出和预览复核。",
  autocad: "必须优先调用本机 AutoCAD，通过 autocad-automation 的 Python COM/ActiveX 封装完成 DWG/DXF/PDF 二维绘图、图层、尺寸标注、图框标题栏和原生预览复核。",
  both: "先用 SolidWorks 完成三维实体、装配、开孔和 STEP/STL；再用 AutoCAD 完成 DWG/DXF/PDF 工程图、孔槽定位尺寸、标题栏和图纸复核。",
};

const codexTargets: Record<CodexConfig["target"], string> = {
  auto: "AI 自动判断",
  general_part: "通用零件建模",
  assembly: "装配体与约束",
  shell: "3D 打印外壳建模",
  fixture: "治具/夹具/支架",
  sheet_metal: "钣金展开与折弯",
  holes: "孔槽/螺纹/阵列",
  drawing: "国标 CAD 图纸",
  package: "交付包整理",
  reverse: "逆向建模/草图重建",
  skill: "Skills 规范沉淀",
};

const taskTemplates: Array<{
  key: string;
  tab: ActiveTab;
  title: string;
  detail: string;
  target: CodexConfig["target"];
  output: CodexConfig["expectedOutput"];
  icon: typeof CubeFocus;
}> = [
  { key: "part", tab: "model", title: "通用零件", detail: "拉伸、旋转、孔槽、倒角、圆角和参数表建模", target: "general_part", output: "cad_files", icon: CubeFocus },
  { key: "assembly", tab: "model", title: "装配体", detail: "零件导入、基准约束、干涉检查和爆炸图准备", target: "assembly", output: "cad_files", icon: Graph },
  { key: "fixture", tab: "model", title: "治具夹具", detail: "定位销、压紧位、安装孔、减重槽和 CNC 可加工性", target: "fixture", output: "cad_files", icon: Aperture },
  { key: "sheet", tab: "model", title: "钣金件", detail: "折弯、展开、K 因子、孔位避让和 DXF 展开输出", target: "sheet_metal", output: "drawing_package", icon: Layout },
  { key: "shell", tab: "model", title: "电子外壳", detail: "壁厚、卡扣、螺丝柱、接口开孔和 3D 打印约束", target: "shell", output: "cad_files", icon: Archive },
  { key: "reverse", tab: "model", title: "逆向重建", detail: "根据图片、草图或旧模型重建参数化特征树", target: "reverse", output: "cad_files", icon: ImageSquare },
  { key: "holes", tab: "holes", title: "孔槽工程", detail: "通孔、沉头孔、螺纹孔、长圆孔、接口槽和孔表", target: "holes", output: "cad_files", icon: Ruler },
  { key: "threaded-holes", tab: "holes", title: "螺纹孔", detail: "M3/M4/M5/M6 攻丝底孔、螺纹深度、孔口倒角和孔标注", target: "holes", output: "cad_files", icon: GearSix },
  { key: "counterbore", tab: "holes", title: "沉头/沉孔", detail: "沉头角度、沉孔直径、螺钉规格、装配避让和剖视标注", target: "holes", output: "drawing_package", icon: Aperture },
  { key: "hole-pattern", tab: "holes", title: "阵列孔", detail: "线性阵列、圆周阵列、孔距、基准定位和孔表生成", target: "holes", output: "drawing_package", icon: Graph },
  { key: "interface-cutout", tab: "holes", title: "接口开槽", detail: "USB、网口、按键、散热窗、线束出口和圆角真实切除", target: "holes", output: "cad_files", icon: Ruler },
  { key: "drawing", tab: "drawing", title: "GB/T 图纸", detail: "三视图、剖视、尺寸链、形位公差、技术要求和标题栏", target: "drawing", output: "drawing_package", icon: FilePlus },
  { key: "tolerance", tab: "drawing", title: "公差标注", detail: "尺寸公差、形位公差、表面粗糙度、基准符号和技术要求", target: "drawing", output: "drawing_package", icon: Ruler },
  { key: "bom", tab: "drawing", title: "装配明细", detail: "装配图、爆炸图、BOM、序号球标和采购/加工清单", target: "assembly", output: "drawing_package", icon: Layout },
  { key: "drawing-convert", tab: "drawing", title: "图纸转换", detail: "DWG、DXF、PDF、PNG 预览输出和国标图框检查", target: "drawing", output: "drawing_package", icon: Export },
  { key: "check", tab: "check", title: "制造复核", detail: "真实开孔、壁厚、格式特征、文件 hash 和 Reviewer Gate", target: "package", output: "research_report", icon: ShieldCheck },
  { key: "print-check", tab: "check", title: "3D 打印检查", detail: "壁厚、悬垂、孔径、支撑、装配间隙和 STL 格式特征", target: "package", output: "research_report", icon: Aperture },
  { key: "cnc-check", tab: "check", title: "CNC 检查", detail: "刀具可达性、内圆角、装夹基准、薄壁风险和孔深比", target: "fixture", output: "research_report", icon: CubeFocus },
  { key: "drawing-check", tab: "check", title: "图纸检查", detail: "尺寸链、孔表、标题栏、技术要求、比例和 GB/T 风格复核", target: "drawing", output: "research_report", icon: ShieldCheck },
  { key: "export", tab: "export", title: "一键交付", detail: "STEP、STL、DWG、DXF、PDF、PNG、报告和 Git 记录打包", target: "package", output: "drawing_package", icon: Export },
  { key: "print-export", tab: "export", title: "打印包", detail: "STL、STEP、切片备注、材料建议、方向建议和打印检查报告", target: "package", output: "cad_files", icon: Archive },
  { key: "machining-export", tab: "export", title: "加工包", detail: "STEP、PDF 图纸、DXF 展开、材料规格、表面处理和检验清单", target: "package", output: "drawing_package", icon: Export },
  { key: "audit-export", tab: "export", title: "审计包", detail: "Artifact Ledger、Reviewer Gate、Codex 输出、验证命令和 Git 记录", target: "package", output: "research_report", icon: ShieldCheck },
];

const codexOutputs: Record<CodexConfig["expectedOutput"], string> = {
  auto: "AI 自动选择输出",
  cad_files: "SLDPRT / STEP / STL",
  drawing_package: "DWG / DXF / PDF 图纸包",
  research_report: "调研报告 / 执行建议",
};

const processLabels: Record<CodexConfig["process"], string> = {
  auto: "AI 自动选工艺",
  FDM: "FDM 3D 打印",
  SLA: "SLA 光固化",
  CNC: "CNC 加工",
  sheet_metal: "钣金",
};

const materialLabels: Record<CodexConfig["material"], string> = {
  auto: "AI 自动选材料",
  PLA: "PLA",
  PETG: "PETG",
  ABS: "ABS",
  Al6061: "Al6061",
};

function stateLabel(state: StageState) {
  if (state === "passed") return "通过";
  if (state === "running") return "执行中";
  if (state === "attention") return "注意";
  return "待执行";
}

function jobStatusLabel(status: AutomationJobStatus) {
  if (status === "running") return "执行中";
  if (status === "passed") return "完成";
  if (status === "failed") return "失败";
  if (status === "cancelled") return "已取消";
  if (status === "approval_required") return "待审批";
  return "排队";
}

function jobKindDetail(kind: AutomationJobKind) {
  if (kind === "create_shell") return { title: "新建 CAD 任务", detail: "生成零件、装配、外壳、孔槽和基础检查任务" };
  if (kind === "import_model") return { title: "导入模型", detail: "读取本地 CAD 模型并创建项目上下文" };
  if (kind === "codex_task") return { title: "Codex 执行", detail: "把图形化配置转换为 Codex 非交互执行任务" };
  return { title: "生成交付包", detail: "整理 STEP、STL、PDF、DWG 和交付清单" };
}

function isTauriRuntime() {
  return "__TAURI_INTERNALS__" in window;
}

function isVideoPath(path: string) {
  return /\.(mp4|webm|mov|m4v|avi)$/i.test(path);
}

function displayNameFromPath(path: string) {
  return path.split(/[\\/]/).pop()?.replace(/\.[^.]+$/, "") || "我的壁纸";
}

function revokeObjectUrl(url?: string) {
  if (url?.startsWith("blob:")) URL.revokeObjectURL(url);
}

function wallpaperFromPath(path: string): WallpaperFile {
  return {
    url: convertFileSrc(path),
    name: displayNameFromPath(path),
    kind: isVideoPath(path) ? "video" : "image",
    sourcePath: path,
  };
}

function clampNumber(value: unknown, fallback: number, min: number, max: number) {
  if (typeof value !== "number" || Number.isNaN(value)) return fallback;
  return Math.min(max, Math.max(min, value));
}

function loadSettings(): AppSettings | null {
  try {
    const raw = localStorage.getItem(SETTINGS_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<AppSettings>;
    return {
      activeWallpaper: parsed.customWallpaperPath ? parsed.activeWallpaper ?? "aurora" : parsed.activeWallpaper === "custom" ? "aurora" : parsed.activeWallpaper ?? "aurora",
      customWallpaperPath: parsed.customWallpaperPath,
      wallpaperBrightness: clampNumber(parsed.wallpaperBrightness, 94, 72, 112),
      wallpaperBlur: clampNumber(parsed.wallpaperBlur, 3, 0, 14),
      wallpaperVignette: clampNumber(parsed.wallpaperVignette, 18, 0, 42),
      recentWallpapers: Array.isArray(parsed.recentWallpapers) ? parsed.recentWallpapers.slice(0, 6) : [],
      recentProjectPath: parsed.recentProjectPath,
      apiConfig: parsed.apiConfig
        ? {
            mode: parsed.apiConfig.mode ?? defaultApiConfig.mode,
            providerName: parsed.apiConfig.providerName ?? defaultApiConfig.providerName,
            endpoint: parsed.apiConfig.endpoint ?? defaultApiConfig.endpoint,
            model: parsed.apiConfig.model ?? defaultApiConfig.model,
            keyStatus: parsed.apiConfig.keyStatus ?? defaultApiConfig.keyStatus,
            lastSyncAt: parsed.apiConfig.lastSyncAt,
            sourcePath: parsed.apiConfig.sourcePath,
          }
        : defaultApiConfig,
    };
  } catch {
    return null;
  }
}

function loadLocalQueue(): AutomationJob[] {
  try {
    const raw = localStorage.getItem(QUEUE_KEY);
    if (!raw) return [];
    const jobs = JSON.parse(raw);
    return Array.isArray(jobs) ? jobs.slice(0, 8) : [];
  } catch {
    return [];
  }
}

function loadAgentChat(): AgentChatMessage[] {
  try {
    const raw = localStorage.getItem(CHAT_KEY);
    if (!raw) return [];
    const messages = JSON.parse(raw);
    return Array.isArray(messages) ? messages.slice(-30) : [];
  } catch {
    return [];
  }
}

function createChatMessage(role: AgentChatMessage["role"], content: string, jobId?: string): AgentChatMessage {
  return {
    id: `msg-${Date.now()}-${Math.random().toString(16).slice(2, 8)}`,
    role,
    content,
    at: new Date().toISOString(),
    jobId,
  };
}

function formatTimeLabel(value?: string) {
  if (!value) return "刚刚";
  if (value.startsWith("unix:")) return value;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

function eventTypeLabel(type?: string) {
  if (!type) return "执行记录";
  if (type.includes("approval")) return "审批";
  if (type.includes("codex.started")) return "AI 启动";
  if (type.includes("codex.completed")) return "AI 结束";
  if (type.includes("heartbeat")) return "心跳";
  if (type.includes("claimed")) return "接单";
  if (type.includes("failed")) return "失败";
  if (type.includes("passed")) return "完成";
  if (type.includes("review")) return "复核";
  if (type.includes("artifact")) return "交付物";
  if (type.includes("step")) return "步骤";
  return type.replaceAll(".", " ");
}

function workerLogMessage(entry: WorkerLogEntry | string) {
  if (typeof entry === "string") return entry;
  return entry.message || entry.status || "worker 已更新任务状态";
}

function workerLogTime(entry: WorkerLogEntry | string) {
  return typeof entry === "string" ? "" : entry.at;
}

function compactJobMessage(job: AutomationJob, events?: QueueEvent[]) {
  return (
    (job.status === "approval_required" ? job.approvalReasons?.[0] : undefined) ||
    events?.[events.length - 1]?.message ||
    (job.reviewGate?.status ? `复核结果: ${job.reviewGate.status}` : undefined) ||
    job.lastMessage ||
    job.result?.message ||
    job.result?.outputPath ||
    job.error ||
    job.detail
  );
}

function buildChatPrompt(config: CodexConfig, api: ApiIntegrationConfig, userText: string, history: AgentChatMessage[], projectPath?: string) {
  const recentHistory = history
    .slice(-8)
    .map((message) => `${message.role === "user" ? "用户" : message.role === "assistant" ? "AI" : "系统"}: ${message.content}`)
    .join("\n");
  return [
    buildCodexPrompt(config, projectPath),
    "",
    "CAD Studio 对话执行要求:",
    "- 你正在响应软件内的 AI 执行对话框，不要输出隐藏推理；请输出可给用户看的执行计划、关键决策、工具调用结果、文件路径和验证结论。",
    "- 如果用户说继续改、重做、调整审美或补充尺寸，需要基于上文和本地文件继续推进，而不是从零开始。",
    "- 面向普通用户表达，不暴露无关开发者配置；必要的命令、文件路径和失败原因要写清楚。",
    "- 若涉及 SolidWorks 或 AutoCAD，本轮仍遵循本地 skills 和中国机械制图/可制造规范。",
    `- 当前 AI 接入方式: ${apiModeLabel(api.mode)}；Provider: ${api.providerName}；Endpoint: ${api.endpoint}；Model: ${api.model}；Key: ${keyStatusLabel(api.keyStatus)}。`,
    "",
    "最近对话:",
    recentHistory || "暂无历史对话。",
    "",
    "用户本次指令:",
    userText,
  ].join("\n");
}

function apiModeLabel(mode: ApiIntegrationMode) {
  if (mode === "cc_switch") return "同步 CC Switch";
  if (mode === "openai_compatible") return "OpenAI 兼容 API";
  if (mode === "manual") return "手动 API";
  return "Codex CLI";
}

function keyStatusLabel(status: ApiIntegrationConfig["keyStatus"]) {
  if (status === "synced") return "已同步";
  if (status === "configured") return "已配置";
  return "未配置";
}

function createJob(kind: AutomationJobKind, projectPath?: string, overrides: Partial<AutomationJob> = {}): AutomationJob {
  const now = new Date().toISOString();
  const copy = jobKindDetail(kind);
  return {
    schemaVersion: "1.0",
    id: `job-${Date.now()}-${Math.random().toString(16).slice(2, 8)}`,
    runId: `run-${Date.now()}-${Math.random().toString(16).slice(2, 8)}`,
    kind,
    title: copy.title,
    detail: projectPath ? `${copy.detail} · ${displayNameFromPath(projectPath)}` : copy.detail,
    status: "queued",
    progress: 0,
    createdAt: now,
    updatedAt: now,
    requestedBy: "local-user",
    createdByAppVersion: APP_VERSION,
    policy: {
      sandbox: "workspace-write",
      approval: "never",
      requireSkillRead: true,
      requireTests: true,
      requireCommit: true,
      requirePush: false,
      requireReviewerPass: true,
    },
    artifacts: [],
    projectPath,
    ...overrides,
  };
}

function buildCodexPrompt(config: CodexConfig, projectPath?: string) {
  const strictRules = [
    "用户未明确指定的建模类型、工艺、材料、输出格式、尺寸细节和检查项，由 AI 根据工程目标自动选择最佳方案，并在结果中说明选择理由。",
    config.realCutouts ? "所有孔、槽、螺纹、接口和减重结构必须是真实几何特征，不能只画线或只做外观标记。" : "如果涉及孔槽，需要明确说明当前是否已真实切除。",
    config.strictGbDrawing ? "CAD 图纸必须按中国机械制图常用格式复核，尺寸链、孔表、技术要求、图框标题栏要完整。" : "图纸输出需要标明当前规范覆盖范围。",
    "结果必须保存到用户指定的本地输出目录，不向 GitHub 或外部服务发布。",
  ];

  return [
    "你是 Codex，请执行由 CAD Studio 图形化界面生成的任务。",
    "",
    `任务目标: ${config.objective}`,
    `目标 CAD 软件: ${cadApplicationLabels[config.cadApplication]}`,
    `软件路由策略: ${cadApplicationRoutes[config.cadApplication]}`,
    `任务类型: ${codexTargets[config.target]}`,
    `期望输出: ${codexOutputs[config.expectedOutput]}`,
    `项目/模型路径: ${projectPath || "未指定"}`,
    `制造方式: ${processLabels[config.process]}`,
    `材料: ${materialLabels[config.material]}`,
    `单位: ${config.unit}`,
    `参考包络尺寸: ${config.length} x ${config.width} x ${config.height} ${config.unit}`,
    `参考壁厚/板厚: ${config.wallThickness} ${config.unit}`,
    `输出目录: ${config.outputDir}`,
    `Skill 路径: ${CODEX_SKILL_PATH}`,
    `AutoCAD 子技能路径: ${AUTOCAD_SKILL_PATH}`,
    "",
    "强制规则:",
    ...strictRules.map((rule) => `- ${rule}`),
    "",
    "自动决策规则:",
    "- 若某项为 AI 自动判断/选择，先根据用户目标、输入文件、制造方式、成本、强度、可加工性和交付要求做最佳选择。",
    "- 自动选择后必须在 summary 或 verification 中解释为什么这么选。",
    "- 若信息不足以可靠决策，先采用行业常用保守方案，并标记残余风险。",
    "",
    "执行方式:",
    "- 必须把 CAD Studio 的图形化配置转换成可执行的本地 CAD 自动化任务。",
    "- 三维实体、装配、开孔、钣金、STEP/STL/SLDPRT 导出优先调用 SolidWorks。",
    "- 二维 DWG/DXF/PDF、国标图纸、尺寸链、孔表、图框标题栏优先调用 AutoCAD。",
    "- 若目标软件为 AI 自动选软件，需要先判断本任务应该调用 SolidWorks、AutoCAD 或两者联动，并说明理由。",
    "- 优先使用 solidworks-automation skill 及其 SolidWorks/AutoCAD 子技能。",
    "- 先检查现有文件和规范，再小步实现。",
    "- 结束时用中文说明输出文件、验证结果和本地保存位置。",
  ].join("\n");
}

function App() {
  const [activeTab, setActiveTab] = useState<ActiveTab>("project");
  const [activeWallpaper, setActiveWallpaper] = useState<WallpaperId>("aurora");
  const [customWallpaper, setCustomWallpaper] = useState<WallpaperFile | null>(null);
  const [appearanceOpen, setAppearanceOpen] = useState(false);
  const [wallpaperBrightness, setWallpaperBrightness] = useState(94);
  const [wallpaperBlur, setWallpaperBlur] = useState(3);
  const [wallpaperVignette, setWallpaperVignette] = useState(18);
  const [recentWallpapers, setRecentWallpapers] = useState<RecentWallpaper[]>([]);
  const [recentProjectPath, setRecentProjectPath] = useState<string | undefined>();
  const [apiConfig, setApiConfig] = useState<ApiIntegrationConfig>(defaultApiConfig);
  const [ccSwitchSync, setCcSwitchSync] = useState<CcSwitchSync | null>(null);
  const [apiSyncMessage, setApiSyncMessage] = useState("可同步 CC Switch，也可继续使用本机 Codex CLI。");
  const [settingsLoaded, setSettingsLoaded] = useState(false);
  const [queueLoaded, setQueueLoaded] = useState(false);
  const [jobs, setJobs] = useState<AutomationJob[]>([]);
  const [jobEvents, setJobEvents] = useState<Record<string, QueueEvent[]>>({});
  const [jobLogTails, setJobLogTails] = useState<Record<string, QueueLogTail>>({});
  const [expandedJobId, setExpandedJobId] = useState<string | null>(null);
  const [activeAgentJobId, setActiveAgentJobId] = useState<string | null>(null);
  const [agentMessages, setAgentMessages] = useState<AgentChatMessage[]>([]);
  const [agentInput, setAgentInput] = useState("");
  const [workerStatus, setWorkerStatus] = useState<WorkerStatus>({ running: false, message: "桌面端可启动" });
  const [windowHint, setWindowHint] = useState("窗口控制就绪");
  const [codexConfig, setCodexConfig] = useState<CodexConfig>({
    objective: "根据用户输入自动判断最佳 CAD 任务类型、制造方式、材料和交付格式，生成可制造结果并解释选择理由。",
    cadApplication: "auto",
    target: "auto",
    expectedOutput: "auto",
    process: "auto",
    material: "auto",
    unit: "mm",
    length: 120,
    width: 80,
    height: 35,
    wallThickness: 1.6,
    outputDir: "Documents/CADAutomationWorkbench",
    strictGbDrawing: true,
    realCutouts: true,
    localCadAutomation: true,
  });
  const [isRunning, setIsRunning] = useState(false);
  const [focusFeature, setFocusFeature] = useState(0);
  const wallpaperInputRef = useRef<HTMLInputElement>(null);
  const completedChatJobIdsRef = useRef<Set<string>>(new Set());
  const reducedMotion = useReducedMotion();

  const visualStages = useMemo(() => {
    if (!isRunning) return stages;
    return stages.map((stage, index) => ({
      ...stage,
      state: index === 1 ? "running" : stage.state,
      detail: index === 1 ? "正在生成 CAD 特征" : stage.detail,
    })) as Stage[];
  }, [isRunning]);

  const queueSummary = useMemo(() => {
    const approvalRequired = jobs.filter((job) => job.status === "approval_required").length;
    const running = jobs.filter((job) => job.status === "running").length;
    const queued = jobs.filter((job) => job.status === "queued").length;
    if (approvalRequired > 0) return `${approvalRequired} 个待审批`;
    if (running > 0) return `${running} 个执行中`;
    if (queued > 0) return `${queued} 个排队`;
    return jobs.length > 0 ? "队列就绪" : "暂无任务";
  }, [jobs]);

  const workerLabel = useMemo(() => {
    const health = workerStatus.health?.status;
    if (workerStatus.running) return health ? `Worker ${health}` : `Worker ${workerStatus.pid ?? ""}`;
    if (health) return `上次 ${health}`;
    return workerStatus.message;
  }, [workerStatus]);

  const currentPage = pageCopy[activeTab];
  const visibleTemplates = useMemo(() => {
    if (activeTab === "project") return taskTemplates.slice(0, 6);
    if (activeTab === "settings") return taskTemplates.filter((item) => item.target === "skill" || item.target === "package");
    return taskTemplates.filter((item) => item.tab === activeTab);
  }, [activeTab]);

  const activeAgentJob = useMemo(() => jobs.find((job) => job.id === activeAgentJobId) ?? jobs.find((job) => job.uiConfig?.agentChat === true) ?? jobs[0], [activeAgentJobId, jobs]);
  const codexPrompt = useMemo(() => buildCodexPrompt(codexConfig, recentProjectPath), [codexConfig, recentProjectPath]);

  function updateCodexConfig(patch: Partial<CodexConfig>) {
    setCodexConfig((config) => ({ ...config, ...patch }));
  }

  async function persistJob(job: AutomationJob) {
    if (isTauriRuntime()) {
      await invoke("save_queue_job", { job });
    }
  }

  function saveLocalQueue(nextJobs: AutomationJob[]) {
    if (!isTauriRuntime()) localStorage.setItem(QUEUE_KEY, JSON.stringify(nextJobs));
  }

  function upsertJob(nextJob: AutomationJob) {
    setJobs((items) => {
      const exists = items.some((item) => item.id === nextJob.id);
      const next = exists ? items.map((item) => (item.id === nextJob.id ? nextJob : item)) : [nextJob, ...items].slice(0, 8);
      saveLocalQueue(next);
      return next;
    });
    void persistJob(nextJob);
  }

  function updateJob(id: string, updater: (job: AutomationJob) => AutomationJob) {
    let changedJob: AutomationJob | undefined;
    setJobs((items) => {
      const next = items.map((item) => {
        if (item.id !== id) return item;
        changedJob = updater(item);
        return changedJob;
      });
      saveLocalQueue(next);
      return next;
    });
    if (changedJob) void persistJob(changedJob);
  }

  async function refreshWorkerStatus() {
    if (!isTauriRuntime()) {
      setWorkerStatus({ running: false, message: "浏览器预览不启动 worker" });
      return;
    }
    try {
      const status = await invoke<WorkerStatus>("worker_status");
      setWorkerStatus(status);
    } catch (error) {
      setWorkerStatus({ running: false, message: `worker 状态读取失败: ${String(error)}` });
    }
  }

  async function startLocalWorker() {
    if (!isTauriRuntime()) {
      setWorkerStatus({ running: false, message: "请在桌面端启动 worker" });
      return;
    }
    try {
      const status = await invoke<WorkerStatus>("start_worker", {
        repoPath: CODEX_CWD,
        enableCodex: true,
        codexFullAccess: codexConfig.localCadAutomation,
      });
      setWorkerStatus(status);
    } catch (error) {
      setWorkerStatus({ running: false, message: `worker 启动失败: ${String(error)}` });
    }
  }

  async function stopLocalWorker() {
    if (!isTauriRuntime()) return;
    try {
      const status = await invoke<WorkerStatus>("stop_worker");
      setWorkerStatus(status);
    } catch (error) {
      setWorkerStatus({ running: false, message: `worker 停止失败: ${String(error)}` });
    }
  }

  async function syncCcSwitchConfig() {
    if (!isTauriRuntime()) {
      setApiSyncMessage("浏览器预览不能读取本机 CC Switch 配置，请在桌面版中同步。");
      return;
    }
    setApiSyncMessage("正在读取 CC Switch 配置...");
    try {
      const sync = await invoke<CcSwitchSync>("sync_cc_switch_config");
      const provider =
        sync.codexProviders?.find((item) => item.active) ||
        sync.codexProviders?.[0] ||
        sync.claudeProviders?.find((item) => item.active) ||
        sync.claudeProviders?.[0];
      const nextConfig: ApiIntegrationConfig = {
        mode: "cc_switch",
        providerName: provider?.name || provider?.id || "CC Switch",
        endpoint: provider?.endpoint || "由 CC Switch 配置决定",
        model: provider?.model || "由 CC Switch 配置决定",
        keyStatus: provider?.hasApiKey ? "synced" : "missing",
        lastSyncAt: sync.syncedAt,
        sourcePath: sync.configPath,
      };
      setCcSwitchSync(sync);
      setApiConfig(nextConfig);
      setApiSyncMessage(provider?.hasApiKey ? "已同步 CC Switch 配置，密钥仅显示脱敏状态。" : "已同步 CC Switch，但当前 provider 没检测到 API Key。");
    } catch (error) {
      setApiSyncMessage(`同步失败: ${String(error)}`);
    }
  }

  function simulateJob(job: AutomationJob) {
    window.setTimeout(() => {
      updateJob(job.id, (item) => ({ ...item, status: "running", progress: 18, updatedAt: new Date().toISOString() }));
      setIsRunning(true);
    }, 220);
    window.setTimeout(() => {
      updateJob(job.id, (item) => (item.status === "cancelled" ? item : { ...item, status: "running", progress: 62, updatedAt: new Date().toISOString() }));
    }, 1200);
    window.setTimeout(() => {
      updateJob(job.id, (item) => (item.status === "cancelled" ? item : { ...item, status: "passed", progress: 100, updatedAt: new Date().toISOString() }));
      setIsRunning(false);
    }, 2300);
  }

  function enqueueAutomation(kind: AutomationJobKind, projectPath?: string) {
    const job = createJob(kind, projectPath);
    upsertJob(job);
    if (!isTauriRuntime()) simulateJob(job);
  }

  function enqueueCodexTask() {
    enqueueCodexTaskWithConfig(codexConfig);
  }

  function enqueueCodexTaskWithConfig(config: CodexConfig) {
    const strictRules = [
      config.realCutouts ? "孔槽、接口、沉头和螺纹必须是真实几何切除" : "明确说明孔槽实现状态",
      config.strictGbDrawing ? "必须按中国机械制图常用格式复核 CAD 图纸" : "说明当前图纸规范覆盖范围",
      `${cadApplicationLabels[config.cadApplication]}: ${cadApplicationRoutes[config.cadApplication]}`,
      config.localCadAutomation ? "允许经审批后调用本机 SolidWorks / AutoCAD 桌面自动化能力。" : "不直接调用本机 CAD 软件，仅生成计划、脚本或说明。",
      `所有交付物只保存到本地输出目录: ${config.outputDir}`,
    ];
    const capabilities = config.localCadAutomation ? ["cad_macro"] : [];
    const job = createJob("codex_task", recentProjectPath, {
      executor: "codex",
      title: "Codex 执行",
      detail: `${cadApplicationLabels[config.cadApplication]} · ${codexTargets[config.target]} · ${codexOutputs[config.expectedOutput]}`,
      objective: config.objective,
      targetSoftware: cadApplicationLabels[config.cadApplication],
      target: codexTargets[config.target],
      expectedOutput: codexOutputs[config.expectedOutput],
      strictRules,
      capabilities,
      prompt: buildCodexPrompt(config, recentProjectPath),
      cwd: CODEX_CWD,
      skillPath: CODEX_SKILL_PATH,
      policy: {
        sandbox: config.localCadAutomation ? "danger-full-access" : "workspace-write",
        approval: "never",
        requireSkillRead: true,
        requireTests: true,
        requireCommit: false,
        requirePush: false,
        requireReviewerPass: true,
      },
      uiConfig: {
        cadRuntime: {
          application: config.cadApplication,
          applicationLabel: cadApplicationLabels[config.cadApplication],
          route: cadApplicationRoutes[config.cadApplication],
          localCadAutomation: config.localCadAutomation,
          solidworksSkillPath: CODEX_SKILL_PATH,
          autocadSkillPath: AUTOCAD_SKILL_PATH,
        },
        manufacturing: {
          process: config.process,
          processLabel: processLabels[config.process],
          material: config.material,
          materialLabel: materialLabels[config.material],
          unit: config.unit,
        },
        selection: {
          mode: "auto_best",
          autoTarget: config.target === "auto",
          autoCadApplication: config.cadApplication === "auto",
          autoOutput: config.expectedOutput === "auto",
          autoProcess: config.process === "auto",
          autoMaterial: config.material === "auto",
          instruction: "未指定字段由 AI 自动选择最佳工程方案、目标 CAD 软件和执行路线，并说明理由。",
        },
        geometry: {
          length: config.length,
          width: config.width,
          height: config.height,
          wallThickness: config.wallThickness,
        },
        gates: {
          realCutouts: config.realCutouts,
          strictGbDrawing: config.strictGbDrawing,
          localCadAutomation: config.localCadAutomation,
        },
        outputDir: config.outputDir,
      },
    });
    upsertJob(job);
    if (!isTauriRuntime()) simulateJob(job);
  }

  function submitAgentMessage() {
    const text = agentInput.trim();
    if (!text) return;

    const userMessage = createChatMessage("user", text);
    const prompt = buildChatPrompt(codexConfig, apiConfig, text, [...agentMessages, userMessage], recentProjectPath);
    const job = createJob("codex_task", recentProjectPath, {
      executor: "codex",
      title: "AI 对话执行",
      detail: `${cadApplicationLabels[codexConfig.cadApplication]} · ${codexTargets[codexConfig.target]} · 可继续追问修改`,
      objective: text,
      targetSoftware: cadApplicationLabels[codexConfig.cadApplication],
      target: codexTargets[codexConfig.target],
      expectedOutput: codexOutputs[codexConfig.expectedOutput],
      strictRules: [
        "以软件内 AI 对话形式响应用户，输出可公开的步骤摘要、执行结果和文件位置。",
        codexConfig.realCutouts ? "涉及孔槽时必须是真实几何开孔/切除。" : "涉及孔槽时必须说明实现状态。",
        codexConfig.strictGbDrawing ? "涉及图纸时必须遵循中国常用机械制图规范并复核尺寸链。" : "涉及图纸时说明规范覆盖范围。",
        "所有交付物只保存到用户指定的本地输出目录。",
      ],
      capabilities: codexConfig.localCadAutomation ? ["cad_macro"] : [],
      prompt,
      cwd: CODEX_CWD,
      skillPath: CODEX_SKILL_PATH,
      policy: {
        sandbox: codexConfig.localCadAutomation ? "danger-full-access" : "workspace-write",
        approval: "never",
        requireSkillRead: true,
        requireTests: true,
        requireCommit: false,
        requirePush: false,
        requireReviewerPass: true,
      },
      uiConfig: {
        agentChat: true,
        outputDir: codexConfig.outputDir,
        sourceJobId: activeAgentJob?.id,
        apiRuntime: apiConfig,
        cadRuntime: {
          application: codexConfig.cadApplication,
          applicationLabel: cadApplicationLabels[codexConfig.cadApplication],
          route: cadApplicationRoutes[codexConfig.cadApplication],
          localCadAutomation: codexConfig.localCadAutomation,
          solidworksSkillPath: CODEX_SKILL_PATH,
          autocadSkillPath: AUTOCAD_SKILL_PATH,
        },
      },
    });

    setAgentInput("");
    setActiveAgentJobId(job.id);
    setExpandedJobId(job.id);
    setAgentMessages((messages) => [
      ...messages,
      userMessage,
      createChatMessage("assistant", "收到，我已经把这句话转成一条本地 Codex 执行任务。你可以在下方看到公开步骤、审批、日志和结果；不满意就继续补充要求。", job.id),
    ].slice(-40));
    upsertJob(job);
    if (!isTauriRuntime()) simulateJob(job);
    if (isTauriRuntime() && !workerStatus.running) void startLocalWorker();
  }

  function enqueueTemplateTask(template: (typeof taskTemplates)[number]) {
    const nextConfig = {
      ...codexConfig,
      target: template.target,
      expectedOutput: template.output,
      objective: `${template.title}: ${template.detail}。请根据用户导入的资料或当前配置生成可制造 CAD 结果，并输出必要的复核记录。`,
    } satisfies CodexConfig;
    setCodexConfig(nextConfig);
    enqueueCodexTaskWithConfig(nextConfig);
  }

  function cancelJob(id: string) {
    updateJob(id, (item) => ({ ...item, status: "cancelled", progress: 0, updatedAt: new Date().toISOString() }));
  }

  async function approveJob(id: string) {
    if (isTauriRuntime()) {
      try {
        const approvedJob = await invoke<AutomationJob>("approve_queue_job", { id });
        upsertJob(approvedJob);
      } catch (error) {
        updateJob(id, (item) => ({
          ...item,
          lastMessage: `审批失败: ${String(error)}`,
          updatedAt: new Date().toISOString(),
        }));
      }
      return;
    }

    updateJob(id, (item) => ({
      ...item,
      status: "queued",
      approvedAt: new Date().toISOString(),
      approvedBy: "local-user",
      approvedPolicyReasons: item.approvalReasons ?? [],
      lastMessage: "人工审批已通过，任务重新进入队列。",
      updatedAt: new Date().toISOString(),
    }));
  }

  function rememberWallpaper(path: string) {
    const nextWallpaper = {
      path,
      name: displayNameFromPath(path),
      kind: isVideoPath(path) ? "video" : "image",
    } satisfies RecentWallpaper;

    setRecentWallpapers((items) => [nextWallpaper, ...items.filter((item) => item.path !== path)].slice(0, 6));
  }

  function useWallpaperFile(file?: File) {
    if (!file) return;
    const isImage = file.type.startsWith("image/");
    const isVideo = file.type.startsWith("video/");
    if (!isImage && !isVideo) return;

    setCustomWallpaper((previous) => {
      revokeObjectUrl(previous?.url);
      return {
        url: URL.createObjectURL(file),
        name: file.name.replace(/\.[^.]+$/, ""),
        kind: isVideo ? "video" : "image",
      };
    });
    setActiveWallpaper("custom");
    setAppearanceOpen(true);
  }

  function applyWallpaperPath(path: string) {
    setCustomWallpaper((previous) => {
      revokeObjectUrl(previous?.url);
      return wallpaperFromPath(path);
    });
    rememberWallpaper(path);
    setActiveWallpaper("custom");
    setAppearanceOpen(true);
  }

  async function chooseWallpaper() {
    if (!isTauriRuntime()) {
      wallpaperInputRef.current?.click();
      return;
    }

    const selected = await openDialog({
      multiple: false,
      filters: [
        {
          name: "Wallpapers",
          extensions: ["png", "jpg", "jpeg", "webp", "gif", "bmp", "mp4", "webm", "mov", "m4v", "avi"],
        },
      ],
    });

    if (!selected || Array.isArray(selected)) return;

    applyWallpaperPath(selected);
  }

  async function chooseProjectFile() {
    if (!isTauriRuntime()) {
      enqueueAutomation("import_model");
      return;
    }

    const selected = await openDialog({
      multiple: false,
      filters: [
        {
          name: "CAD Models",
          extensions: ["step", "stp", "sldprt", "sldasm", "stl", "iges", "igs", "dxf", "dwg"],
        },
      ],
    });

    if (!selected || Array.isArray(selected)) return;
    setRecentProjectPath(selected);
    enqueueAutomation("import_model", selected);
  }

  async function chooseOutputDir() {
    if (!isTauriRuntime()) return;

    const selected = await openDialog({
      multiple: false,
      directory: true,
    });

    if (!selected || Array.isArray(selected)) return;
    updateCodexConfig({ outputDir: selected });
  }

  function importWallpaper(event: ChangeEvent<HTMLInputElement>) {
    useWallpaperFile(event.target.files?.[0]);
    event.target.value = "";
  }

  function dropWallpaper(event: DragEvent<HTMLButtonElement>) {
    event.preventDefault();
    useWallpaperFile(event.dataTransfer.files?.[0]);
  }

  async function controlWindow(action: "close" | "minimize" | "maximize") {
    const labels = { close: "关闭", minimize: "最小化", maximize: "最大化/还原" };
    if (!isTauriRuntime()) {
      setWindowHint("浏览器预览不控制窗口，桌面版可用");
      return;
    }
    try {
      const appWindow = getCurrentWindow();
      setWindowHint(`正在${labels[action]}`);
      if (action === "close") await appWindow.close();
      if (action === "minimize") await appWindow.minimize();
      if (action === "maximize") {
        if (await appWindow.isMaximized()) {
          await appWindow.unmaximize();
          setWindowHint("窗口已还原");
          return;
        }
        await appWindow.maximize();
      }
      if (action !== "close") setWindowHint(`窗口已${labels[action]}`);
    } catch (error) {
      console.error(error);
      setWindowHint("窗口控制失败，请重启桌面版后再试");
    }
  }

  useEffect(() => {
    return () => {
      revokeObjectUrl(customWallpaper?.url);
    };
  }, [customWallpaper?.url]);

  useEffect(() => {
    const settings = loadSettings();
    if (settings) {
      setActiveWallpaper(settings.activeWallpaper);
      setWallpaperBrightness(settings.wallpaperBrightness);
      setWallpaperBlur(settings.wallpaperBlur);
      setWallpaperVignette(settings.wallpaperVignette);
      setRecentWallpapers(settings.recentWallpapers);
      setRecentProjectPath(settings.recentProjectPath);
      setApiConfig(settings.apiConfig ?? defaultApiConfig);
      if (settings.customWallpaperPath) setCustomWallpaper(wallpaperFromPath(settings.customWallpaperPath));
    }
    setSettingsLoaded(true);
  }, []);

  useEffect(() => {
    const savedMessages = loadAgentChat();
    setAgentMessages(
      savedMessages.length > 0
        ? savedMessages
        : [
            createChatMessage(
              "assistant",
              "你好，我是 CAD Studio 的 AI 执行助手。直接告诉我你要建模、改图、开孔、出图或打包交付，我会把要求交给本地 Codex 执行，并把可见过程显示在这里。",
            ),
          ],
    );
  }, []);

  useEffect(() => {
    if (agentMessages.length === 0) return;
    localStorage.setItem(CHAT_KEY, JSON.stringify(agentMessages.slice(-40)));
  }, [agentMessages]);

  useEffect(() => {
    let disposed = false;

    async function loadQueue() {
      if (!isTauriRuntime()) {
        setJobs(loadLocalQueue());
        setQueueLoaded(true);
        return;
      }

      try {
        const savedJobs = await invoke<AutomationJob[]>("read_queue_jobs");
        if (disposed) return;
        const nextJobs = savedJobs
          .filter((job) => typeof job.id === "string")
          .sort((a, b) => (b.updatedAt || "").localeCompare(a.updatedAt || ""))
          .slice(0, 8);
        setJobs(nextJobs);
        const visibleJobIds = Array.from(new Set([...nextJobs.slice(0, 4).map((job) => job.id), activeAgentJobId, expandedJobId].filter(Boolean))) as string[];
        const eventPairs = await Promise.all(visibleJobIds.map(async (id) => [id, await invoke<QueueEvent[]>("read_queue_events", { id })] as const));
        const logPairs = await Promise.all(
          visibleJobIds.map(async (id) => {
            try {
              return [id, await invoke<QueueLogTail>("read_queue_log_tail", { id })] as const;
            } catch {
              return [id, {}] as const;
            }
          }),
        );
        if (!disposed) setJobEvents(Object.fromEntries(eventPairs));
        if (!disposed) setJobLogTails(Object.fromEntries(logPairs));
      } finally {
        if (!disposed) setQueueLoaded(true);
      }
    }

    void loadQueue();
    if (!isTauriRuntime()) return () => {
      disposed = true;
    };

    const timer = window.setInterval(() => void loadQueue(), 1400);
    return () => {
      disposed = true;
      window.clearInterval(timer);
    };
  }, [activeAgentJobId, expandedJobId]);

  useEffect(() => {
    void refreshWorkerStatus();
    if (!isTauriRuntime()) return;
    const timer = window.setInterval(() => void refreshWorkerStatus(), 2200);
    return () => window.clearInterval(timer);
  }, []);

  useEffect(() => {
    setIsRunning(jobs.some((job) => job.status === "running"));
  }, [jobs]);

  useEffect(() => {
    const updates: AgentChatMessage[] = [];
    for (const job of jobs) {
      if (job.uiConfig?.agentChat !== true) continue;
      if (!["passed", "failed", "approval_required", "cancelled"].includes(job.status)) continue;
      const marker = `${job.id}:${job.status}`;
      if (completedChatJobIdsRef.current.has(marker)) continue;
      completedChatJobIdsRef.current.add(marker);

      if (job.status === "passed") {
        const lines = [
          "这轮执行已完成。",
          job.result?.message,
          job.result?.outputPath ? `输出位置: ${job.result.outputPath}` : undefined,
          job.reviewGate?.status ? `复核结果: ${job.reviewGate.status}` : undefined,
        ].filter(Boolean);
        updates.push(createChatMessage("assistant", lines.join("\n"), job.id));
      } else if (job.status === "approval_required") {
        updates.push(createChatMessage("assistant", `这轮需要你先批准本机自动化权限：${job.approvalReasons?.join("；") || "需要人工确认后继续执行。"}`, job.id));
      } else if (job.status === "failed") {
        updates.push(createChatMessage("assistant", `这轮执行失败了：${job.error || job.lastMessage || "未知错误"}\n你可以直接补充一句“继续修复这个错误”。`, job.id));
      } else if (job.status === "cancelled") {
        updates.push(createChatMessage("assistant", "这轮任务已经取消。你可以换一种要求重新发起。", job.id));
      }
    }
    if (updates.length > 0) setAgentMessages((messages) => [...messages, ...updates].slice(-40));
  }, [jobs]);

  useEffect(() => {
    if (!settingsLoaded) return;
    const settings: AppSettings = {
      activeWallpaper: activeWallpaper === "custom" && !customWallpaper?.sourcePath ? "aurora" : activeWallpaper,
      customWallpaperPath: customWallpaper?.sourcePath,
      wallpaperBrightness,
      wallpaperBlur,
      wallpaperVignette,
      recentWallpapers,
      recentProjectPath,
      apiConfig,
    };
    localStorage.setItem(SETTINGS_KEY, JSON.stringify(settings));
  }, [activeWallpaper, apiConfig, customWallpaper?.sourcePath, recentProjectPath, recentWallpapers, settingsLoaded, wallpaperBlur, wallpaperBrightness, wallpaperVignette]);

  const activeWallpaperName =
    activeWallpaper === "custom" ? customWallpaper?.name ?? "我的壁纸" : wallpapers.find((item) => item.id === activeWallpaper)?.name ?? "Aurora";
  const activeAgentEvents = activeAgentJob ? jobEvents[activeAgentJob.id] ?? [] : [];
  const activeAgentLogs = activeAgentJob ? jobLogTails[activeAgentJob.id] ?? {} : {};

  return (
    <main
      className={`app-shell theme-${activeWallpaper}`}
      style={
        {
          "--wallpaper-brightness": `${wallpaperBrightness}%`,
          "--wallpaper-blur": `${wallpaperBlur}px`,
          "--wallpaper-vignette": `${wallpaperVignette / 100}`,
        } as CSSProperties
      }
    >
      <div className="wallpaper" aria-hidden="true">
        <AnimatePresence>
          {customWallpaper && activeWallpaper === "custom" ? (
            customWallpaper.kind === "video" ? (
              <motion.video
                className="custom-wallpaper-layer custom-wallpaper-video"
                src={customWallpaper.url}
                autoPlay
                loop
                muted
                playsInline
                initial={reducedMotion ? false : { opacity: 0, scale: 1.02 }}
                animate={{ opacity: 1, scale: 1 }}
                exit={reducedMotion ? undefined : { opacity: 0, scale: 1.02 }}
                transition={{ duration: 0.55 }}
              />
            ) : (
              <motion.div
                className="custom-wallpaper-layer"
                style={{ backgroundImage: `url("${customWallpaper.url}")` }}
                initial={reducedMotion ? false : { opacity: 0, scale: 1.02 }}
                animate={{ opacity: 1, scale: 1 }}
                exit={reducedMotion ? undefined : { opacity: 0, scale: 1.02 }}
                transition={{ duration: 0.55 }}
              />
            )
          ) : null}
        </AnimatePresence>
        <motion.span
          className="orb orb-one"
          animate={reducedMotion ? undefined : { x: [0, 32, -18, 0], y: [0, -26, 18, 0] }}
          transition={{ duration: 18, repeat: Infinity, ease: "easeInOut" }}
        />
        <motion.span
          className="orb orb-two"
          animate={reducedMotion ? undefined : { x: [0, -24, 18, 0], y: [0, 28, -16, 0] }}
          transition={{ duration: 22, repeat: Infinity, ease: "easeInOut" }}
        />
        <motion.span
          className="orb orb-three"
          animate={reducedMotion ? undefined : { scale: [1, 1.08, 0.96, 1], opacity: [0.48, 0.66, 0.5, 0.48] }}
          transition={{ duration: 16, repeat: Infinity, ease: "easeInOut" }}
        />
      </div>

      <motion.section
        className="desktop-frame"
        initial={reducedMotion ? false : { y: 24, opacity: 0, scale: 0.985 }}
        animate={{ y: 0, opacity: 1, scale: 1 }}
        transition={{ duration: 0.75, ease: [0.22, 1, 0.36, 1] }}
      >
        <aside className="dock-panel liquid">
          <div className="profile-card">
            <div className="avatar">
              <CubeFocus size={24} weight="duotone" />
            </div>
            <div>
              <strong>CAD Studio</strong>
              <span>本地自动化工作台</span>
            </div>
          </div>

          <nav className="dock-nav" aria-label="主导航">
            {navItems.map(([key, label, Icon]) => (
              <motion.button
                className={activeTab === key ? "dock-item active" : "dock-item"}
                key={key}
                onClick={() => setActiveTab(key)}
                whileHover={reducedMotion ? undefined : { x: 3 }}
                whileTap={{ scale: 0.975 }}
              >
                <Icon size={19} weight="duotone" />
                <span>{label}</span>
              </motion.button>
            ))}
          </nav>

          <motion.button className="local-chip" whileHover={reducedMotion ? undefined : { y: -2 }} whileTap={{ scale: 0.98 }}>
            <ShieldCheck size={18} weight="duotone" />
            <span>工程文件不出电脑</span>
          </motion.button>
        </aside>

        <section className="main-window liquid">
          <header className="window-bar app-toolbar">
            <div className="project-title">
              <strong>{currentPage.title}</strong>
              <span>{recentProjectPath ? `${displayNameFromPath(recentProjectPath)} · SolidWorks 已连接 · 规范库 GB/T` : "本地工作区 · SolidWorks 已连接 · 规范库 GB/T"}</span>
              <small>{windowHint}</small>
            </div>
            <div className="toolbar-actions">
              <motion.button className="icon-button" onClick={() => setAppearanceOpen((value) => !value)} whileHover={reducedMotion ? undefined : { y: -2 }} whileTap={{ scale: 0.96 }}>
                <Aperture size={18} weight="duotone" />
                <span>外观</span>
              </motion.button>
              <motion.button className="icon-button" whileHover={reducedMotion ? undefined : { y: -2 }} whileTap={{ scale: 0.96 }}>
                <GearSix size={18} weight="duotone" />
              </motion.button>
            </div>
            <div className="window-controls" role="group" aria-label="窗口控制">
              <motion.button
                className="window-control minimize"
                type="button"
                title="最小化窗口"
                aria-label="最小化窗口"
                onClick={() => controlWindow("minimize")}
                whileHover={reducedMotion ? undefined : { y: -1 }}
                whileTap={{ scale: 0.96 }}
              >
                <Minus size={14} weight="bold" />
                <span>最小化</span>
              </motion.button>
              <motion.button
                className="window-control maximize"
                type="button"
                title="最大化或还原窗口"
                aria-label="最大化或还原窗口"
                onClick={() => controlWindow("maximize")}
                whileHover={reducedMotion ? undefined : { y: -1 }}
                whileTap={{ scale: 0.96 }}
              >
                <Square size={12} weight="bold" />
                <span>最大化</span>
              </motion.button>
              <motion.button
                className="window-control close"
                type="button"
                title="关闭窗口"
                aria-label="关闭窗口"
                onClick={() => controlWindow("close")}
                whileHover={reducedMotion ? undefined : { y: -1 }}
                whileTap={{ scale: 0.96 }}
              >
                <X size={13} weight="bold" />
                <span>关闭</span>
              </motion.button>
            </div>

            <AnimatePresence>
              {appearanceOpen ? (
                <motion.div
                  className="appearance-popover"
                  initial={reducedMotion ? false : { opacity: 0, y: -10, scale: 0.98 }}
                  animate={{ opacity: 1, y: 0, scale: 1 }}
                  exit={reducedMotion ? undefined : { opacity: 0, y: -10, scale: 0.98 }}
                  transition={{ duration: 0.22 }}
                >
                  <div className="switcher-head">
                    <span>外观</span>
                    <small>{activeWallpaperName}</small>
                  </div>
                  <input ref={wallpaperInputRef} className="wallpaper-input" type="file" accept="image/*,video/*" onChange={importWallpaper} />
                  <button
                    className="drop-wallpaper"
                    onClick={chooseWallpaper}
                    onDragOver={(event) => event.preventDefault()}
                    onDrop={dropWallpaper}
                  >
                    <UploadSimple size={22} weight="duotone" />
                    <strong>导入本地壁纸</strong>
                    <span>支持图片、GIF、视频，拖入这里即可预览</span>
                  </button>
                  <div className="wallpaper-grid compact">
                    {wallpapers.map((wallpaper) => (
                      <motion.button
                        className={activeWallpaper === wallpaper.id ? `wallpaper-tile ${wallpaper.id} active` : `wallpaper-tile ${wallpaper.id}`}
                        key={wallpaper.id}
                        onClick={() => setActiveWallpaper(wallpaper.id)}
                        whileHover={reducedMotion ? undefined : { y: -3 }}
                        whileTap={{ scale: 0.97 }}
                      >
                        <span className="tile-preview" />
                        <strong>{wallpaper.name}</strong>
                      </motion.button>
                    ))}
                    {customWallpaper ? (
                      <motion.button
                        className={activeWallpaper === "custom" ? "wallpaper-tile custom active" : "wallpaper-tile custom"}
                        onClick={() => setActiveWallpaper("custom")}
                        whileHover={reducedMotion ? undefined : { y: -3 }}
                        whileTap={{ scale: 0.97 }}
                      >
                        <span
                          className="tile-preview custom-preview"
                          style={customWallpaper.kind === "image" ? { backgroundImage: `url("${customWallpaper.url}")` } : undefined}
                        >
                          {customWallpaper.kind === "video" ? <Play size={18} weight="fill" /> : null}
                        </span>
                        <strong>我的壁纸</strong>
                      </motion.button>
                    ) : null}
                  </div>
                  {recentWallpapers.length > 0 ? (
                    <div className="recent-wallpapers">
                      <span>最近使用</span>
                      {recentWallpapers.map((wallpaper) => (
                        <button key={wallpaper.path} type="button" onClick={() => applyWallpaperPath(wallpaper.path)}>
                          <ImageSquare size={15} weight="duotone" />
                          <strong>{wallpaper.name}</strong>
                        </button>
                      ))}
                    </div>
                  ) : null}
                  <div className="wallpaper-controls">
                    <label>
                      <span>亮度</span>
                      <input type="range" min="72" max="112" value={wallpaperBrightness} onChange={(event) => setWallpaperBrightness(Number(event.target.value))} />
                    </label>
                    <label>
                      <span>模糊</span>
                      <input type="range" min="0" max="14" value={wallpaperBlur} onChange={(event) => setWallpaperBlur(Number(event.target.value))} />
                    </label>
                    <label>
                      <span>暗角</span>
                      <input type="range" min="0" max="42" value={wallpaperVignette} onChange={(event) => setWallpaperVignette(Number(event.target.value))} />
                    </label>
                  </div>
                </motion.div>
              ) : null}
            </AnimatePresence>
          </header>

          <section className="workbench-head">
            <div>
              <p className="eyebrow">LOCAL CAD WORKBENCH</p>
              <h1>{currentPage.title}</h1>
              <p className="subtitle">{currentPage.subtitle}</p>
            </div>
            <div className="command-row">
              <motion.button className="primary-button shine" onClick={() => setActiveTab("model")} whileHover={reducedMotion ? undefined : { y: -2 }} whileTap={{ scale: 0.975 }}>
                <FilePlus size={18} weight="duotone" />
                新建 CAD 任务
              </motion.button>
              <motion.button className="ghost-button" onClick={chooseProjectFile} whileHover={reducedMotion ? undefined : { y: -2 }} whileTap={{ scale: 0.975 }}>
                <FolderOpen size={18} weight="duotone" />
                导入模型
              </motion.button>
              <motion.button className="ghost-button" onClick={() => enqueueAutomation("delivery_package", recentProjectPath)} whileHover={reducedMotion ? undefined : { y: -2 }} whileTap={{ scale: 0.975 }}>
                <Archive size={18} weight="duotone" />
                生成交付包
              </motion.button>
            </div>
          </section>

          {activeTab === "settings" ? (
            <section className="tab-surface">
              <div className="settings-studio">
                <article className="setting-card api-card primary-setting">
                  <div className="setting-title">
                    <span>AI 接入</span>
                    <strong>{apiModeLabel(apiConfig.mode)}</strong>
                    <p>决定 CAD Agent 底层接谁。默认可用 Codex CLI，也可以一键同步 CC Switch 的 provider、模型和接口配置。</p>
                  </div>
                  <div className="api-mode-grid">
                    {(["codex_cli", "cc_switch", "openai_compatible", "manual"] as ApiIntegrationMode[]).map((mode) => (
                      <button
                        type="button"
                        className={apiConfig.mode === mode ? "active" : ""}
                        key={mode}
                        onClick={() => setApiConfig((config) => ({ ...config, mode }))}
                      >
                        {apiModeLabel(mode)}
                      </button>
                    ))}
                  </div>
                  <div className="api-form-grid">
                    <label>
                      <span>Provider</span>
                      <input value={apiConfig.providerName} onChange={(event) => setApiConfig((config) => ({ ...config, providerName: event.target.value }))} />
                    </label>
                    <label>
                      <span>Model</span>
                      <input value={apiConfig.model} onChange={(event) => setApiConfig((config) => ({ ...config, model: event.target.value }))} />
                    </label>
                    <label className="wide">
                      <span>Base URL / 执行入口</span>
                      <input value={apiConfig.endpoint} onChange={(event) => setApiConfig((config) => ({ ...config, endpoint: event.target.value }))} />
                    </label>
                  </div>
                  <div className="api-sync-row">
                    <button type="button" onClick={() => void syncCcSwitchConfig()}>
                      同步 CC Switch
                    </button>
                    <span>{apiSyncMessage}</span>
                  </div>
                  <div className="api-status-strip">
                    <span>密钥状态: {keyStatusLabel(apiConfig.keyStatus)}</span>
                    <span>配置来源: {apiConfig.sourcePath || "CAD Studio 本地设置"}</span>
                    <span>同步时间: {formatTimeLabel(apiConfig.lastSyncAt)}</span>
                  </div>
                  {ccSwitchSync?.codexProviders?.length ? (
                    <div className="provider-list">
                      {ccSwitchSync.codexProviders.slice(0, 4).map((provider) => (
                        <div className={provider.active ? "provider-row active" : "provider-row"} key={provider.id || provider.name}>
                          <strong>{provider.name || provider.id}</strong>
                          <span>{provider.model || "模型跟随 CC Switch"}</span>
                          <small>{provider.hasApiKey ? `Key ${provider.redactedApiKey || "已配置"}` : "未检测到 Key"}</small>
                        </div>
                      ))}
                    </div>
                  ) : null}
                </article>

                <article className="setting-card status-setting">
                  <span>本地执行</span>
                  <strong>{workerStatus.running ? `运行中 · PID ${workerStatus.pid ?? "-"}` : "未启动"}</strong>
                  <p>{workerStatus.health?.heartbeatAt ? `最近心跳 ${workerStatus.health.heartbeatAt}` : workerStatus.message}</p>
                  <button type="button" onClick={() => void (workerStatus.running ? stopLocalWorker() : startLocalWorker())}>
                    {workerStatus.running ? "停止本地执行器" : "启动本地执行器"}
                  </button>
                </article>
                <article className="setting-card status-setting amber">
                  <span>本地输出</span>
                  <strong>只保存到本机</strong>
                  <p>{codexConfig.outputDir}</p>
                  <button type="button" onClick={chooseOutputDir}>选择输出文件夹</button>
                </article>
                <article className="setting-card status-setting dark">
                  <span>外观</span>
                  <strong>{activeWallpaperName}</strong>
                  <p>支持本地图片、GIF 和视频壁纸。建议用低饱和背景，避免影响 CAD 信息阅读。</p>
                  <button type="button" onClick={() => setAppearanceOpen(true)}>打开外观设置</button>
                </article>
              </div>
            </section>
          ) : (
            <section className="capability-board">
              {visibleTemplates.map((template, index) => {
                const Icon = template.icon;
                return (
                  <motion.button
                    className="capability-card"
                    key={template.key}
                    onClick={() => enqueueTemplateTask(template)}
                    initial={reducedMotion ? false : { y: 12, opacity: 0 }}
                    animate={{ y: 0, opacity: 1 }}
                    transition={{ duration: 0.35, delay: index * 0.04 }}
                    whileHover={reducedMotion ? undefined : { y: -3 }}
                    whileTap={{ scale: 0.985 }}
                  >
                    <Icon size={22} weight="duotone" />
                    <span>{codexTargets[template.target]}</span>
                    <strong>{template.title}</strong>
                    <p>{template.detail}</p>
                  </motion.button>
                );
              })}
            </section>
          )}

          {activeTab !== "settings" ? (
            <>
          <section className="content-grid workbench-grid">
            <motion.article className="preview-card" layout>
              <div className="panel-heading">
                <div>
                  <p className="eyebrow">MODEL PREVIEW</p>
                  <h2>参数化 CAD 草案</h2>
                </div>
                <span className={isRunning ? "status-pill running" : "status-pill"}>{isRunning ? "建模中" : "待执行"}</span>
              </div>
              <div className={isRunning ? "cad-stage active" : "cad-stage"}>
                <motion.div
                  className="device-body"
                  animate={
                    reducedMotion
                      ? undefined
                      : {
                          rotateX: isRunning ? [58, 62, 58] : 58,
                          rotateZ: isRunning ? [-7, -4, -7] : -7,
                          y: isRunning ? [0, -5, 0] : 0,
                        }
                  }
                  transition={{ duration: 2.2, repeat: isRunning ? Infinity : 0, ease: "easeInOut" }}
                >
                  <span className="hole h1" />
                  <span className="hole h2" />
                  <span className="slot s1" />
                  <span className="slot s2" />
                  <span className="vent v1" />
                  <span className="vent v2" />
                  <span className="vent v3" />
                </motion.div>
                <div className="dimension-line horizontal">120.00 mm</div>
                <div className="dimension-line vertical">80.00 mm</div>
              </div>
            </motion.article>

            <aside className="inspector-panel">
              <div className="inspector-head">
                <div>
                  <p className="eyebrow">INSPECTOR</p>
                  <h2>参数与检查</h2>
                </div>
                <SlidersHorizontal size={22} weight="duotone" />
              </div>

              <section className="compact-card embedded">
                <div className="panel-heading compact">
                  <div>
                    <p className="eyebrow">HOLES</p>
                    <h2>开孔列表</h2>
                  </div>
                  <Ruler size={21} weight="duotone" />
                </div>
                <div className="hole-list">
                  {features.map((feature, index) => (
                    <motion.button
                      className={focusFeature === index ? "hole-row active" : "hole-row"}
                      key={feature.name}
                      onClick={() => setFocusFeature(index)}
                      whileHover={reducedMotion ? undefined : { x: 3 }}
                      whileTap={{ scale: 0.985 }}
                    >
                      <span>{feature.name}</span>
                      <strong>{feature.spec}</strong>
                      <small>{feature.pos}</small>
                      <em>{feature.status}</em>
                    </motion.button>
                  ))}
                </div>
              </section>

              <section className="compact-card embedded">
                <div className="panel-heading compact">
                  <div>
                    <p className="eyebrow">P0 GATE</p>
                    <h2>复核门禁</h2>
                  </div>
                  <ShieldCheck size={21} weight="duotone" />
                </div>
                <div className="review-list">
                  {reviewItems.map((item, index) => (
                    <motion.button
                      className={item.state === "通过" ? "review-row passed" : "review-row attention"}
                      key={item.label}
                      initial={reducedMotion ? false : { x: 12, opacity: 0 }}
                      animate={{ x: 0, opacity: 1 }}
                      transition={{ duration: 0.35, delay: index * 0.05 }}
                      whileHover={reducedMotion ? undefined : { x: 3 }}
                      whileTap={{ scale: 0.985 }}
                    >
                      <span>{item.label}</span>
                      <strong>{item.state}</strong>
                      <small>{item.note}</small>
                    </motion.button>
                  ))}
                </div>
              </section>
            </aside>
          </section>

          <section className="codex-bridge">
            <div className="bridge-copy">
              <p className="eyebrow">CODEX BRIDGE</p>
              <h2>创建 CAD 任务</h2>
              <p>按步骤填写目标、保存位置和执行偏好。软件会把它转换成本机 CAD Agent 任务，输出文件只保存到本地。</p>
            </div>

            <div className="bridge-controls">
              <section className="workflow-card">
                <div className="workflow-card-head">
                  <span>01</span>
                  <div>
                    <strong>任务内容</strong>
                    <small>描述你要得到的模型或图纸</small>
                  </div>
                </div>
                <label className="bridge-field wide">
                  <span>需求描述</span>
                  <textarea value={codexConfig.objective} onChange={(event) => updateCodexConfig({ objective: event.target.value })} />
                </label>
                <div className="bridge-field">
                  <span>目标模块</span>
                  <div className="segmented-control">
                    {(Object.keys(codexTargets) as Array<CodexConfig["target"]>).map((target) => (
                      <button
                        type="button"
                        className={codexConfig.target === target ? "active" : ""}
                        key={target}
                        onClick={() => updateCodexConfig({ target })}
                      >
                        {codexTargets[target]}
                      </button>
                    ))}
                  </div>
                </div>
              </section>

              <section className="workflow-card">
                <div className="workflow-card-head">
                  <span>02</span>
                  <div>
                    <strong>保存到本地</strong>
                    <small>选择输出物和目标文件夹</small>
                  </div>
                </div>
                <div className="bridge-field">
                  <span>输出物</span>
                  <div className="segmented-control output-control">
                    {(Object.keys(codexOutputs) as Array<CodexConfig["expectedOutput"]>).map((output) => (
                      <button
                        type="button"
                        className={codexConfig.expectedOutput === output ? "active" : ""}
                        key={output}
                        onClick={() => updateCodexConfig({ expectedOutput: output })}
                      >
                        {codexOutputs[output]}
                      </button>
                    ))}
                  </div>
                </div>
                <label className="bridge-field wide">
                  <span>输出目录</span>
                  <div className="output-path-row">
                    <input value={codexConfig.outputDir} onChange={(event) => updateCodexConfig({ outputDir: event.target.value })} />
                    <button type="button" onClick={chooseOutputDir}>选择</button>
                  </div>
                </label>
              </section>

              <section className="workflow-card">
                <div className="workflow-card-head">
                  <span>03</span>
                  <div>
                    <strong>执行设置</strong>
                    <small>默认自动选择，必要时再手动指定</small>
                  </div>
                </div>
                <div className="bridge-field wide">
                  <span>目标软件</span>
                  <div className="segmented-control software-control">
                    {(Object.keys(cadApplicationLabels) as Array<CodexConfig["cadApplication"]>).map((application) => (
                      <button
                        type="button"
                        className={codexConfig.cadApplication === application ? "active" : ""}
                        key={application}
                        onClick={() => updateCodexConfig({ cadApplication: application })}
                      >
                        {cadApplicationLabels[application]}
                      </button>
                    ))}
                  </div>
                </div>
                <div className="execution-grid">
                  <div className="bridge-field">
                    <span>制造方式</span>
                    <div className="segmented-control">
                      {(Object.keys(processLabels) as Array<CodexConfig["process"]>).map((process) => (
                        <button
                          type="button"
                          className={codexConfig.process === process ? "active" : ""}
                          key={process}
                          onClick={() => updateCodexConfig({ process })}
                        >
                          {processLabels[process]}
                        </button>
                      ))}
                    </div>
                  </div>

                  <div className="bridge-field">
                    <span>材料</span>
                    <div className="segmented-control">
                      {(Object.keys(materialLabels) as Array<CodexConfig["material"]>).map((material) => (
                        <button
                          type="button"
                          className={codexConfig.material === material ? "active" : ""}
                          key={material}
                          onClick={() => updateCodexConfig({ material })}
                        >
                          {materialLabels[material]}
                        </button>
                      ))}
                    </div>
                  </div>
                </div>
                <div className="bridge-field compact-inputs">
                  <span>参考尺寸</span>
                  <div className="number-grid">
                    {[
                      ["length", "长"],
                      ["width", "宽"],
                      ["height", "高"],
                      ["wallThickness", "壁厚"],
                    ].map(([key, label]) => (
                      <label key={key}>
                        <em>{label}</em>
                        <input
                          type="number"
                          min="0"
                          step="0.1"
                          value={codexConfig[key as "length" | "width" | "height" | "wallThickness"]}
                          onChange={(event) => updateCodexConfig({ [key]: Number(event.target.value) } as Partial<CodexConfig>)}
                        />
                      </label>
                    ))}
                  </div>
                </div>

                <div className="bridge-toggles">
                  <button type="button" className={codexConfig.realCutouts ? "toggle-pill active" : "toggle-pill"} onClick={() => updateCodexConfig({ realCutouts: !codexConfig.realCutouts })}>
                    真实开孔
                  </button>
                  <button type="button" className={codexConfig.strictGbDrawing ? "toggle-pill active" : "toggle-pill"} onClick={() => updateCodexConfig({ strictGbDrawing: !codexConfig.strictGbDrawing })}>
                    严格图纸规范
                  </button>
                  <button type="button" className={codexConfig.localCadAutomation ? "toggle-pill active" : "toggle-pill"} onClick={() => updateCodexConfig({ localCadAutomation: !codexConfig.localCadAutomation })}>
                    本机 CAD 自动化
                  </button>
                </div>
              </section>
            </div>

            <div className="bridge-runtime">
              <div className="runtime-line">
                <span>Executor</span>
                <strong>Codex CLI</strong>
              </div>
              <div className="runtime-line">
                <span>目标软件</span>
                <strong>{cadApplicationLabels[codexConfig.cadApplication]}</strong>
              </div>
              <div className="runtime-line">
                <span>Skill</span>
                <strong>{codexConfig.cadApplication === "autocad" ? "autocad-automation" : codexConfig.cadApplication === "both" ? "SW + AutoCAD skills" : "solidworks-automation"}</strong>
              </div>
              <div className="runtime-line">
                <span>权限</span>
                <strong>{codexConfig.localCadAutomation ? "需审批后控制本机 CAD" : "仅生成计划/脚本"}</strong>
              </div>
              <div className="runtime-line">
                <span>制造输入</span>
                <strong>{`${processLabels[codexConfig.process]} · ${materialLabels[codexConfig.material]} · ${codexConfig.length}x${codexConfig.width}x${codexConfig.height}`}</strong>
              </div>
              <div className="prompt-preview">
                <span>执行计划预览</span>
                <p>{codexPrompt}</p>
              </div>
              <motion.button className="primary-button bridge-run shine" onClick={enqueueCodexTask} whileHover={reducedMotion ? undefined : { y: -2 }} whileTap={{ scale: 0.975 }}>
                <Lightning size={18} weight="duotone" />
                交给 Codex 执行
              </motion.button>
            </div>
          </section>

          <footer className="status-strip">
            <div className="metric-row">
              {[
                ["运行模式", "本地桌面", Lightning],
                ["图纸门禁", "GB/T P0", ShieldCheck],
                ["制造场景", processLabels[codexConfig.process], Aperture],
                ["任务队列", queueLoaded ? queueSummary : "加载中", Graph],
              ].map(([label, value, Icon]) => (
                <motion.div className="metric-card" key={label as string} whileHover={reducedMotion ? undefined : { y: -2 }}>
                  <Icon size={19} weight="duotone" />
                  <span>{label as string}</span>
                  <strong>{value as string}</strong>
                </motion.div>
              ))}
            </div>

            <section className="agent-console">
              <div className="agent-head">
                <div>
                  <p className="eyebrow">AI EXECUTION CHAT</p>
                  <h2>AI 执行对话</h2>
                </div>
                <span>{activeAgentJob ? `${jobStatusLabel(activeAgentJob.status)} · ${activeAgentJob.progress}%` : "等待指令"}</span>
              </div>

              <div className="agent-body">
                <div className="chat-thread" aria-label="AI 执行对话记录">
                  {agentMessages.map((message) => (
                    <motion.div
                      className={`chat-bubble ${message.role}`}
                      key={message.id}
                      initial={reducedMotion ? false : { y: 8, opacity: 0 }}
                      animate={{ y: 0, opacity: 1 }}
                    >
                      <span>{message.role === "user" ? "你" : message.role === "system" ? "系统" : "CAD Agent"}</span>
                      <p>{message.content}</p>
                      <small>{formatTimeLabel(message.at)}</small>
                    </motion.div>
                  ))}
                </div>

                <div className="agent-live-panel">
                  <div className="live-head">
                    <ChatCircleText size={18} weight="duotone" />
                    <strong>{activeAgentJob?.title ?? "等待第一条任务"}</strong>
                    <span>{activeAgentJob ? jobStatusLabel(activeAgentJob.status) : "待命"}</span>
                  </div>
                  <div className="live-progress">
                    <i style={{ width: `${activeAgentJob?.progress ?? 0}%` }} />
                  </div>
                  <div className="live-summary">
                    <p>{activeAgentJob ? compactJobMessage(activeAgentJob, activeAgentEvents) : "输入你的要求后，这里会显示 AI 的公开执行过程、工具结果和输出文件。"}</p>
                  </div>
                  {activeAgentJob?.status === "approval_required" ? (
                    <button className="approval-button" type="button" onClick={() => void approveJob(activeAgentJob.id)}>
                      批准本机执行
                    </button>
                  ) : null}
                  <div className="live-timeline">
                    {activeAgentEvents.length === 0 ? (
                      <div className="timeline-empty">任务开始后会显示：接单、审批、AI 启动、复核、输出路径和错误。</div>
                    ) : (
                      activeAgentEvents.slice(-6).map((event, index) => (
                        <div className="timeline-item" key={`${event.at}-${event.type}-${index}`}>
                          <span>{eventTypeLabel(event.type)}</span>
                          <p>{event.message || "状态已更新"}</p>
                          <small>{formatTimeLabel(event.at)}</small>
                        </div>
                      ))
                    )}
                  </div>
                  {(activeAgentLogs.stdout || activeAgentLogs.stderr) && (
                    <div className="agent-log-preview">
                      <strong>AI 输出</strong>
                      {activeAgentLogs.stdout ? <pre>{activeAgentLogs.stdout}</pre> : null}
                      {activeAgentLogs.stderr ? <pre className="error-log">{activeAgentLogs.stderr}</pre> : null}
                    </div>
                  )}
                </div>
              </div>

              <div className="agent-input-row">
                <textarea
                  value={agentInput}
                  onChange={(event) => setAgentInput(event.target.value)}
                  onKeyDown={(event) => {
                    if ((event.ctrlKey || event.metaKey) && event.key === "Enter") submitAgentMessage();
                  }}
                  placeholder="例如：把这个外壳的 USB 口改大 1mm，并重新导出 STL 和国标 PDF 图纸"
                />
                <button type="button" onClick={submitAgentMessage}>
                  <PaperPlaneTilt size={18} weight="fill" />
                  发送执行
                </button>
              </div>
            </section>

            <section className="queue-panel">
              <div className="queue-head">
                <div>
                  <p className="eyebrow">AUTOMATION QUEUE</p>
                  <h2>本地任务监视器</h2>
                </div>
                <div className="queue-actions">
                  <span className={workerStatus.running ? "worker-pill running" : "worker-pill"}>
                    {workerLabel}
                  </span>
                  <button type="button" onClick={() => void (workerStatus.running ? stopLocalWorker() : startLocalWorker())}>
                    {workerStatus.running ? "停止" : "启动"}
                  </button>
                  <span>{queueLoaded ? queueSummary : "加载中"}</span>
                </div>
              </div>
              <div className="queue-list">
                {jobs.length === 0 ? (
                  <div className="queue-empty">
                    <Sparkle size={19} weight="duotone" />
                    <span>点击模板、发送 AI 对话或导入模型后，任务会出现在这里。</span>
                  </div>
                ) : (
                  jobs.slice(0, 4).map((job) => {
                    const expanded = expandedJobId === job.id;
                    const events = jobEvents[job.id] ?? [];
                    const logs = jobLogTails[job.id] ?? {};
                    const workerLogs = (job.workerLog ?? []).slice(-5);
                    return (
                      <motion.article className={`queue-job ${job.status} ${expanded ? "expanded" : ""}`} key={job.id} layout>
                        <div className="job-main">
                          <div>
                            <strong>{job.title}</strong>
                            <small>{compactJobMessage(job, events)}</small>
                          </div>
                          <span>{jobStatusLabel(job.status)}</span>
                        </div>
                        <div className="job-progress" aria-label={`${job.title} 进度 ${job.progress}%`}>
                          <i style={{ width: `${job.progress}%` }} />
                        </div>
                        <div className="job-controls">
                          <button type="button" onClick={() => setExpandedJobId(expanded ? null : job.id)}>
                            <CaretDown size={15} weight="bold" />
                            {expanded ? "收起过程" : "查看过程"}
                          </button>
                          {job.uiConfig?.agentChat === true ? (
                            <button type="button" onClick={() => setActiveAgentJobId(job.id)}>
                              对话跟随
                            </button>
                          ) : null}
                          {job.status === "approval_required" ? (
                            <button type="button" onClick={() => void approveJob(job.id)}>
                              批准
                            </button>
                          ) : null}
                          {job.status === "queued" || job.status === "running" ? (
                            <button type="button" onClick={() => cancelJob(job.id)}>
                              取消
                            </button>
                          ) : null}
                        </div>
                        <AnimatePresence>
                          {expanded ? (
                            <motion.div
                              className="job-process"
                              initial={reducedMotion ? false : { height: 0, opacity: 0 }}
                              animate={{ height: "auto", opacity: 1 }}
                              exit={reducedMotion ? undefined : { height: 0, opacity: 0 }}
                            >
                              <div className="process-grid">
                                <div>
                                  <span>当前任务</span>
                                  <strong>{job.detail}</strong>
                                </div>
                                <div>
                                  <span>执行软件</span>
                                  <strong>{job.targetSoftware || "AI 自动判断"}</strong>
                                </div>
                                <div>
                                  <span>最近心跳</span>
                                  <strong>{formatTimeLabel(job.heartbeatAt || workerStatus.health?.heartbeatAt)}</strong>
                                </div>
                                <div>
                                  <span>Worker</span>
                                  <strong>{job.workerPid ? `PID ${job.workerPid}` : workerLabel}</strong>
                                </div>
                              </div>

                              {job.approvalReasons?.length ? (
                                <div className="process-note warning">
                                  <strong>需要审批</strong>
                                  <p>{job.approvalReasons.join("；")}</p>
                                </div>
                              ) : null}
                              {job.error ? (
                                <div className="process-note error">
                                  <strong>错误</strong>
                                  <p>{job.error}</p>
                                </div>
                              ) : null}
                              {job.result?.outputPath || job.artifactLedgerPath || job.reviewGatePath ? (
                                <div className="process-paths">
                                  {job.result?.outputPath ? <span>输出: {job.result.outputPath}</span> : null}
                                  {job.artifactLedgerPath ? <span>交付账本: {job.artifactLedgerPath}</span> : null}
                                  {job.reviewGatePath ? <span>复核记录: {job.reviewGatePath}</span> : null}
                                </div>
                              ) : null}

                              <div className="process-columns">
                                <div className="process-timeline">
                                  <strong>执行过程</strong>
                                  {(events.length ? events : [{ message: job.lastMessage || "等待 worker 接单", at: job.updatedAt, type: job.status }]).slice(-8).map((event, index) => (
                                    <div className="timeline-item" key={`${event.at}-${event.type}-${index}`}>
                                      <span>{eventTypeLabel(event.type)}</span>
                                      <p>{event.message || "状态已更新"}</p>
                                      <small>{formatTimeLabel(event.at)}</small>
                                    </div>
                                  ))}
                                </div>
                                <div className="process-timeline">
                                  <strong>Worker 日志</strong>
                                  {(workerLogs.length ? workerLogs : [{ message: "暂无 worker 日志，任务启动后会自动刷新。", at: job.updatedAt }]).map((entry, index) => (
                                    <div className="timeline-item" key={`${workerLogTime(entry)}-${index}`}>
                                      <span>{formatTimeLabel(workerLogTime(entry))}</span>
                                      <p>{workerLogMessage(entry)}</p>
                                    </div>
                                  ))}
                                </div>
                              </div>
                              {(logs.stdout || logs.stderr) && (
                                <div className="agent-log-preview full">
                                  <strong>Codex 输出尾部</strong>
                                  {logs.stdout ? <pre>{logs.stdout}</pre> : null}
                                  {logs.stderr ? <pre className="error-log">{logs.stderr}</pre> : null}
                                </div>
                              )}
                            </motion.div>
                          ) : null}
                        </AnimatePresence>
                      </motion.article>
                    );
                  })
                )}
              </div>
            </section>

            <div className="stage-row">
              {visualStages.map((stage, index) => (
                <motion.div
                  className={`stage-card ${stage.state}`}
                  key={stage.key}
                  initial={reducedMotion ? false : { y: 8, opacity: 0 }}
                  animate={{ y: 0, opacity: 1 }}
                  transition={{ duration: 0.3, delay: index * 0.04 }}
                >
                  <span className="stage-index">{String(index + 1).padStart(2, "0")}</span>
                  <strong>{stage.label}</strong>
                  <small>{stateLabel(stage.state)}</small>
                  <p>{stage.detail}</p>
                </motion.div>
              ))}
            </div>
          </footer>
            </>
          ) : null}
        </section>
      </motion.section>

      <div className="software-roadmap" aria-label="桌面部署计划">
        <WarningCircle size={16} weight="duotone" />
        <span>已接入 Tauri 本地队列：桌面端创建任务，Python worker 可离线接单，后续替换为真实 CAD 执行器。</span>
      </div>
    </main>
  );
}

export default App;
