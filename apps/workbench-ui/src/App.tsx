import {
  Aperture,
  Archive,
  ArrowClockwise,
  CaretDown,
  ChatCircleText,
  CubeFocus,
  Export,
  FilePlus,
  FolderOpen,
  GearSix,
  Graph,
  Question,
  ImageSquare,
  Layout,
  Lightning,
  Minus,
  PaperPlaneTilt,
  Play,
  Ruler,
  ShieldCheck,
  Sparkle,
  Square,
  UploadSimple,
  X,
} from "@phosphor-icons/react";
import { convertFileSrc, invoke } from "@tauri-apps/api/core";
import { getCurrentWindow } from "@tauri-apps/api/window";
import { open as openDialog } from "@tauri-apps/plugin-dialog";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { type CSSProperties, type ChangeEvent, type DragEvent, type PointerEvent as ReactPointerEvent, useEffect, useMemo, useRef, useState } from "react";

const DEFAULT_WALLPAPER_URL = new URL("./assets/default-blossom-wallpaper.mp4", import.meta.url).href;
const DEFAULT_WALLPAPER_POSTER_URL = new URL("./assets/default-blossom-poster.webp", import.meta.url).href;
const FUJI_WALLPAPER_URL = new URL("./assets/wallpaper-fuji.webp", import.meta.url).href;
const ANIME_SKY_WALLPAPER_URL = new URL("./assets/wallpaper-anime-sky.webp", import.meta.url).href;
const TOKYO_NEON_WALLPAPER_URL = new URL("./assets/wallpaper-tokyo-neon.webp", import.meta.url).href;

type PresetWallpaperId = "blossom" | "fuji" | "anime-sky" | "tokyo-neon" | "blueprint" | "studio" | "mist";
type WallpaperId = PresetWallpaperId | "custom";
type WallpaperMotionMode = "still" | "breathe" | "cinematic" | "follow";
type WallpaperFile = { url: string; name: string; kind: "image" | "video"; sourcePath?: string };
type RecentWallpaper = { path: string; name: string; kind: "image" | "video" };
type AppSettings = {
  activeWallpaper: WallpaperId;
  customWallpaperPath?: string;
  wallpaperBrightness: number;
  wallpaperBlur: number;
  wallpaperVignette: number;
  workspaceOpacity: number;
  wallpaperMotionMode: WallpaperMotionMode;
  wallpaperMotionStrength: number;
  defaultWallpaperVersion?: number;
  panelOpacityVersion?: number;
  recentWallpapers: RecentWallpaper[];
  recentProjectPath?: string;
  apiConfig?: ApiIntegrationConfig;
  knowledgeBase?: KnowledgeBaseConfig;
};
type ApiIntegrationMode = "codex_cli" | "cc_switch";
type AgentProviderId = "codex" | "claude" | "gemini" | "opencode";
type ApiProviderSummary = {
  id?: string;
  name?: string;
  active?: boolean;
  endpoint?: string;
  model?: string;
  hasApiKey?: boolean;
  redactedApiKey?: string;
  appType?: AgentProviderId;
  models?: string[];
  credentialStatus?: "oauth" | "managed" | "route";
  authLabel?: string;
};
type CcSwitchSync = {
  source?: string;
  rootPath?: string;
  configPath?: string;
  databasePath?: string;
  settingsPath?: string;
  syncedAt?: string;
  codexCurrent?: string;
  claudeCurrent?: string;
  codexProviders?: ApiProviderSummary[];
  claudeProviders?: ApiProviderSummary[];
  geminiProviders?: ApiProviderSummary[];
  opencodeProviders?: ApiProviderSummary[];
  providersByAgent?: Partial<Record<AgentProviderId, ApiProviderSummary[]>>;
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
  agentProvider: AgentProviderId;
  providerName: string;
  endpoint: string;
  model: string;
  keyStatus: "missing" | "configured" | "synced";
  lastSyncAt?: string;
  sourcePath?: string;
};
type KnowledgeBaseConfig = {
  cloudEnabled: boolean;
  localRoots: string[];
  endpoint: string;
  namespace: string;
  tokenEnv: string;
  topK: number;
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
type AutomationJobKind = "create_shell" | "import_model" | "delivery_package" | "codex_task" | "agent_task";
type AutomationJobStatus = "queued" | "running" | "passed" | "review_required" | "failed" | "cancelled" | "approval_required";
type WorkerLogEntry = {
  status?: string;
  message?: string;
  at?: string;
  worker?: string;
  runnerId?: string;
  data?: unknown;
};
type ArtifactRecord = {
  kind?: string;
  path?: string;
  exists?: boolean;
  isDirectory?: boolean;
  sizeBytes?: number;
  sha256?: string;
  producedThisRun?: boolean;
};
type ReviewCheck = {
  id?: string;
  severity?: string;
  status?: "pass" | "warning" | "fail" | string;
  message?: string;
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
  executor?: "mock" | "codex" | "agent";
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
    outputs?: Record<string, string> | Array<string | ArtifactRecord>;
    artifacts?: Array<string | ArtifactRecord>;
    verification?: Array<Record<string, unknown>>;
    features?: Array<Record<string, unknown>>;
    checks?: ReviewCheck[];
    stdoutTail?: string;
    stderrTail?: string;
    engineeringPlanPath?: string;
    engineeringPlan?: {
      phases?: Array<{ id?: string; name?: string; status?: string; human_gate?: boolean }>;
    };
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
  artifacts?: ArtifactRecord[];
  approvalReasons?: string[];
  approvedAt?: string;
  approvedBy?: string;
  approvedPolicyReasons?: string[];
  reviewedAt?: string;
  reviewedBy?: string;
  reviewDecision?: "approved" | "rejected";
  reviewNote?: string;
  artifactLedgerPath?: string;
  reviewGatePath?: string;
  reviewGate?: {
    status?: "pass" | "warning" | "fail";
    checks?: ReviewCheck[];
    manualReview?: {
      status?: "approved" | "rejected";
      reviewedBy?: string;
      reviewedAt?: string;
      note?: string;
    };
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
type ManualReviewDraft = {
  note: string;
  checks: string[];
};
type WorkerStatus = {
  running: boolean;
  pid?: number | null;
  recoveredJobs?: number;
  message: string;
  health?: {
    status?: string;
    heartbeatAt?: string;
    queue?: Record<string, number>;
  } | null;
};
type RuntimeHealth = {
  skillRoot: string;
  solidworksSkillPath: string;
  autocadSkillPath: string;
  defaultOutputDir?: string;
  python?: { ok?: boolean; entry?: string; message?: string };
  codex?: { version?: { ok?: boolean; message?: string }; login?: { ok?: boolean; message?: string }; entry?: string };
  agentProviders?: Array<{
    id: AgentProviderId;
    name: string;
    installed?: boolean;
    ready?: boolean;
    verified?: boolean;
    status?: "not_installed" | "auth_failed" | "verified" | "verification_required";
    version?: { ok?: boolean; message?: string };
    auth?: { ok?: boolean | null; message?: string };
    entry?: string;
  }>;
  solidworks?: { ok?: boolean; message?: string };
  autocad?: { ok?: boolean; path?: string };
};

const wallpapers: Array<{ id: PresetWallpaperId; name: string; hint: string; assetUrl?: string; credit?: string }> = [
  { id: "blossom", name: "樱影", hint: "内置动态壁纸" },
  { id: "fuji", name: "富士暮色", hint: "CC0 · Alpsdake", assetUrl: FUJI_WALLPAPER_URL, credit: "Alpsdake · CC0" },
  { id: "anime-sky", name: "青空原野", hint: "CC BY-SA · mendhak", assetUrl: ANIME_SKY_WALLPAPER_URL, credit: "mendhak · CC BY-SA 4.0" },
  { id: "tokyo-neon", name: "东京霓虹", hint: "CC BY-SA · Basile Morin", assetUrl: TOKYO_NEON_WALLPAPER_URL, credit: "Basile Morin · CC BY-SA 4.0" },
  { id: "blueprint", name: "Blueprint", hint: "淡蓝工程网格" },
  { id: "studio", name: "Studio", hint: "白色摄影棚光" },
  { id: "mist", name: "Mist", hint: "晨雾玻璃质感" },
];

const navItems = [
  ["project", "01 总览", Layout],
  ["model", "02 建模", CubeFocus],
  ["holes", "03 特征", Ruler],
  ["drawing", "04 图纸", FilePlus],
  ["check", "05 复核", ShieldCheck],
  ["export", "06 交付", Export],
  ["settings", "设置", GearSix],
  ["help", "帮助", Question],
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
    subtitle: "管理本地 Agent、CC Switch 模型路由、审批策略、壁纸外观、默认规范库和输出目录。",
  },
  help: {
    title: "使用帮助",
    subtitle: "从环境准备、AI 选择到建模、复核和交付的完整操作路径。",
  },
};

const SETTINGS_KEY = "cad-studio.settings.v1";
const QUEUE_KEY = "cad-studio.queue.v1";
const CHAT_KEY = "cad-studio.agent-chat.v1";
const APP_VERSION = "0.1.1";
const manualReviewOptions = [
  ["native-open", "已用目标 CAD 软件原生打开并确认无报错"],
  ["dimensions", "已核对关键尺寸、公差、基准和定位尺寸"],
  ["features", "已核对孔槽、螺纹、装配和真实几何特征"],
  ["artifacts", "已核对本轮交付文件、格式、路径和版本"],
] as const;
const defaultApiConfig: ApiIntegrationConfig = {
  mode: "codex_cli",
  agentProvider: "codex",
  providerName: "Codex CLI",
  endpoint: "本机 Codex 登录态",
  model: "由 Codex 配置决定",
  keyStatus: "configured",
};
const agentProviderCatalog: Record<AgentProviderId, { name: string; protocol: string; model: string }> = {
  codex: { name: "Codex", protocol: "codex-exec-v1", model: "跟随 Codex 配置" },
  claude: { name: "Claude Code", protocol: "claude-print-v1", model: "跟随 Claude 配置" },
  gemini: { name: "Gemini CLI", protocol: "gemini-headless-v1", model: "跟随 Gemini 配置" },
  opencode: { name: "OpenCode", protocol: "opencode-jsonl-v1", model: "跟随 OpenCode 配置" },
};

function ccSwitchProvidersForAgent(sync: CcSwitchSync | null, agentProvider: AgentProviderId) {
  if (!sync) return [];
  const grouped = sync.providersByAgent?.[agentProvider];
  if (grouped) return grouped;
  if (agentProvider === "codex") return sync.codexProviders || [];
  if (agentProvider === "claude") return sync.claudeProviders || [];
  if (agentProvider === "gemini") return sync.geminiProviders || [];
  return sync.opencodeProviders || [];
}

function activeCcSwitchProvider(sync: CcSwitchSync | null, agentProvider: AgentProviderId) {
  const providers = ccSwitchProvidersForAgent(sync, agentProvider);
  return providers.find((provider) => provider.active) || providers[0];
}
const wallpaperShots = [
  { x: 0, y: 0, scale: 1.04 },
  { x: -2.5, y: -1.5, scale: 1.13 },
  { x: 3, y: 1, scale: 1.18 },
  { x: -1, y: 2.5, scale: 1.09 },
];
const wallpaperMotionLabels: Record<WallpaperMotionMode, string> = {
  still: "静止",
  breathe: "呼吸",
  cinematic: "电影镜头",
  follow: "跟随指针",
};
const defaultKnowledgeBase: KnowledgeBaseConfig = {
  cloudEnabled: false,
  localRoots: [],
  endpoint: "",
  namespace: "mechanical-engineering",
  tokenEnv: "CAD_STUDIO_RAG_TOKEN",
  topK: 6,
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
];

const codexOutputs: Record<CodexConfig["expectedOutput"], string> = {
  auto: "AI 自动选择输出",
  cad_files: "SLDPRT / STEP / STL",
  drawing_package: "DWG / DXF / PDF 图纸包",
  research_report: "调研报告 / 执行建议",
};

function resolvedExpectedOutput(config: CodexConfig) {
  if (config.expectedOutput === "cad_files" && config.target === "assembly") return "SLDASM / STEP / STL";
  return codexOutputs[config.expectedOutput];
}

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

const deliveryFormats = ["STEP", "STL", "SLDPRT", "SLDASM", "DWG", "DXF", "PDF", "PNG", "复核报告"];

function jobStatusLabel(status: AutomationJobStatus) {
  if (status === "running") return "执行中";
  if (status === "passed") return "完成";
  if (status === "review_required") return "待复核";
  if (status === "failed") return "失败";
  if (status === "cancelled") return "已取消";
  if (status === "approval_required") return "待审批";
  return "排队";
}

function jobKindDetail(kind: AutomationJobKind) {
  if (kind === "create_shell") return { title: "新建 CAD 任务", detail: "生成零件、装配、外壳、孔槽和基础检查任务" };
  if (kind === "import_model") return { title: "导入已有文件", detail: "读取 CAD 模型、工程图或图片草图作为参考" };
  if (kind === "codex_task" || kind === "agent_task") return { title: "Agent 执行", detail: "把图形化配置转换为当前 AI 的非交互执行任务" };
  return { title: "生成交付包", detail: "整理 STEP、STL、PDF、DWG 和交付清单" };
}

function conciseTaskTitle(value: string | undefined, fallback: string) {
  const normalized = value?.replace(/\s+/g, " ").trim();
  if (!normalized) return fallback;
  return normalized.length > 24 ? `${normalized.slice(0, 24)}...` : normalized;
}

function jobDisplayTitle(job: AutomationJob) {
  const title = job.title.trim();
  const internalExecutionTitle = /^(Codex|Claude Code|Gemini CLI|OpenCode|Agent|AI 对话)\s*执行$/i.test(title);
  if (!internalExecutionTitle) return title;
  return conciseTaskTitle(job.objective, job.target ? `${job.target}任务` : "AI CAD 任务");
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
    const migratedWallpaper =
      parsed.defaultWallpaperVersion === 1
        ? parsed.activeWallpaper ?? "blossom"
        : parsed.customWallpaperPath
          ? parsed.activeWallpaper ?? "custom"
          : "blossom";
    return {
      activeWallpaper: parsed.customWallpaperPath ? migratedWallpaper : migratedWallpaper === "custom" ? "blossom" : migratedWallpaper,
      customWallpaperPath: parsed.customWallpaperPath,
      wallpaperBrightness: clampNumber(parsed.wallpaperBrightness, 94, 72, 112),
      wallpaperBlur: clampNumber(parsed.wallpaperBlur, 3, 0, 14),
      wallpaperVignette: clampNumber(parsed.wallpaperVignette, 18, 0, 42),
      workspaceOpacity: parsed.panelOpacityVersion === 1 ? clampNumber(parsed.workspaceOpacity, 36, 18, 92) : 36,
      wallpaperMotionMode: parsed.wallpaperMotionMode ?? "cinematic",
      wallpaperMotionStrength: clampNumber(parsed.wallpaperMotionStrength, 55, 0, 100),
      defaultWallpaperVersion: 1,
      panelOpacityVersion: 1,
      recentWallpapers: Array.isArray(parsed.recentWallpapers) ? parsed.recentWallpapers.slice(0, 6) : [],
      recentProjectPath: parsed.recentProjectPath,
      apiConfig: parsed.apiConfig
        ? {
            mode: parsed.apiConfig.mode ?? defaultApiConfig.mode,
            agentProvider: parsed.apiConfig.agentProvider ?? defaultApiConfig.agentProvider,
            providerName: parsed.apiConfig.providerName ?? defaultApiConfig.providerName,
            endpoint: parsed.apiConfig.endpoint ?? defaultApiConfig.endpoint,
            model: parsed.apiConfig.model ?? defaultApiConfig.model,
            keyStatus: parsed.apiConfig.keyStatus ?? defaultApiConfig.keyStatus,
            lastSyncAt: parsed.apiConfig.lastSyncAt,
            sourcePath: parsed.apiConfig.sourcePath,
          }
        : defaultApiConfig,
      knowledgeBase: parsed.knowledgeBase
        ? {
            cloudEnabled: parsed.knowledgeBase.cloudEnabled === true,
            localRoots: Array.isArray(parsed.knowledgeBase.localRoots) ? parsed.knowledgeBase.localRoots.filter((item): item is string => typeof item === "string").slice(0, 8) : [],
            endpoint: parsed.knowledgeBase.endpoint ?? "",
            namespace: parsed.knowledgeBase.namespace ?? defaultKnowledgeBase.namespace,
            tokenEnv: parsed.knowledgeBase.tokenEnv ?? defaultKnowledgeBase.tokenEnv,
            topK: clampNumber(parsed.knowledgeBase.topK, 6, 1, 12),
          }
        : defaultKnowledgeBase,
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
    return Array.isArray(messages)
      ? messages.filter((message) => !String(message?.content || "").startsWith("你好，我是 CAD Studio 的 AI 执行助手")).slice(-30)
      : [];
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

function readableExecutionMessage(message?: string, job?: AutomationJob) {
  if (!message) return "";
  if (message.includes("WinError 2") || message.includes("系统找不到指定的文件")) {
    if (job?.executor === "codex" || job?.kind === "codex_task") {
      return "找不到所选 Agent CLI。请到设置里检查执行核心，或确认对应 CLI 已安装并能在命令行运行。";
    }
    return "找不到要启动的本地程序。请检查 Python、SolidWorks、AutoCAD 或相关执行器是否已安装。";
  }
  return message;
}

function compactJobMessage(job: AutomationJob, events?: QueueEvent[]) {
  const message =
    (job.status === "approval_required" ? job.approvalReasons?.[0] : undefined) ||
    events?.[events.length - 1]?.message ||
    (job.reviewGate?.status ? `复核结果: ${job.reviewGate.status}` : undefined) ||
    job.lastMessage ||
    job.result?.message ||
    job.result?.outputPath ||
    job.error ||
    job.detail;
  return readableExecutionMessage(message, job);
}

function buildChatPrompt(
  config: CodexConfig,
  api: ApiIntegrationConfig,
  userText: string,
  history: AgentChatMessage[],
  projectPath?: string,
  runtime?: RuntimeHealth | null,
) {
  const recentHistory = history
    .slice(-8)
    .map((message) => `${message.role === "user" ? "用户" : message.role === "assistant" ? "AI" : "系统"}: ${message.content}`)
    .join("\n");
  return [
    buildCodexPrompt(config, projectPath, runtime),
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
  return "本机 Agent CLI";
}

function keyStatusLabel(status: ApiIntegrationConfig["keyStatus"]) {
  if (status === "synced") return "已同步";
  if (status === "configured") return "已配置";
  return "未配置";
}

function fileNameFromPath(path?: string) {
  if (!path) return "未命名文件";
  return path.split(/[\\/]/).pop() || path;
}

function artifactKindLabel(kind?: string, path?: string) {
  const normalized = (kind || fileNameFromPath(path).split(".").pop() || "artifact").toLowerCase();
  if (normalized.includes("sldprt")) return "SolidWorks 零件";
  if (normalized.includes("sldasm")) return "SolidWorks 装配";
  if (normalized.includes("step") || normalized.includes("stp")) return "STEP";
  if (normalized.includes("stl")) return "STL";
  if (normalized.includes("dwg")) return "DWG";
  if (normalized.includes("dxf")) return "DXF";
  if (normalized.includes("pdf")) return "PDF";
  if (normalized.includes("png") || normalized.includes("preview")) return "预览图";
  if (normalized.includes("codex")) return "AI 结果";
  return kind || "交付物";
}

function formatBytes(value?: number) {
  if (!value || value <= 0) return "";
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / 1024 / 1024).toFixed(1)} MB`;
}

function reviewStatusLabel(status?: string) {
  if (status === "pass") return "通过";
  if (status === "fail") return "失败";
  if (status === "warning") return "注意";
  return status || "待复核";
}

function jobReviewStatusLabel(job?: AutomationJob) {
  if (job?.reviewDecision === "approved") return "人工复核通过";
  if (job?.reviewDecision === "rejected") return "人工复核驳回";
  if (job?.reviewGate?.status) return reviewStatusLabel(job.reviewGate.status);
  return "未复核";
}

function reviewOptionsFor(job?: AutomationJob): Array<readonly [string, string]> {
  const options: Array<readonly [string, string]> = [...manualReviewOptions];
  if (/DWG|DXF|PDF|图纸/i.test(`${job?.expectedOutput ?? ""} ${job?.target ?? ""}`)) {
    options.push(["drawing", "已核对图框标题栏、视图、尺寸链、孔表和技术要求"]);
  }
  return options;
}

function artifactStatusLabel(artifact: ArtifactRecord) {
  if (artifact.exists === false) return "缺失";
  if (artifact.isDirectory) return "目录";
  if (artifact.exists) return "已生成";
  return "待确认";
}

function deliveryFormatStatus(format: string, job: AutomationJob | undefined, artifacts: ArtifactRecord[]) {
  if (format === "复核报告") {
    return job?.reviewGatePath ? "ready" : job ? "missing" : "optional";
  }
  const extensionMap: Record<string, string[]> = {
    STEP: [".step", ".stp"],
    STL: [".stl"],
    SLDPRT: [".sldprt"],
    SLDASM: [".sldasm"],
    DWG: [".dwg"],
    DXF: [".dxf"],
    PDF: [".pdf"],
    PNG: [".png"],
  };
  const extensions = extensionMap[format] ?? [];
  const ready = artifacts.some((artifact) => {
    const path = artifact.path?.toLowerCase() ?? "";
    return artifact.exists !== false && artifact.producedThisRun !== false && extensions.some((extension) => path.endsWith(extension));
  });
  if (ready) return "ready";
  const expected = (job?.expectedOutput ?? "").toUpperCase().includes(format);
  return expected ? "missing" : "optional";
}

function collectJobArtifacts(job?: AutomationJob): ArtifactRecord[] {
  if (!job) return [];
  const items: ArtifactRecord[] = [];
  const pushArtifact = (kind: string, path?: string, extra: Partial<ArtifactRecord> = {}) => {
    if (!path) return;
    items.push({ kind, path, ...extra });
  };

  for (const artifact of job.artifacts ?? []) {
    if (artifact?.path) items.push(artifact);
  }
  if (job.result?.outputPath) pushArtifact("codex_output", job.result.outputPath, { exists: true });
  const outputs = job.result?.outputs;
  if (Array.isArray(outputs)) {
    outputs.forEach((item, index) => {
      if (typeof item === "string") pushArtifact(`output_${index}`, item);
      else if (item?.path) items.push(item);
    });
  } else if (outputs && typeof outputs === "object") {
    Object.entries(outputs).forEach(([kind, path]) => pushArtifact(kind, path));
  }

  const seen = new Set<string>();
  return items.filter((item) => {
    const key = item.path || `${item.kind}-${seen.size}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

function realFeatureRows(job?: AutomationJob): Array<Record<string, unknown>> {
  const features = job?.result?.features;
  return Array.isArray(features) ? features.filter((item): item is Record<string, unknown> => typeof item === "object" && item !== null) : [];
}

function recordText(record: Record<string, unknown>, keys: string[], fallback = "") {
  for (const key of keys) {
    const value = record[key];
    if (typeof value === "string" && value.trim()) return value;
    if (typeof value === "number") return String(value);
  }
  return fallback;
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

function buildCodexPrompt(config: CodexConfig, projectPath?: string, runtime?: RuntimeHealth | null) {
  const strictRules = [
    "用户未明确指定的建模类型、工艺、材料、输出格式、尺寸细节和检查项，由 AI 根据工程目标自动选择最佳方案，并在结果中说明选择理由。",
    config.realCutouts ? "所有孔、槽、螺纹、接口和减重结构必须是真实几何特征，不能只画线或只做外观标记。" : "如果涉及孔槽，需要明确说明当前是否已真实切除。",
    config.strictGbDrawing ? "CAD 图纸必须按中国机械制图常用格式复核，尺寸链、孔表、技术要求、图框标题栏要完整。" : "图纸输出需要标明当前规范覆盖范围。",
    "结果必须保存到用户指定的本地输出目录，不向 GitHub 或外部服务发布。",
  ];

  return [
    "你是用户选择的本机 Agent Provider，请执行由 CAD Studio 图形化界面生成的任务。",
    "",
    `任务目标: ${config.objective}`,
    `目标 CAD 软件: ${cadApplicationLabels[config.cadApplication]}`,
    `软件路由策略: ${cadApplicationRoutes[config.cadApplication]}`,
    `任务类型: ${codexTargets[config.target]}`,
    `期望输出: ${resolvedExpectedOutput(config)}`,
    `项目/模型路径: ${projectPath || "未指定"}`,
    `制造方式: ${processLabels[config.process]}`,
    `材料: ${materialLabels[config.material]}`,
    `单位: ${config.unit}`,
    `参考包络尺寸: ${config.length > 0 && config.width > 0 && config.height > 0 ? `${config.length} x ${config.width} x ${config.height} ${config.unit}` : "未指定，涉及装配接口或制造前必须向用户确认"}`,
    `参考壁厚/板厚: ${config.wallThickness > 0 ? `${config.wallThickness} ${config.unit}` : "未指定，由 AI 给出建议但制造前必须确认"}`,
    `输出目录: ${config.outputDir}`,
    `Skill 路径: ${runtime?.solidworksSkillPath || "由桌面端启动时自动检测"}`,
    `AutoCAD 子技能路径: ${runtime?.autocadSkillPath || "由桌面端启动时自动检测"}`,
    "",
    "强制规则:",
    ...strictRules.map((rule) => `- ${rule}`),
    "",
    "自动决策规则:",
    "- 若某项为 AI 自动判断/选择，先根据用户目标、输入文件、制造方式、成本、强度、可加工性和交付要求做最佳选择。",
    "- 自动选择后必须在 summary 或 verification 中解释为什么这么选。",
    "- 若信息不足以可靠决策，先采用行业常用保守方案，并标记残余风险。",
    "- 不得自动猜测装配接口、关键尺寸、公差、载荷和安全相关材料；缺失时必须询问，或明确标为概念方案不可制造。",
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
  const [activeWallpaper, setActiveWallpaper] = useState<WallpaperId>("blossom");
  const [customWallpaper, setCustomWallpaper] = useState<WallpaperFile | null>(null);
  const [appearanceOpen, setAppearanceOpen] = useState(false);
  const [wallpaperBrightness, setWallpaperBrightness] = useState(94);
  const [wallpaperBlur, setWallpaperBlur] = useState(3);
  const [wallpaperVignette, setWallpaperVignette] = useState(18);
  const [workspaceOpacity, setWorkspaceOpacity] = useState(36);
  const [wallpaperMotionMode, setWallpaperMotionMode] = useState<WallpaperMotionMode>("cinematic");
  const [wallpaperMotionStrength, setWallpaperMotionStrength] = useState(55);
  const [wallpaperShot, setWallpaperShot] = useState(0);
  const [recentWallpapers, setRecentWallpapers] = useState<RecentWallpaper[]>([]);
  const [recentProjectPath, setRecentProjectPath] = useState<string | undefined>();
  const [apiConfig, setApiConfig] = useState<ApiIntegrationConfig>(defaultApiConfig);
  const [knowledgeBase, setKnowledgeBase] = useState<KnowledgeBaseConfig>(defaultKnowledgeBase);
  const [ccSwitchSync, setCcSwitchSync] = useState<CcSwitchSync | null>(null);
  const [apiSyncMessage, setApiSyncMessage] = useState("可同步 CC Switch，也可继续使用本机 Agent CLI。");
  const [settingsLoaded, setSettingsLoaded] = useState(false);
  const [queueLoaded, setQueueLoaded] = useState(false);
  const [jobs, setJobs] = useState<AutomationJob[]>([]);
  const [jobEvents, setJobEvents] = useState<Record<string, QueueEvent[]>>({});
  const [jobLogTails, setJobLogTails] = useState<Record<string, QueueLogTail>>({});
  const [expandedJobId, setExpandedJobId] = useState<string | null>(null);
  const [activeAgentJobId, setActiveAgentJobId] = useState<string | null>(null);
  const [agentMessages, setAgentMessages] = useState<AgentChatMessage[]>([]);
  const [agentInput, setAgentInput] = useState("");
  const [manualReviewDrafts, setManualReviewDrafts] = useState<Record<string, ManualReviewDraft>>({});
  const [workerStatus, setWorkerStatus] = useState<WorkerStatus>({ running: false, message: "桌面端可启动" });
  const [workerAction, setWorkerAction] = useState<"start" | "stop" | "restart" | null>(null);
  const [retryingJobId, setRetryingJobId] = useState<string | null>(null);
  const [runtimeHealth, setRuntimeHealth] = useState<RuntimeHealth | null>(null);
  const [runtimeMessage, setRuntimeMessage] = useState("正在检测 Agent、skills 与 CAD 环境...");
  const [windowHint, setWindowHint] = useState("窗口控制就绪");
  const [codexConfig, setCodexConfig] = useState<CodexConfig>({
    objective: "根据用户输入自动判断最佳 CAD 任务类型、制造方式、材料和交付格式，生成可制造结果并解释选择理由。",
    cadApplication: "auto",
    target: "auto",
    expectedOutput: "auto",
    process: "auto",
    material: "auto",
    unit: "mm",
    length: 0,
    width: 0,
    height: 0,
    wallThickness: 0,
    outputDir: "Documents/CADAutomationWorkbench",
    strictGbDrawing: true,
    realCutouts: true,
    localCadAutomation: true,
  });
  const wallpaperInputRef = useRef<HTMLInputElement>(null);
  const completedChatJobIdsRef = useRef<Set<string>>(new Set());
  const reducedMotion = useReducedMotion();

  const queueSummary = useMemo(() => {
    const approvalRequired = jobs.filter((job) => job.status === "approval_required").length;
    const reviewRequired = jobs.filter((job) => job.status === "review_required").length;
    const running = jobs.filter((job) => job.status === "running").length;
    const queued = jobs.filter((job) => job.status === "queued").length;
    if (approvalRequired > 0) return `${approvalRequired} 个待审批`;
    if (reviewRequired > 0) return `${reviewRequired} 个待复核`;
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
  const workspaceTemplates = useMemo(() => {
    if (!["model", "holes", "drawing"].includes(activeTab)) return [];
    return taskTemplates.filter((item) => item.tab === activeTab);
  }, [activeTab]);

  const activeAgentJob = useMemo(() => jobs.find((job) => job.id === activeAgentJobId) ?? jobs.find((job) => job.uiConfig?.agentChat === true) ?? jobs[0], [activeAgentJobId, jobs]);
  const resultJob = useMemo(
    () => activeAgentJob || jobs.find((job) => collectJobArtifacts(job).length > 0 || job.reviewGate?.checks?.length || job.result?.message || job.error),
    [activeAgentJob, jobs],
  );
  const resultArtifacts = useMemo(() => collectJobArtifacts(resultJob), [resultJob]);
  const resultChecks = resultJob?.reviewGate?.checks ?? resultJob?.result?.checks ?? [];
  const resultFeatures = realFeatureRows(resultJob);
  const codexPrompt = useMemo(() => buildCodexPrompt(codexConfig, recentProjectPath, runtimeHealth), [codexConfig, recentProjectPath, runtimeHealth]);
  const recentJobs = useMemo(() => jobs.slice(0, 5), [jobs]);
  const selectedProvider = useMemo(
    () => runtimeHealth?.agentProviders?.find((provider) => provider.id === apiConfig.agentProvider),
    [apiConfig.agentProvider, runtimeHealth],
  );
  const selectedCcSwitchProviders = useMemo(
    () => ccSwitchProvidersForAgent(ccSwitchSync, apiConfig.agentProvider),
    [apiConfig.agentProvider, ccSwitchSync],
  );

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
  }

  function updateJob(id: string, updater: (job: AutomationJob) => AutomationJob) {
    setJobs((items) => {
      const next = items.map((item) => {
        if (item.id !== id) return item;
        return updater(item);
      });
      saveLocalQueue(next);
      return next;
    });
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
    setWorkerAction("start");
    try {
      const status = await invoke<WorkerStatus>("start_worker", {
        repoPath: runtimeHealth?.skillRoot ?? "",
        enableCodex: true,
        codexFullAccess: codexConfig.localCadAutomation,
      });
      setWorkerStatus(status);
    } catch (error) {
      setWorkerStatus({ running: false, message: `worker 启动失败: ${String(error)}` });
    } finally {
      setWorkerAction(null);
    }
  }

  async function stopLocalWorker() {
    if (!isTauriRuntime()) return;
    setWorkerAction("stop");
    try {
      const status = await invoke<WorkerStatus>("stop_worker");
      setWorkerStatus(status);
    } catch (error) {
      setWorkerStatus({ running: false, message: `worker 停止失败: ${String(error)}` });
    } finally {
      setWorkerAction(null);
    }
  }

  async function restartLocalWorker() {
    if (!isTauriRuntime()) {
      setWorkerStatus({ running: false, message: "请在桌面端重启 worker" });
      return;
    }
    setWorkerAction("restart");
    try {
      const stopped = await invoke<WorkerStatus>("stop_worker");
      const status = await invoke<WorkerStatus>("start_worker", {
        repoPath: runtimeHealth?.skillRoot ?? "",
        enableCodex: true,
        codexFullAccess: codexConfig.localCadAutomation,
      });
      const recovered = stopped.recoveredJobs ?? 0;
      setWorkerStatus({
        ...status,
        message: recovered > 0 ? `worker 已重启，恢复任务 ${recovered} 个` : "worker 已重启",
      });
    } catch (error) {
      setWorkerStatus({ running: false, message: `worker 重启失败: ${String(error)}` });
    } finally {
      setWorkerAction(null);
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
      const agentProvider = apiConfig.agentProvider;
      const provider = activeCcSwitchProvider(sync, agentProvider);
      const providerCount = ccSwitchProvidersForAgent(sync, agentProvider).length;
      const nextConfig: ApiIntegrationConfig = {
        mode: "cc_switch",
        agentProvider,
        providerName: provider?.name || provider?.id || agentProviderCatalog[agentProvider].name,
        endpoint: provider?.endpoint || "由 CC Switch 配置决定",
        model: provider?.model || "由 CC Switch 配置决定",
        keyStatus: provider ? "synced" : selectedProvider?.ready ? "configured" : "missing",
        lastSyncAt: sync.syncedAt,
        sourcePath: sync.databasePath || sync.configPath,
      };
      setCcSwitchSync(sync);
      setApiConfig(nextConfig);
      setApiSyncMessage(providerCount > 0
        ? `已读取 ${providerCount} 个 ${agentProviderCatalog[agentProvider].name} 路由，凭据由 CC Switch 管理。`
        : `CC Switch 中暂未配置 ${agentProviderCatalog[agentProvider].name} 路由，继续使用当前 CLI 登录态。`);
    } catch (error) {
      setApiSyncMessage(`同步失败: ${String(error)}`);
    }
  }

  function enqueueCodexTask() {
    void enqueueCodexTaskWithConfig(codexConfig);
  }

  async function ensureRuntimeHealth(): Promise<RuntimeHealth> {
    let health = runtimeHealth;
    if (!health?.skillRoot) {
      setRuntimeMessage("正在检测 Agent、skills 与 CAD 环境...");
      health = await invoke<RuntimeHealth>("runtime_health");
    } else {
      const providerHealth = await invoke<Pick<RuntimeHealth, "agentProviders">>("agent_provider_runtime_health");
      health = { ...health, agentProviders: providerHealth.agentProviders };
    }
    setRuntimeHealth(health);
    const provider = health.agentProviders?.find((item) => item.id === apiConfig.agentProvider);
    if (!provider?.installed || !provider.ready) {
      throw new Error(provider?.auth?.message || provider?.version?.message || `${agentProviderCatalog[apiConfig.agentProvider].name} CLI 未就绪`);
    }
    setRuntimeMessage(
      provider.verified
        ? `${provider.name} 真实任务已验证，skills 与本地 CAD 路由已就绪`
        : `${provider.name} CLI 已安装，将在首个真实任务完成后记录验证状态`,
    );
    return health;
  }

  async function enqueueCodexTaskWithConfig(config: CodexConfig) {
    if (!isTauriRuntime()) {
      setAgentMessages((messages) => [...messages, createChatMessage("system", "浏览器仅用于界面预览，不会模拟任务成功。请启动 CAD Studio 桌面版执行真实任务。")].slice(-40));
      return;
    }
    let activeRuntime: RuntimeHealth;
    try {
      activeRuntime = await ensureRuntimeHealth();
    } catch (error) {
      setAgentMessages((messages) => [...messages, createChatMessage("system", `本地运行环境未就绪：${String(error)}`)].slice(-40));
      return;
    }
    const strictRules = [
      config.realCutouts ? "孔槽、接口、沉头和螺纹必须是真实几何切除" : "明确说明孔槽实现状态",
      config.strictGbDrawing ? "必须按中国机械制图常用格式复核 CAD 图纸" : "说明当前图纸规范覆盖范围",
      `${cadApplicationLabels[config.cadApplication]}: ${cadApplicationRoutes[config.cadApplication]}`,
      config.localCadAutomation ? "允许经审批后调用本机 SolidWorks / AutoCAD 桌面自动化能力。" : "不直接调用本机 CAD 软件，仅生成计划、脚本或说明。",
      `所有交付物只保存到本地输出目录: ${config.outputDir}`,
    ];
    const capabilities = config.localCadAutomation ? ["cad_macro"] : [];
    const providerMeta = agentProviderCatalog[apiConfig.agentProvider];
    const job = createJob("agent_task", recentProjectPath, {
      executor: "agent",
      title: conciseTaskTitle(config.objective, `${codexTargets[config.target]}任务`),
      detail: `${cadApplicationLabels[config.cadApplication]} · ${codexTargets[config.target]} · ${resolvedExpectedOutput(config)}`,
      objective: config.objective,
      targetSoftware: cadApplicationLabels[config.cadApplication],
      target: codexTargets[config.target],
      expectedOutput: resolvedExpectedOutput(config),
      strictRules,
      capabilities,
      prompt: buildCodexPrompt(config, recentProjectPath),
      cwd: activeRuntime.skillRoot,
      skillPath: activeRuntime.solidworksSkillPath,
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
        agentRuntime: {
          provider: apiConfig.agentProvider,
          providerName: providerMeta.name,
          protocol: providerMeta.protocol,
          model: apiConfig.model.includes("跟随") || apiConfig.model.includes("配置决定") ? "" : apiConfig.model,
        },
        cadRuntime: {
          application: config.cadApplication,
          applicationLabel: cadApplicationLabels[config.cadApplication],
          route: cadApplicationRoutes[config.cadApplication],
          localCadAutomation: config.localCadAutomation,
          solidworksSkillPath: activeRuntime.solidworksSkillPath,
          autocadSkillPath: activeRuntime.autocadSkillPath,
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
        engineeringOrchestration: {
          mode: "plan_guided_dag",
          trigger: "检测到跨零件、孔槽、装配、Motion、图纸或交付的综合任务时自动启用",
          stages: ["需求", "零件", "孔槽与倒角", "装配 Mate", "Motion", "工程图 BOM", "导出", "综合复核"],
          retry: "对话追改时只重规划受影响阶段，并使其下游结果失效",
          cadConcurrency: 1,
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
        knowledgeBase,
      },
    });
    try {
      await persistJob(job);
      upsertJob(job);
      if (!workerStatus.running) void startLocalWorker();
    } catch (error) {
      setAgentMessages((messages) => [
        ...messages,
        createChatMessage("system", `任务写入失败，没有进入执行队列：${String(error)}`),
      ].slice(-40));
    }
  }

  async function submitAgentMessage() {
    const text = agentInput.trim();
    if (!text) return;

    const userMessage = createChatMessage("user", text);
    if (!isTauriRuntime()) {
      setAgentMessages((messages) => [...messages, userMessage, createChatMessage("system", "浏览器预览不会创建模拟任务。请打开桌面版后继续。")].slice(-40));
      setAgentInput("");
      return;
    }
    let activeRuntime: RuntimeHealth;
    try {
      activeRuntime = await ensureRuntimeHealth();
    } catch (error) {
      setAgentMessages((messages) => [...messages, userMessage, createChatMessage("system", `本地环境未就绪：${String(error)}`)].slice(-40));
      setAgentInput("");
      return;
    }
    const prompt = buildChatPrompt(codexConfig, apiConfig, text, [...agentMessages, userMessage], recentProjectPath, activeRuntime);
    const providerMeta = agentProviderCatalog[apiConfig.agentProvider];
    const job = createJob("agent_task", recentProjectPath, {
      executor: "agent",
      title: conciseTaskTitle(text, "AI CAD 对话任务"),
      detail: `${cadApplicationLabels[codexConfig.cadApplication]} · ${codexTargets[codexConfig.target]} · 可继续追问修改`,
      objective: text,
      targetSoftware: cadApplicationLabels[codexConfig.cadApplication],
      target: codexTargets[codexConfig.target],
      expectedOutput: resolvedExpectedOutput(codexConfig),
      strictRules: [
        "以软件内 AI 对话形式响应用户，输出可公开的步骤摘要、执行结果和文件位置。",
        codexConfig.realCutouts ? "涉及孔槽时必须是真实几何开孔/切除。" : "涉及孔槽时必须说明实现状态。",
        codexConfig.strictGbDrawing ? "涉及图纸时必须遵循中国常用机械制图规范并复核尺寸链。" : "涉及图纸时说明规范覆盖范围。",
        "所有交付物只保存到用户指定的本地输出目录。",
      ],
      capabilities: codexConfig.localCadAutomation ? ["cad_macro"] : [],
      prompt,
      cwd: activeRuntime.skillRoot,
      skillPath: activeRuntime.solidworksSkillPath,
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
        agentRuntime: {
          provider: apiConfig.agentProvider,
          providerName: providerMeta.name,
          protocol: providerMeta.protocol,
          model: apiConfig.model.includes("跟随") || apiConfig.model.includes("配置决定") ? "" : apiConfig.model,
        },
        outputDir: codexConfig.outputDir,
        knowledgeBase,
        engineeringOrchestration: {
          mode: "plan_guided_dag",
          trigger: "复杂机械工程自动拆解；简单任务保持最小执行路径",
          stages: ["需求", "零件", "孔槽与倒角", "装配 Mate", "Motion", "工程图 BOM", "导出", "综合复核"],
          retry: "局部修改只重规划受影响阶段及其下游",
          cadConcurrency: 1,
        },
        sourceJobId: activeAgentJob?.id,
        apiRuntime: apiConfig,
        cadRuntime: {
          application: codexConfig.cadApplication,
          applicationLabel: cadApplicationLabels[codexConfig.cadApplication],
          route: cadApplicationRoutes[codexConfig.cadApplication],
          localCadAutomation: codexConfig.localCadAutomation,
          solidworksSkillPath: activeRuntime.solidworksSkillPath,
          autocadSkillPath: activeRuntime.autocadSkillPath,
        },
      },
    });

    setAgentInput("");
    try {
      await persistJob(job);
      setActiveAgentJobId(job.id);
      setExpandedJobId(job.id);
      setAgentMessages((messages) => [
        ...messages,
        userMessage,
        createChatMessage("assistant", `收到，我已经把这句话转成一条本地 ${providerMeta.name} 执行任务。你可以在下方看到公开步骤、审批、日志和结果；不满意就继续补充要求。`, job.id),
      ].slice(-40));
      upsertJob(job);
      if (!workerStatus.running) void startLocalWorker();
    } catch (error) {
      setAgentMessages((messages) => [
        ...messages,
        userMessage,
        createChatMessage("system", `任务写入失败，没有进入执行队列：${String(error)}`),
      ].slice(-40));
    }
  }

  function enqueueTemplateTask(template: (typeof taskTemplates)[number]) {
    const nextConfig = {
      ...codexConfig,
      target: template.target,
      expectedOutput: template.output,
      objective: `${template.title}: ${template.detail}。请根据用户导入的资料或当前配置生成可制造 CAD 结果，并输出必要的复核记录。`,
    } satisfies CodexConfig;
    setCodexConfig(nextConfig);
    void enqueueCodexTaskWithConfig(nextConfig);
  }

  function enqueueDeliveryTask() {
    const nextConfig = {
      ...codexConfig,
      target: "package",
      expectedOutput: "auto",
      objective: "整理当前项目的真实 CAD 产物，验证文件存在性和格式，生成本地交付清单；缺失文件必须明确报错，不能用占位文件代替。",
    } satisfies CodexConfig;
    setCodexConfig(nextConfig);
    void enqueueCodexTaskWithConfig(nextConfig);
  }

  async function cancelJob(id: string) {
    if (isTauriRuntime()) {
      try {
        const cancelled = await invoke<AutomationJob>("cancel_queue_job", { id });
        upsertJob(cancelled);
        return;
      } catch (error) {
        updateJob(id, (item) => ({ ...item, lastMessage: `取消失败: ${String(error)}`, updatedAt: new Date().toISOString() }));
        return;
      }
    }
    updateJob(id, (item) => ({ ...item, status: "cancelled", progress: 0, updatedAt: new Date().toISOString() }));
  }

  async function retryJob(id: string) {
    if (retryingJobId) return;
    setRetryingJobId(id);
    try {
      if (isTauriRuntime()) {
        const retried = await invoke<AutomationJob>("retry_queue_job", { id });
        upsertJob(retried);
      } else {
        updateJob(id, (item) => ({
          ...item,
          runId: `retry-${Date.now()}`,
          status: "queued",
          progress: 0,
          updatedAt: new Date().toISOString(),
          lastMessage: "用户已重新执行失败任务，等待 Worker 接单。",
          result: undefined,
          artifacts: [],
          artifactLedgerPath: undefined,
          reviewGatePath: undefined,
          reviewGate: undefined,
          reviewedAt: undefined,
          reviewedBy: undefined,
          reviewDecision: undefined,
          reviewNote: undefined,
          runnerId: undefined,
          workerPid: undefined,
          heartbeatAt: undefined,
          leaseUntil: undefined,
          workerLog: undefined,
          error: undefined,
        }));
      }
      setExpandedJobId(id);
      if (!workerStatus.running) void startLocalWorker();
    } catch (error) {
      updateJob(id, (item) => ({
        ...item,
        lastMessage: `重新执行失败: ${String(error)}`,
        updatedAt: new Date().toISOString(),
      }));
    } finally {
      setRetryingJobId(null);
    }
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

  async function reviewJob(id: string, approved: boolean) {
    const job = jobs.find((item) => item.id === id);
    const draft = manualReviewDrafts[id] ?? { note: "", checks: [] };
    const requiredChecks = reviewOptionsFor(job).map(([key]) => key);
    if (draft.note.trim().length < (approved ? 8 : 4)) {
      updateJob(id, (item) => ({
        ...item,
        lastMessage: approved ? "通过复核前请填写至少 8 个字的具体复核说明。" : "驳回前请填写具体问题。",
      }));
      return;
    }
    if (approved && requiredChecks.some((key) => !draft.checks.includes(key))) {
      updateJob(id, (item) => ({ ...item, lastMessage: "请完成当前任务要求的全部人工复核项。" }));
      return;
    }
    if (isTauriRuntime()) {
      try {
        const reviewedJob = await invoke<AutomationJob>(
          approved ? "approve_review_job" : "reject_review_job",
          approved ? { id, reason: draft.note.trim(), checks: draft.checks } : { id, reason: draft.note.trim() },
        );
        upsertJob(reviewedJob);
        setManualReviewDrafts((items) => {
          const next = { ...items };
          delete next[id];
          return next;
        });
      } catch (error) {
        updateJob(id, (item) => ({
          ...item,
          lastMessage: `人工复核失败: ${String(error)}`,
          updatedAt: new Date().toISOString(),
        }));
      }
      return;
    }

    updateJob(id, (item) => ({
      ...item,
      status: approved ? "passed" : "failed",
      reviewDecision: approved ? "approved" : "rejected",
      reviewedAt: new Date().toISOString(),
      reviewedBy: "local-user",
      reviewNote: draft.note.trim(),
      lastMessage: approved ? "人工复核已通过，任务可以交付。" : "人工复核未通过，任务已驳回。",
      updatedAt: new Date().toISOString(),
    }));
  }

  function updateManualReviewDraft(id: string, patch: Partial<ManualReviewDraft>) {
    setManualReviewDrafts((items) => ({
      ...items,
      [id]: { ...(items[id] ?? { note: "", checks: [] }), ...patch },
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
      setAgentMessages((messages) => [...messages, createChatMessage("system", "浏览器预览不能访问本机 CAD 文件。请在桌面版中导入 STEP、STL、SLDPRT、SLDASM、DWG、DXF、PDF 或图片。")].slice(-40));
      return;
    }

    const selected = await openDialog({
      multiple: false,
      filters: [
        {
          name: "CAD / Drawing / Sketch",
          extensions: ["step", "stp", "sldprt", "sldasm", "stl", "iges", "igs", "dxf", "dwg", "pdf", "png", "jpg", "jpeg", "webp", "bmp"],
        },
      ],
    });

    if (!selected || Array.isArray(selected)) return;
    setRecentProjectPath(selected);
    setAgentMessages((messages) => [
      ...messages,
      createChatMessage("system", `已把 ${displayNameFromPath(selected)} 加入当前任务上下文。请在对话中说明要新建、修改、出图还是检查。`),
    ].slice(-40));
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

  async function chooseKnowledgeRoot() {
    if (!isTauriRuntime()) return;
    const selected = await openDialog({ multiple: false, directory: true });
    if (!selected || Array.isArray(selected)) return;
    setKnowledgeBase((config) => ({
      ...config,
      localRoots: [selected, ...config.localRoots.filter((item) => item !== selected)].slice(0, 8),
    }));
  }

  function importWallpaper(event: ChangeEvent<HTMLInputElement>) {
    useWallpaperFile(event.target.files?.[0]);
    event.target.value = "";
  }

  function dropWallpaper(event: DragEvent<HTMLButtonElement>) {
    event.preventDefault();
    useWallpaperFile(event.dataTransfer.files?.[0]);
  }

  function controlWallpaperPointer(event: ReactPointerEvent<HTMLElement>) {
    if (reducedMotion || wallpaperMotionMode !== "follow") return;
    const bounds = event.currentTarget.getBoundingClientRect();
    const strength = wallpaperMotionStrength / 100;
    const x = ((event.clientX - bounds.left) / bounds.width - 0.5) * -18 * strength;
    const y = ((event.clientY - bounds.top) / bounds.height - 0.5) * -12 * strength;
    event.currentTarget.style.setProperty("--wallpaper-pointer-x", `${x}px`);
    event.currentTarget.style.setProperty("--wallpaper-pointer-y", `${y}px`);
  }

  function resetWallpaperPointer(event: ReactPointerEvent<HTMLElement>) {
    event.currentTarget.style.setProperty("--wallpaper-pointer-x", "0px");
    event.currentTarget.style.setProperty("--wallpaper-pointer-y", "0px");
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
      if (action === "close") {
        await invoke("close_app");
        return;
      }
      if (action === "minimize") await appWindow.minimize();
      if (action === "maximize") {
        if (await appWindow.isMaximized()) {
          await appWindow.unmaximize();
          setWindowHint("窗口已还原");
          return;
        }
        await appWindow.maximize();
      }
      setWindowHint(`窗口已${labels[action]}`);
    } catch (error) {
      console.error(error);
      setWindowHint("窗口控制失败，请重启桌面版后再试");
    }
  }

  useEffect(() => {
    if (!isTauriRuntime()) {
      setRuntimeMessage("浏览器预览模式：真实 Agent、skills 与 CAD 检测仅在桌面版运行。 ");
      return;
    }
    let disposed = false;
    void invoke<RuntimeHealth>("runtime_health")
      .then((health) => {
        if (disposed) return;
        setRuntimeHealth(health);
        if (health.defaultOutputDir) {
          setCodexConfig((config) => ({
            ...config,
            outputDir: config.outputDir === "Documents/CADAutomationWorkbench" ? health.defaultOutputDir! : config.outputDir,
          }));
        }
        const installedProviders = health.agentProviders?.filter((provider) => provider.installed) ?? [];
        const verifiedProviders = installedProviders.filter((provider) => provider.verified);
        setApiConfig((config) => {
          const current = health.agentProviders?.find((provider) => provider.id === config.agentProvider);
          return { ...config, keyStatus: current?.verified ? "configured" : "missing" };
        });
        setRuntimeMessage(
          installedProviders.length
            ? `已安装 ${installedProviders.map((provider) => provider.name).join("、")}；真实任务已验证 ${verifiedProviders.length ? verifiedProviders.map((provider) => provider.name).join("、") : "无"}。SolidWorks ${health.solidworks?.ok ? "可用" : "待检查"}，AutoCAD ${health.autocad?.ok ? "可用" : "未检测到"}。`
            : "未检测到 Agent Provider，请在设置中检查 CLI 安装状态。",
        );
      })
      .catch((error) => {
        if (!disposed) setRuntimeMessage(`环境检测失败：${String(error)}`);
      });
    return () => {
      disposed = true;
    };
  }, []);

  useEffect(() => {
    return () => {
      revokeObjectUrl(customWallpaper?.url);
    };
  }, [customWallpaper?.url]);

  useEffect(() => {
    setWallpaperShot(0);
    if (reducedMotion || wallpaperMotionMode !== "cinematic") return;
    const timer = window.setInterval(() => setWallpaperShot((shot) => (shot + 1) % wallpaperShots.length), 14000);
    return () => window.clearInterval(timer);
  }, [activeWallpaper, reducedMotion, wallpaperMotionMode]);

  useEffect(() => {
    const settings = loadSettings();
    if (settings) {
      setActiveWallpaper(settings.activeWallpaper);
      setWallpaperBrightness(settings.wallpaperBrightness);
      setWallpaperBlur(settings.wallpaperBlur);
      setWallpaperVignette(settings.wallpaperVignette);
      setWorkspaceOpacity(settings.workspaceOpacity);
      setWallpaperMotionMode(settings.wallpaperMotionMode);
      setWallpaperMotionStrength(settings.wallpaperMotionStrength);
      setRecentWallpapers(settings.recentWallpapers);
      setRecentProjectPath(settings.recentProjectPath);
      setApiConfig(settings.apiConfig ?? defaultApiConfig);
      setKnowledgeBase(settings.knowledgeBase ?? defaultKnowledgeBase);
      if (settings.customWallpaperPath) setCustomWallpaper(wallpaperFromPath(settings.customWallpaperPath));
    }
    setSettingsLoaded(true);
  }, []);

  useEffect(() => {
    const savedMessages = loadAgentChat();
    setAgentMessages(savedMessages);
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
    const updates: AgentChatMessage[] = [];
    for (const job of jobs) {
      if (job.uiConfig?.agentChat !== true) continue;
      if (!["passed", "review_required", "failed", "approval_required", "cancelled"].includes(job.status)) continue;
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
      } else if (job.status === "review_required") {
        updates.push(createChatMessage("assistant", `这轮执行已结束，但尚不能作为最终交付：${job.lastMessage || "仍需 CAD 原生或人工复核。"}`, job.id));
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
      activeWallpaper: activeWallpaper === "custom" && !customWallpaper?.sourcePath ? "blossom" : activeWallpaper,
      customWallpaperPath: customWallpaper?.sourcePath,
      wallpaperBrightness,
      wallpaperBlur,
      wallpaperVignette,
      workspaceOpacity,
      wallpaperMotionMode,
      wallpaperMotionStrength,
      defaultWallpaperVersion: 1,
      panelOpacityVersion: 1,
      recentWallpapers,
      recentProjectPath,
      apiConfig,
      knowledgeBase,
    };
    localStorage.setItem(SETTINGS_KEY, JSON.stringify(settings));
  }, [activeWallpaper, apiConfig, customWallpaper?.sourcePath, knowledgeBase, recentProjectPath, recentWallpapers, settingsLoaded, wallpaperBlur, wallpaperBrightness, wallpaperMotionMode, wallpaperMotionStrength, wallpaperVignette, workspaceOpacity]);

  function renderTemplatePanel() {
    return (
      <section className="capability-board">
        {workspaceTemplates.map((template, index) => {
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
    );
  }

  function renderProjectPanel() {
    return (
      <section className="project-console">
        <article className="project-brief">
          <div className="panel-heading compact">
            <div>
              <p className="eyebrow">PROJECT</p>
              <h2>{recentProjectPath ? displayNameFromPath(recentProjectPath) : "新项目"}</h2>
            </div>
            <span className="status-pill">{workerStatus.running ? "可执行" : "待启动"}</span>
          </div>
          <div className="project-quick-grid">
            <button type="button" onClick={() => setActiveTab("model")}>
              <CubeFocus size={19} weight="duotone" />
              <strong>从零建模</strong>
              <span>不需要先导入文件</span>
            </button>
            <button type="button" onClick={chooseProjectFile}>
              <FolderOpen size={19} weight="duotone" />
              <strong>导入已有文件</strong>
              <span>STEP / STL / DWG / PDF / 图片</span>
            </button>
            <button type="button" onClick={() => setActiveTab("drawing")}>
              <FilePlus size={19} weight="duotone" />
              <strong>出工程图</strong>
              <span>GB/T 图框、尺寸、孔表</span>
            </button>
          </div>
        </article>

        <aside className="project-list-panel">
          <div className="panel-heading compact">
            <div>
              <p className="eyebrow">CONTEXT</p>
              <h2>当前上下文</h2>
            </div>
          </div>
          <div className="context-summary">
            <span>参考文件</span>
            <strong>{recentProjectPath ? displayNameFromPath(recentProjectPath) : "未导入，可直接从零建模"}</strong>
            <span>执行环境</span>
            <strong>{runtimeMessage}</strong>
            <span>默认决策</span>
            <strong>未指定项由 AI 选择；关键尺寸与安全参数必须确认</strong>
          </div>
        </aside>
      </section>
    );
  }

  function renderCheckPanel() {
    return (
      <section className="review-workspace">
        <article className="review-summary-card">
          <div className="panel-heading compact">
            <div>
              <p className="eyebrow">REVIEW</p>
              <h2>{resultJob ? jobDisplayTitle(resultJob) : "等待任务完成"}</h2>
            </div>
            <span className="status-pill">{jobReviewStatusLabel(resultJob)}</span>
          </div>
          <div className="review-table">
            {resultChecks.length > 0 ? (
              resultChecks.map((check, index) => (
                <div className={`review-row ${check.status || "pending"}`} key={check.id || index}>
                  <span>{check.severity || "CHECK"}</span>
                  <strong>{reviewStatusLabel(check.status)}</strong>
                  <small>{check.message || "复核项已返回，但没有说明。"}</small>
                </div>
              ))
            ) : (
              <div className="inspector-empty">
                <strong>没有真实复核数据</strong>
                <p>任务完成后会在这里显示文件存在性、格式、孔槽、图纸规范和制造风险。</p>
              </div>
            )}
          </div>
        </article>

        <aside className="review-summary-card compact-side">
          <div className="panel-heading compact">
            <div>
              <p className="eyebrow">FEATURES</p>
              <h2>几何特征</h2>
            </div>
          </div>
          <div className="hole-list">
            {resultFeatures.length > 0 ? (
              resultFeatures.map((feature, index) => (
                <div className="hole-row" key={index}>
                  <span>{recordText(feature, ["name", "type", "label"], `特征 ${index + 1}`)}</span>
                  <strong>{recordText(feature, ["spec", "size", "dimension", "value"], "")}</strong>
                  <small>{recordText(feature, ["position", "pos", "location", "note"], "已由任务结果返回")}</small>
                  <em>{recordText(feature, ["status"], "待复核")}</em>
                </div>
              ))
            ) : (
              <div className="inspector-empty">
                <strong>暂无特征表</strong>
                <p>AI 返回真实孔、槽、螺纹或装配特征后会自动列出。</p>
              </div>
            )}
          </div>
        </aside>
      </section>
    );
  }

  function renderExportPanel() {
    return (
      <section className="delivery-console">
        <article className="delivery-main">
          <div className="panel-heading compact">
            <div>
              <p className="eyebrow">DELIVERY</p>
              <h2>本地交付清单</h2>
            </div>
            <motion.button className="primary-button compact-action shine" type="button" onClick={enqueueDeliveryTask} whileHover={reducedMotion ? undefined : { y: -2 }} whileTap={{ scale: 0.975 }}>
              <Archive size={17} weight="duotone" />
              生成交付包
            </motion.button>
          </div>
          <div className="artifact-list delivery-artifacts">
            {resultArtifacts.length > 0 ? (
              resultArtifacts.map((artifact, index) => (
                <div className={artifact.exists === false ? "artifact-row missing" : "artifact-row"} key={`${artifact.path}-${index}`}>
                  <div>
                    <strong>{artifactKindLabel(artifact.kind, artifact.path)}</strong>
                    <span>{artifact.path}</span>
                  </div>
                  <small>{formatBytes(artifact.sizeBytes) || artifactStatusLabel(artifact)}</small>
                </div>
              ))
            ) : (
              <div className="inspector-empty">
                <strong>还没有可交付文件</strong>
                <p>先让 AI 完成建模、出图或转换任务，交付中心会读取真实输出物。</p>
              </div>
            )}
          </div>
        </article>

        <aside className="delivery-side">
          <div className="delivery-path">
            <span>输出目录</span>
            <strong>{codexConfig.outputDir}</strong>
            <button type="button" onClick={chooseOutputDir}>更改目录</button>
          </div>
          <div className="format-strip">
            {deliveryFormats.map((format) => {
              const status = deliveryFormatStatus(format, resultJob, resultArtifacts);
              return (
                <span className={status} key={format}>
                  {format} · {status === "ready" ? "已生成" : status === "missing" ? "缺失" : "未要求"}
                </span>
              );
            })}
          </div>
          <div className="review-mini">
            <span>复核状态</span>
            <strong>{resultJob ? jobReviewStatusLabel(resultJob) : "等待生成后复核"}</strong>
          </div>
        </aside>
      </section>
    );
  }

  function renderSettingsPanel() {
    return (
      <section className="tab-surface">
        <div className="settings-studio">
          <article className="setting-card api-card primary-setting">
            <div className="setting-title">
              <span>执行核心</span>
              <strong>{agentProviderCatalog[apiConfig.agentProvider].name}</strong>
              <p>自动检测本机 Agent CLI，任务协议、审批、RAG、CAD 工具与交付复核保持一致；本软件不保存 API Key。</p>
            </div>
            <div className="agent-provider-grid" role="radiogroup" aria-label="Agent Provider">
              {(Object.keys(agentProviderCatalog) as AgentProviderId[]).map((providerId) => {
                const metadata = agentProviderCatalog[providerId];
                const health = runtimeHealth?.agentProviders?.find((item) => item.id === providerId);
                const ccSwitchRoute = activeCcSwitchProvider(ccSwitchSync, providerId);
                const unavailable = runtimeHealth ? !health?.installed : false;
                return (
                  <button
                    type="button"
                    role="radio"
                    aria-checked={apiConfig.agentProvider === providerId}
                    disabled={unavailable}
                    className={apiConfig.agentProvider === providerId ? "active" : ""}
                    key={providerId}
                    onClick={() => setApiConfig((config) => ({
                      ...config,
                      agentProvider: providerId,
                      providerName: ccSwitchRoute?.name || metadata.name,
                      endpoint: ccSwitchRoute?.endpoint || health?.entry || "本机 CLI",
                      model: ccSwitchRoute?.model || metadata.model,
                      keyStatus: ccSwitchRoute ? "synced" : health?.verified ? "configured" : "missing",
                    }))}
                  >
                    <strong>{metadata.name}</strong>
                    <span>{health?.installed ? `已安装 · ${health.version?.message || "版本未知"}` : runtimeHealth ? "未安装" : "等待检测"}</span>
                    <small>{health?.verified ? "真实任务已验证" : health?.auth?.ok === false ? "认证失败，暂不可执行" : health?.installed ? "等待首个真实任务验证" : "需要先安装 CLI"}</small>
                  </button>
                );
              })}
            </div>
            <div className="api-mode-grid">
              {(["codex_cli", "cc_switch"] as ApiIntegrationMode[]).map((mode) => (
                <button type="button" className={apiConfig.mode === mode ? "active" : ""} key={mode} onClick={() => setApiConfig((config) => ({ ...config, mode }))}>
                  {apiModeLabel(mode)}
                </button>
              ))}
            </div>
            <div className="api-sync-row">
              <button type="button" onClick={() => void syncCcSwitchConfig()}>
                读取 CC Switch 状态
              </button>
              <span>{apiSyncMessage}</span>
            </div>
            <div className="api-status-strip">
              <span>{selectedProvider?.name || agentProviderCatalog[apiConfig.agentProvider].name}: {selectedProvider?.ready ? "可执行" : "待确认"}</span>
              <span>CLI: {selectedProvider?.version?.message || "检测中"}</span>
              <span className="settings-path">入口: {selectedProvider?.entry || "检测中"}</span>
              <span>Skill: {runtimeHealth?.solidworksSkillPath || "检测中"}</span>
            </div>
            {selectedCcSwitchProviders.length ? (
              <div className="provider-list">
                <div className="provider-list-head">
                  <strong>{agentProviderCatalog[apiConfig.agentProvider].name} 模型路由</strong>
                  <span>{selectedCcSwitchProviders.length} 个 · 当前项由 CC Switch 决定</span>
                </div>
                {selectedCcSwitchProviders.map((provider) => (
                  <div className={provider.active ? "provider-row active" : "provider-row"} key={provider.id || provider.name}>
                    <div className="provider-main">
                      <strong>{provider.name || provider.id}</strong>
                      <small>{provider.endpoint || "端点由 CC Switch 管理"}</small>
                    </div>
                    <span>{provider.model || "模型跟随 CC Switch"}</span>
                    <small>{provider.authLabel || "配置由 CC Switch 管理"}</small>
                  </div>
                ))}
              </div>
            ) : null}
          </article>

          <article className="setting-card status-setting">
            <span>本地执行</span>
            <strong>{workerStatus.running ? `运行中 · PID ${workerStatus.pid ?? "-"}` : "未启动"}</strong>
            <p>{workerStatus.health?.heartbeatAt ? `最近心跳 ${workerStatus.health.heartbeatAt}` : runtimeMessage}</p>
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
          <article className="setting-card knowledge-setting">
            <span>专业知识库</span>
            <strong>{knowledgeBase.cloudEnabled ? "本地 + 云端" : "本地优先"}</strong>
            <div className="knowledge-mode" role="group" aria-label="知识库模式">
              <button type="button" className={!knowledgeBase.cloudEnabled ? "active" : ""} onClick={() => setKnowledgeBase((config) => ({ ...config, cloudEnabled: false }))}>本地</button>
              <button type="button" className={knowledgeBase.cloudEnabled ? "active" : ""} onClick={() => setKnowledgeBase((config) => ({ ...config, cloudEnabled: true }))}>云端增强</button>
            </div>
            {knowledgeBase.cloudEnabled ? (
              <div className="knowledge-fields">
                <label>
                  <span>HTTPS 检索地址</span>
                  <input value={knowledgeBase.endpoint} placeholder="https://rag.example.com/retrieve" onChange={(event) => setKnowledgeBase((config) => ({ ...config, endpoint: event.target.value }))} />
                </label>
                <label>
                  <span>命名空间</span>
                  <input value={knowledgeBase.namespace} onChange={(event) => setKnowledgeBase((config) => ({ ...config, namespace: event.target.value }))} />
                </label>
              </div>
            ) : (
              <p>{knowledgeBase.localRoots[0] || "使用内置 SolidWorks、制造和图纸规范知识。"}</p>
            )}
            <button type="button" onClick={() => void chooseKnowledgeRoot()}>添加本地标准库</button>
          </article>
        </div>
      </section>
    );
  }

  function renderHelpPanel() {
    const providers = runtimeHealth?.agentProviders ?? [];
    const installedProviders = providers.filter((provider) => provider.installed).map((provider) => provider.name);
    return (
      <section className="help-workspace">
        <div className="help-intro">
          <div>
            <span>首次使用</span>
            <strong>从一个明确需求开始</strong>
          </div>
          <p>准备一个输出文件夹，选择可用 AI；需要真实建模时再启用本机 CAD 自动化。</p>
        </div>
        <ol className="help-steps">
          <li><span>1</span><div><strong>检查环境</strong><p>在设置中确认 Python、至少一个 Agent CLI，以及需要使用的 SolidWorks 或 AutoCAD。</p></div></li>
          <li><span>2</span><div><strong>选择 AI</strong><p>选择 Codex、Claude Code、Gemini CLI 或 OpenCode。使用 CC Switch 时读取对应模型路由。</p></div></li>
          <li><span>3</span><div><strong>创建项目</strong><p>从零建模不必导入文件；修改现有设计时再导入 SLDPRT、STEP、DWG、PDF 或参考图片。</p></div></li>
          <li><span>4</span><div><strong>描述目标</strong><p>写清用途、关键尺寸、材料、工艺和输出格式；未指定的普通参数由 AI 选择，安全参数必须确认。</p></div></li>
          <li><span>5</span><div><strong>审批执行</strong><p>真实控制 CAD、访问外部目录或网络时，任务会等待人工批准。批准后本地执行器接单。</p></div></li>
          <li><span>6</span><div><strong>复核交付</strong><p>在复核页检查尺寸、孔槽、装配和文件，再到交付页确认 STEP、STL、DWG、PDF 等产物。</p></div></li>
        </ol>
        <div className="help-status-grid">
          <div><span>AI</span><strong>{installedProviders.length ? installedProviders.join("、") : "尚未检测到可用 CLI"}</strong></div>
          <div><span>Python</span><strong>{runtimeHealth?.python?.ok ? "已就绪" : "需要安装 Python 3"}</strong></div>
          <div><span>SolidWorks</span><strong>{runtimeHealth?.solidworks?.ok ? "可用" : "未检测到或待检查"}</strong></div>
          <div><span>AutoCAD</span><strong>{runtimeHealth?.autocad?.ok ? "可用" : "未检测到"}</strong></div>
        </div>
        <div className="help-note">
          <ShieldCheck size={19} weight="duotone" />
          <p>左侧是当前项目的任务历史。标题显示你的任务目标，不代表固定使用某个 AI；实际执行器以设置中的选择为准。</p>
        </div>
      </section>
    );
  }

  function renderWorkspacePanel() {
    if (activeTab === "project") return renderProjectPanel();
    if (activeTab === "check") return renderCheckPanel();
    if (activeTab === "export") return renderExportPanel();
    if (activeTab === "settings") return renderSettingsPanel();
    if (activeTab === "help") return renderHelpPanel();
    return renderTemplatePanel();
  }

  const activeWallpaperName =
    activeWallpaper === "custom" ? customWallpaper?.name ?? "我的壁纸" : wallpapers.find((item) => item.id === activeWallpaper)?.name ?? "Aurora";
  const activePresetWallpaper = activeWallpaper === "custom" ? undefined : wallpapers.find((item) => item.id === activeWallpaper);
  const effectiveWallpaperMotion: WallpaperMotionMode = reducedMotion ? "still" : wallpaperMotionMode;
  const shot = wallpaperShots[wallpaperShot % wallpaperShots.length];
  const shotStrength = wallpaperMotionStrength / 100;
  const wallpaperCameraStyle = {
    "--wallpaper-camera-x": `${shot.x * shotStrength}%`,
    "--wallpaper-camera-y": `${shot.y * shotStrength}%`,
    "--wallpaper-camera-scale": `${1 + (shot.scale - 1) * shotStrength}`,
  } as CSSProperties;
  const activeAgentEvents = activeAgentJob ? jobEvents[activeAgentJob.id] ?? [] : [];
  const activeAgentLogs = activeAgentJob ? jobLogTails[activeAgentJob.id] ?? {} : {};
  const activeManualReviewDraft = activeAgentJob ? manualReviewDrafts[activeAgentJob.id] ?? { note: "", checks: [] } : { note: "", checks: [] };
  const activeManualReviewOptions = reviewOptionsFor(activeAgentJob);

  return (
    <main
      className={`app-shell theme-${activeWallpaper}`}
      style={
        {
          "--wallpaper-brightness": `${wallpaperBrightness}%`,
          "--wallpaper-blur": `${wallpaperBlur}px`,
          "--wallpaper-vignette": `${wallpaperVignette / 100}`,
          "--workspace-opacity": `${workspaceOpacity / 100}`,
        } as CSSProperties
      }
      onPointerMove={controlWallpaperPointer}
      onPointerLeave={resetWallpaperPointer}
    >
      <div className="wallpaper" aria-hidden="true">
        <div className={`wallpaper-camera motion-${effectiveWallpaperMotion}`} style={wallpaperCameraStyle}>
        <AnimatePresence>
          {activeWallpaper === "blossom" ? (
            <motion.video
              key="default-blossom"
              className="custom-wallpaper-layer custom-wallpaper-video"
              src={DEFAULT_WALLPAPER_URL}
              poster={DEFAULT_WALLPAPER_POSTER_URL}
              autoPlay={!reducedMotion}
              loop
              muted
              playsInline
              initial={reducedMotion ? false : { opacity: 0, scale: 1.02 }}
              animate={{ opacity: 1, scale: 1 }}
              exit={reducedMotion ? undefined : { opacity: 0, scale: 1.02 }}
              transition={{ duration: 0.55 }}
            />
          ) : customWallpaper && activeWallpaper === "custom" ? (
            customWallpaper.kind === "video" ? (
              <motion.video
                className="custom-wallpaper-layer custom-wallpaper-video"
                src={customWallpaper.url}
                autoPlay={!reducedMotion}
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
          ) : activePresetWallpaper?.assetUrl ? (
            <motion.div
              key={activePresetWallpaper.id}
              className="custom-wallpaper-layer preset-wallpaper-layer"
              style={{ backgroundImage: `url("${activePresetWallpaper.assetUrl}")` }}
              initial={reducedMotion ? false : { opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={reducedMotion ? undefined : { opacity: 0 }}
              transition={{ duration: 0.7 }}
            />
          ) : null}
        </AnimatePresence>
        </div>
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

          <div className="sidebar-project-head">
            <span>当前项目</span>
            <strong>{recentProjectPath ? displayNameFromPath(recentProjectPath) : "未命名项目"}</strong>
            <button type="button" onClick={() => setActiveTab("model")}>
              <FilePlus size={16} weight="bold" />
              新建任务
            </button>
          </div>

          <nav className="project-sequence" aria-label="项目任务序列">
            <span className="sidebar-label">任务</span>
            {recentJobs.length ? recentJobs.map((job) => (
              <button
                type="button"
                className={activeAgentJob?.id === job.id ? "project-sequence-item active" : "project-sequence-item"}
                key={job.id}
                onClick={() => {
                  setActiveAgentJobId(job.id);
                  setExpandedJobId(job.id);
                  setActiveTab("project");
                }}
              >
                <i className={job.status} />
                <span>
                  <strong>{jobDisplayTitle(job)}</strong>
                  <small>{jobStatusLabel(job.status)} · {job.progress}%</small>
                </span>
              </button>
            )) : (
              <div className="sidebar-empty">发送第一条需求后，任务会按时间排列在这里。</div>
            )}
          </nav>

          <div className="local-chip">
            <ShieldCheck size={18} weight="duotone" />
            <span>产物默认保存到本机</span>
          </div>
        </aside>

        <section className="main-window liquid">
          <header className="window-bar app-toolbar">
            <div className="project-title">
              <strong>{currentPage.title}</strong>
              <span>{recentProjectPath ? `${displayNameFromPath(recentProjectPath)} · 规范库 GB/T` : "本地工作区 · 规范库 GB/T"}</span>
              <small>{windowHint}</small>
            </div>
            <div className="top-menu" role="toolbar" aria-label="工作区导航">
              <button type="button" onClick={chooseProjectFile} title="导入 CAD、图纸或草图文件">
                <FilePlus size={15} weight="bold" />
                导入
              </button>
              {navItems.map(([key, label]) => (
                <button type="button" aria-pressed={activeTab === key} className={activeTab === key ? "active" : ""} key={key} onClick={() => setActiveTab(key)}>
                  {label.replace(/^\d+\s*/, "")}
                </button>
              ))}
            </div>
            <div className="toolbar-actions">
              <motion.button className="icon-button" onClick={() => setAppearanceOpen((value) => !value)} whileHover={reducedMotion ? undefined : { y: -2 }} whileTap={{ scale: 0.96 }}>
                <Aperture size={18} weight="duotone" />
                <span>外观</span>
              </motion.button>
              <motion.button className="icon-button" aria-label="打开设置" title="设置" onClick={() => setActiveTab("settings")} whileHover={reducedMotion ? undefined : { y: -2 }} whileTap={{ scale: 0.96 }}>
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
                        <span className="tile-preview" style={wallpaper.assetUrl ? { backgroundImage: `url("${wallpaper.assetUrl}")` } : undefined} />
                        <strong>{wallpaper.name}</strong>
                        <small>{wallpaper.hint}</small>
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
                  <div className="wallpaper-motion-grid" role="radiogroup" aria-label="壁纸动态方式">
                    {(Object.keys(wallpaperMotionLabels) as WallpaperMotionMode[]).map((mode) => (
                      <button
                        type="button"
                        role="radio"
                        aria-checked={wallpaperMotionMode === mode}
                        className={wallpaperMotionMode === mode ? "active" : ""}
                        key={mode}
                        onClick={() => setWallpaperMotionMode(mode)}
                      >
                        {wallpaperMotionLabels[mode]}
                      </button>
                    ))}
                    <button type="button" className="wallpaper-shot-button" onClick={() => setWallpaperShot((shotIndex) => (shotIndex + 1) % wallpaperShots.length)}>
                      <Aperture size={15} weight="duotone" />
                      换个特写
                    </button>
                  </div>
                  <div className="wallpaper-controls">
                    <div className="panel-opacity-presets" role="group" aria-label="界面遮罩预设">
                      <button type="button" className={workspaceOpacity <= 30 ? "active" : ""} onClick={() => setWorkspaceOpacity(24)}>穿透</button>
                      <button type="button" className={workspaceOpacity > 30 && workspaceOpacity < 66 ? "active" : ""} onClick={() => setWorkspaceOpacity(46)}>平衡</button>
                      <button type="button" className={workspaceOpacity >= 66 ? "active" : ""} onClick={() => setWorkspaceOpacity(78)}>专注</button>
                    </div>
                    <label>
                      <span>动态幅度</span>
                      <input type="range" min="0" max="100" value={wallpaperMotionStrength} onChange={(event) => setWallpaperMotionStrength(Number(event.target.value))} />
                    </label>
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
                    <label>
                      <span>界面遮罩 <output>{workspaceOpacity}%</output></span>
                      <input type="range" min="18" max="92" value={workspaceOpacity} onChange={(event) => setWorkspaceOpacity(Number(event.target.value))} />
                    </label>
                  </div>
                </motion.div>
              ) : null}
            </AnimatePresence>
          </header>

          {renderWorkspacePanel()}

          {["project", "model", "holes", "drawing"].includes(activeTab) ? (
            <>
          {["model", "holes", "drawing"].includes(activeTab) ? (
          <section className="codex-bridge">
            <div className="bridge-copy">
              <p className="eyebrow">AGENT BRIDGE</p>
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
                  <button type="button" aria-pressed={codexConfig.realCutouts} className={codexConfig.realCutouts ? "toggle-pill active" : "toggle-pill"} onClick={() => updateCodexConfig({ realCutouts: !codexConfig.realCutouts })}>
                    真实开孔
                  </button>
                  <button type="button" aria-pressed={codexConfig.strictGbDrawing} className={codexConfig.strictGbDrawing ? "toggle-pill active" : "toggle-pill"} onClick={() => updateCodexConfig({ strictGbDrawing: !codexConfig.strictGbDrawing })}>
                    严格图纸规范
                  </button>
                  <button type="button" aria-pressed={codexConfig.localCadAutomation} className={codexConfig.localCadAutomation ? "toggle-pill active" : "toggle-pill"} onClick={() => updateCodexConfig({ localCadAutomation: !codexConfig.localCadAutomation })}>
                    本机 CAD 自动化
                  </button>
                </div>
              </section>
            </div>

            <div className="bridge-runtime">
              <div className="runtime-line">
                <span>Executor</span>
                <strong>{agentProviderCatalog[apiConfig.agentProvider].name}</strong>
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
              <div className="runtime-line orchestration-line">
                <span>工程编排</span>
                <strong>AI 自动选路 · 阶段复核</strong>
              </div>
              <div className="prompt-preview">
                <span>执行计划预览</span>
                <p>{codexPrompt}</p>
              </div>
              <motion.button className="primary-button bridge-run shine" onClick={enqueueCodexTask} whileHover={reducedMotion ? undefined : { y: -2 }} whileTap={{ scale: 0.975 }}>
                <Lightning size={18} weight="duotone" />
                交给 {agentProviderCatalog[apiConfig.agentProvider].name} 执行
              </motion.button>
            </div>
          </section>
          ) : null}

          <footer className="status-strip">
            <div className="desktop-statusbar" aria-live="polite">
              <span className={selectedProvider?.ready ? "ready" : "warning"}>{agentProviderCatalog[apiConfig.agentProvider].name} {selectedProvider?.ready ? "已连接" : "未确认"}</span>
              <span>Worker {workerStatus.running ? `运行中 · ${workerStatus.pid ?? "-"}` : "未启动"}</span>
              <span>SolidWorks {runtimeHealth?.solidworks?.ok ? "可用" : "待检查"}</span>
              <span>AutoCAD {runtimeHealth?.autocad?.ok ? "可用" : "未检测到"}</span>
              <span>{queueLoaded ? queueSummary : "队列加载中"}</span>
            </div>

            <section className="agent-console" aria-live="polite">
              <div className="agent-head">
                <div>
                  <p className="eyebrow">AI EXECUTION CHAT</p>
                  <h2>AI 执行对话</h2>
                </div>
                <span>{activeAgentJob ? `${jobStatusLabel(activeAgentJob.status)} · ${activeAgentJob.progress}%` : "等待指令"}</span>
              </div>

              <div className={activeAgentJob ? "agent-body" : "agent-body single"}>
                <div className="chat-thread" aria-label="AI 执行对话记录">
                  {agentMessages.length === 0 ? (
                    <div className="chat-empty">
                      <ChatCircleText size={20} weight="duotone" />
                      <strong>CAD Agent 已就绪</strong>
                    </div>
                  ) : agentMessages.map((message) => (
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

                {activeAgentJob ? <div className="agent-live-panel">
                  <div className="live-head">
                    <ChatCircleText size={18} weight="duotone" />
                    <strong>{activeAgentJob ? jobDisplayTitle(activeAgentJob) : "等待第一条任务"}</strong>
                    <span>{activeAgentJob ? jobStatusLabel(activeAgentJob.status) : "待命"}</span>
                  </div>
                  <div className="live-progress">
                    <i style={{ width: `${activeAgentJob?.progress ?? 0}%` }} />
                  </div>
                  <div className="live-summary">
                    <p>{activeAgentJob ? compactJobMessage(activeAgentJob, activeAgentEvents) : "输入你的要求后，这里会显示 AI 的公开执行过程、工具结果和输出文件。"}</p>
                  </div>
                  {activeAgentJob.result?.engineeringPlan?.phases?.length ? (
                    <div className="engineering-plan-view">
                      <strong>AI 工程路径</strong>
                      <div>
                        {activeAgentJob.result.engineeringPlan.phases.map((phase, index) => (
                          <span className={phase.human_gate ? "human-gate" : ""} key={phase.id || `${phase.name}-${index}`}>
                            <i>{index + 1}</i>
                            {phase.name || phase.id}
                          </span>
                        ))}
                      </div>
                    </div>
                  ) : null}
                  {activeAgentJob?.status === "approval_required" ? (
                    <button className="approval-button" type="button" onClick={() => void approveJob(activeAgentJob.id)}>
                      批准本机执行
                    </button>
                  ) : null}
                  {activeAgentJob?.status === "review_required" ? (
                    <div className="manual-review-form">
                      <strong>人工复核记录</strong>
                      <div className="manual-review-checks">
                        {activeManualReviewOptions.map(([key, label]) => (
                          <label className="manual-review-check" key={key}>
                            <input
                              type="checkbox"
                              checked={activeManualReviewDraft.checks.includes(key)}
                              onChange={(event) => updateManualReviewDraft(activeAgentJob.id, {
                                checks: event.target.checked
                                  ? [...activeManualReviewDraft.checks, key]
                                  : activeManualReviewDraft.checks.filter((item) => item !== key),
                              })}
                            />
                            <span>{label}</span>
                          </label>
                        ))}
                      </div>
                      <textarea
                        value={activeManualReviewDraft.note}
                        onChange={(event) => updateManualReviewDraft(activeAgentJob.id, { note: event.target.value })}
                        placeholder="填写实际检查结果、发现的问题或放行依据"
                      />
                      <div className="review-action-row">
                        <button className="approval-button" type="button" onClick={() => void reviewJob(activeAgentJob.id, true)}>
                          通过复核
                        </button>
                        <button className="review-reject-button" type="button" onClick={() => void reviewJob(activeAgentJob.id, false)}>
                          驳回
                        </button>
                      </div>
                    </div>
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
                </div> : null}
              </div>

              <div className="agent-input-row">
                <textarea
                  value={agentInput}
                  onChange={(event) => setAgentInput(event.target.value)}
                  onKeyDown={(event) => {
                    if ((event.ctrlKey || event.metaKey) && event.key === "Enter") void submitAgentMessage();
                  }}
                  placeholder="例如：把这个外壳的 USB 口改大 1mm，并重新导出 STL 和国标 PDF 图纸"
                />
                <button type="button" onClick={() => void submitAgentMessage()}>
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
                  {workerStatus.running ? (
                    <button type="button" disabled={workerAction !== null} onClick={() => void restartLocalWorker()} title="停止并重新启动本地执行器">
                      <ArrowClockwise className={workerAction === "restart" ? "spin" : undefined} size={15} weight="bold" />
                      {workerAction === "restart" ? "重启中" : "重启执行器"}
                    </button>
                  ) : null}
                  <button type="button" disabled={workerAction !== null} onClick={() => void (workerStatus.running ? stopLocalWorker() : startLocalWorker())}>
                    {workerAction === "start" ? "启动中" : workerAction === "stop" ? "停止中" : workerStatus.running ? "停止" : "启动"}
                  </button>
                  <span>{queueLoaded ? queueSummary : "加载中"}</span>
                </div>
              </div>
              <div className="queue-list">
                {jobs.length === 0 ? (
                  <div className="queue-empty">
                    <Sparkle size={19} weight="duotone" />
                    <span>发送 AI 对话或点击任务模板后，执行任务会出现在这里。</span>
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
                            <strong>{jobDisplayTitle(job)}</strong>
                            <small>{compactJobMessage(job, events)}</small>
                          </div>
                          <span>{jobStatusLabel(job.status)}</span>
                        </div>
                        <div className="job-progress" aria-label={`${jobDisplayTitle(job)} 进度 ${job.progress}%`}>
                          <i style={{ width: `${job.progress}%` }} />
                        </div>
                        <div className="job-controls">
                          <button className="expand-button" type="button" onClick={() => setExpandedJobId(expanded ? null : job.id)}>
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
                          {job.status === "review_required" ? (
                            <button type="button" onClick={() => {
                              setActiveAgentJobId(job.id);
                              setExpandedJobId(job.id);
                            }}>
                              填写复核
                            </button>
                          ) : null}
                          {job.status === "failed" ? (
                            <button type="button" disabled={retryingJobId !== null} onClick={() => void retryJob(job.id)}>
                              <ArrowClockwise className={retryingJobId === job.id ? "spin" : undefined} size={15} weight="bold" />
                              {retryingJobId === job.id ? "重新排队中" : "重新执行"}
                            </button>
                          ) : null}
                          {job.status === "queued" || job.status === "running" || job.status === "approval_required" ? (
                            <button type="button" onClick={() => void cancelJob(job.id)}>
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
                                  <strong>Agent 输出尾部</strong>
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

          </footer>
            </>
          ) : null}
        </section>
      </motion.section>
    </main>
  );
}

export default App;
