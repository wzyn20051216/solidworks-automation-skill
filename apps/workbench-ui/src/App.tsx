import {
  Aperture,
  Archive,
  CubeFocus,
  Export,
  FilePlus,
  FolderOpen,
  GearSix,
  Graph,
  ImageSquare,
  Layout,
  Lightning,
  Play,
  Ruler,
  ShieldCheck,
  SlidersHorizontal,
  Sparkle,
  UploadSimple,
  WarningCircle,
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
};
type CodexConfig = {
  objective: string;
  target: "shell" | "drawing" | "skill" | "package";
  expectedOutput: "cad_files" | "drawing_package" | "skill_update" | "research_report";
  process: "FDM" | "SLA" | "CNC" | "sheet_metal";
  material: "PLA" | "PETG" | "ABS" | "Al6061";
  unit: "mm";
  length: number;
  width: number;
  height: number;
  wallThickness: number;
  outputDir: string;
  strictGbDrawing: boolean;
  realCutouts: boolean;
  commitAndPush: boolean;
};
type AutomationJobKind = "create_shell" | "import_model" | "delivery_package" | "codex_task";
type AutomationJobStatus = "queued" | "running" | "passed" | "failed" | "cancelled" | "approval_required";
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
  target?: string;
  expectedOutput?: string;
  strictRules?: string[];
  capabilities?: string[];
  prompt?: string;
  cwd?: string;
  skillPath?: string;
  lastMessage?: string;
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
  error?: string;
};
type QueueEvent = {
  type?: string;
  jobId?: string;
  status?: string;
  message?: string;
  at?: string;
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

const stages: Stage[] = [
  { key: "preflight", label: "环境", state: "passed", detail: "SolidWorks COM 可用" },
  { key: "model", label: "建模", state: "ready", detail: "等待参数输入" },
  { key: "drawing", label: "图纸", state: "attention", detail: "缺少 DWG 实体复核" },
  { key: "package", label: "交付", state: "ready", detail: "STEP / STL / PDF 打包" },
];

const features = [
  { name: "安装孔 H1", spec: "4 x Φ3.4", pos: "X10 Y10, pitch 100 x 60", status: "已切除" },
  { name: "USB-C I1", spec: "10 x 4 R1", pos: "Front, X60 Y15", status: "待复核" },
  { name: "螺丝柱 B1", spec: "M3, OD7, H8", pos: "Bottom, X10 Y10", status: "已生成" },
];

const reviewItems = [
  { label: "真实开孔", state: "通过", note: "孔槽将参与实体切除" },
  { label: "壁厚检查", state: "通过", note: "最小壁厚 2.0 mm" },
  { label: "国标图纸", state: "注意", note: "缺少完整尺寸链" },
  { label: "交付清单", state: "注意", note: "等待真实导出器" },
];

const SETTINGS_KEY = "cad-studio.settings.v1";
const QUEUE_KEY = "cad-studio.queue.v1";
const APP_VERSION = "0.1.0";
const CODEX_CWD = "C:/Users/23201/.codex/skills/solidworks-automation";
const CODEX_SKILL_PATH = `${CODEX_CWD}/SKILL.md`;

const codexTargets: Record<CodexConfig["target"], string> = {
  shell: "3D 打印外壳建模",
  drawing: "国标 CAD 图纸",
  skill: "Skills 规范沉淀",
  package: "交付包整理",
};

const codexOutputs: Record<CodexConfig["expectedOutput"], string> = {
  cad_files: "SLDPRT / STEP / STL",
  drawing_package: "DWG / DXF / PDF 图纸包",
  skill_update: "Skill 更新 + GitHub 推送",
  research_report: "调研报告 / 执行建议",
};

const processLabels: Record<CodexConfig["process"], string> = {
  FDM: "FDM 3D 打印",
  SLA: "SLA 光固化",
  CNC: "CNC 加工",
  sheet_metal: "钣金",
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
  if (kind === "create_shell") return { title: "新建外壳", detail: "生成参数化壳体、开孔和基础检查任务" };
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
    config.realCutouts ? "3D 打印开孔必须是真实几何切除，不能只画线或只做外观标记。" : "如果涉及开孔，需要明确说明当前是否已真实切除。",
    config.strictGbDrawing ? "CAD 图纸必须按中国机械制图常用格式复核，尺寸链、孔表、技术要求、图框标题栏要完整。" : "图纸输出需要标明当前规范覆盖范围。",
    config.commitAndPush ? "完成后运行验证，使用中文 commit，并推送 GitHub。" : "完成后运行验证并说明未提交的原因。",
  ];

  return [
    "你是 Codex，请执行由 CAD Studio 图形化界面生成的任务。",
    "",
    `任务目标: ${config.objective}`,
    `任务类型: ${codexTargets[config.target]}`,
    `期望输出: ${codexOutputs[config.expectedOutput]}`,
    `项目/模型路径: ${projectPath || "未指定"}`,
    `制造方式: ${processLabels[config.process]}`,
    `材料: ${config.material}`,
    `单位: ${config.unit}`,
    `外形尺寸: ${config.length} x ${config.width} x ${config.height} ${config.unit}`,
    `壁厚: ${config.wallThickness} ${config.unit}`,
    `输出目录: ${config.outputDir}`,
    `Skill 路径: ${CODEX_SKILL_PATH}`,
    "",
    "强制规则:",
    ...strictRules.map((rule) => `- ${rule}`),
    "",
    "执行方式:",
    "- 优先使用 solidworks-automation skill 及其子技能。",
    "- 先检查现有文件和规范，再小步实现。",
    "- 结束时用中文说明改动、验证结果和输出位置。",
  ].join("\n");
}

function App() {
  const [activeTab, setActiveTab] = useState("project");
  const [activeWallpaper, setActiveWallpaper] = useState<WallpaperId>("aurora");
  const [customWallpaper, setCustomWallpaper] = useState<WallpaperFile | null>(null);
  const [appearanceOpen, setAppearanceOpen] = useState(false);
  const [wallpaperBrightness, setWallpaperBrightness] = useState(94);
  const [wallpaperBlur, setWallpaperBlur] = useState(3);
  const [wallpaperVignette, setWallpaperVignette] = useState(18);
  const [recentWallpapers, setRecentWallpapers] = useState<RecentWallpaper[]>([]);
  const [recentProjectPath, setRecentProjectPath] = useState<string | undefined>();
  const [settingsLoaded, setSettingsLoaded] = useState(false);
  const [queueLoaded, setQueueLoaded] = useState(false);
  const [jobs, setJobs] = useState<AutomationJob[]>([]);
  const [jobEvents, setJobEvents] = useState<Record<string, QueueEvent[]>>({});
  const [codexConfig, setCodexConfig] = useState<CodexConfig>({
    objective: "根据当前配置生成可 3D 打印的外壳，并严格检查真实开孔和图纸标注。",
    target: "shell",
    expectedOutput: "cad_files",
    process: "FDM",
    material: "PETG",
    unit: "mm",
    length: 120,
    width: 80,
    height: 35,
    wallThickness: 1.6,
    outputDir: "Documents/CADAutomationWorkbench",
    strictGbDrawing: true,
    realCutouts: true,
    commitAndPush: true,
  });
  const [isRunning, setIsRunning] = useState(false);
  const [focusFeature, setFocusFeature] = useState(0);
  const wallpaperInputRef = useRef<HTMLInputElement>(null);
  const reducedMotion = useReducedMotion();

  const visualStages = useMemo(() => {
    if (!isRunning) return stages;
    return stages.map((stage, index) => ({
      ...stage,
      state: index === 1 ? "running" : stage.state,
      detail: index === 1 ? "正在生成外壳特征" : stage.detail,
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
    const strictRules = [
      codexConfig.realCutouts ? "3D 打印开孔必须真实切除" : "明确说明开孔实现状态",
      codexConfig.strictGbDrawing ? "必须按中国机械制图常用格式复核 CAD 图纸" : "说明当前图纸规范覆盖范围",
      codexConfig.commitAndPush ? "完成验证后中文提交并推送 GitHub" : "完成验证并保留本地结果",
    ];
    const job = createJob("codex_task", recentProjectPath, {
      executor: "codex",
      title: "Codex 执行",
      detail: `${codexTargets[codexConfig.target]} · ${codexOutputs[codexConfig.expectedOutput]}`,
      objective: codexConfig.objective,
      target: codexTargets[codexConfig.target],
      expectedOutput: codexOutputs[codexConfig.expectedOutput],
      strictRules,
      capabilities: codexConfig.commitAndPush ? ["git_push"] : [],
      prompt: codexPrompt,
      cwd: CODEX_CWD,
      skillPath: CODEX_SKILL_PATH,
      policy: {
        sandbox: "workspace-write",
        approval: "never",
        requireSkillRead: true,
        requireTests: true,
        requireCommit: codexConfig.commitAndPush,
        requirePush: codexConfig.commitAndPush,
        requireReviewerPass: true,
      },
      uiConfig: {
        manufacturing: {
          process: codexConfig.process,
          processLabel: processLabels[codexConfig.process],
          material: codexConfig.material,
          unit: codexConfig.unit,
        },
        shell: {
          length: codexConfig.length,
          width: codexConfig.width,
          height: codexConfig.height,
          wallThickness: codexConfig.wallThickness,
        },
        gates: {
          realCutouts: codexConfig.realCutouts,
          strictGbDrawing: codexConfig.strictGbDrawing,
          commitAndPush: codexConfig.commitAndPush,
        },
        outputDir: codexConfig.outputDir,
      },
    });
    upsertJob(job);
    if (!isTauriRuntime()) simulateJob(job);
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

  function importWallpaper(event: ChangeEvent<HTMLInputElement>) {
    useWallpaperFile(event.target.files?.[0]);
    event.target.value = "";
  }

  function dropWallpaper(event: DragEvent<HTMLButtonElement>) {
    event.preventDefault();
    useWallpaperFile(event.dataTransfer.files?.[0]);
  }

  async function controlWindow(action: "close" | "minimize" | "maximize") {
    if (!isTauriRuntime()) return;
    const appWindow = getCurrentWindow();
    if (action === "close") await appWindow.close();
    if (action === "minimize") await appWindow.minimize();
    if (action === "maximize") await appWindow.toggleMaximize();
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
      if (settings.customWallpaperPath) setCustomWallpaper(wallpaperFromPath(settings.customWallpaperPath));
    }
    setSettingsLoaded(true);
  }, []);

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
        const eventPairs = await Promise.all(
          nextJobs.slice(0, 4).map(async (job) => [job.id, await invoke<QueueEvent[]>("read_queue_events", { id: job.id })] as const),
        );
        if (!disposed) setJobEvents(Object.fromEntries(eventPairs));
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
  }, []);

  useEffect(() => {
    setIsRunning(jobs.some((job) => job.status === "running"));
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
    };
    localStorage.setItem(SETTINGS_KEY, JSON.stringify(settings));
  }, [activeWallpaper, customWallpaper?.sourcePath, recentProjectPath, recentWallpapers, settingsLoaded, wallpaperBlur, wallpaperBrightness, wallpaperVignette]);

  const activeWallpaperName =
    activeWallpaper === "custom" ? customWallpaper?.name ?? "我的壁纸" : wallpapers.find((item) => item.id === activeWallpaper)?.name ?? "Aurora";

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
            <div className="traffic-lights" aria-label="窗口控制">
              <button type="button" aria-label="关闭窗口" onClick={() => controlWindow("close")} />
              <button type="button" aria-label="最小化窗口" onClick={() => controlWindow("minimize")} />
              <button type="button" aria-label="最大化窗口" onClick={() => controlWindow("maximize")} />
            </div>
            <div className="project-title">
              <strong>智能外壳项目</strong>
              <span>{recentProjectPath ? `${displayNameFromPath(recentProjectPath)} · SolidWorks 已连接 · 规范库 GB/T` : "本地工作区 · SolidWorks 已连接 · 规范库 GB/T"}</span>
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
              <h1>项目工作台</h1>
              <p className="subtitle">拖入草图、参数表或模型文件，生成可打印外壳、国标图纸和交付包。</p>
            </div>
            <div className="command-row">
              <motion.button className="primary-button shine" onClick={() => enqueueAutomation("create_shell", recentProjectPath)} whileHover={reducedMotion ? undefined : { y: -2 }} whileTap={{ scale: 0.975 }}>
                <FilePlus size={18} weight="duotone" />
                新建外壳
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

          <section className="content-grid workbench-grid">
            <motion.article className="preview-card" layout>
              <div className="panel-heading">
                <div>
                  <p className="eyebrow">MODEL PREVIEW</p>
                  <h2>参数化外壳草案</h2>
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
              <h2>图形化配置，Codex 执行</h2>
              <p>把按钮、选项和工程规则转换成稳定提示词，交给本机 Codex CLI 执行，结果再回写任务队列。</p>
            </div>

            <div className="bridge-controls">
              <label className="bridge-field wide">
                <span>任务目标</span>
                <textarea value={codexConfig.objective} onChange={(event) => updateCodexConfig({ objective: event.target.value })} />
              </label>

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

              <div className="bridge-field compact-inputs">
                <span>外壳参数</span>
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

              <div className="bridge-field">
                <span>输出物</span>
                <div className="segmented-control">
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

              <div className="bridge-toggles">
                <button type="button" className={codexConfig.realCutouts ? "toggle-pill active" : "toggle-pill"} onClick={() => updateCodexConfig({ realCutouts: !codexConfig.realCutouts })}>
                  真实开孔
                </button>
                <button type="button" className={codexConfig.strictGbDrawing ? "toggle-pill active" : "toggle-pill"} onClick={() => updateCodexConfig({ strictGbDrawing: !codexConfig.strictGbDrawing })}>
                  严格图纸规范
                </button>
                <button type="button" className={codexConfig.commitAndPush ? "toggle-pill active" : "toggle-pill"} onClick={() => updateCodexConfig({ commitAndPush: !codexConfig.commitAndPush })}>
                  提交并推送
                </button>
              </div>
            </div>

            <div className="bridge-runtime">
              <div className="runtime-line">
                <span>Executor</span>
                <strong>Codex CLI</strong>
              </div>
              <div className="runtime-line">
                <span>Skill</span>
                <strong>solidworks-automation</strong>
              </div>
              <div className="runtime-line">
                <span>制造输入</span>
                <strong>{`${processLabels[codexConfig.process]} · ${codexConfig.material} · ${codexConfig.length}x${codexConfig.width}x${codexConfig.height}`}</strong>
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
                ["制造场景", "3D 打印", Aperture],
                ["任务队列", queueLoaded ? queueSummary : "加载中", Graph],
              ].map(([label, value, Icon]) => (
                <motion.div className="metric-card" key={label as string} whileHover={reducedMotion ? undefined : { y: -2 }}>
                  <Icon size={19} weight="duotone" />
                  <span>{label as string}</span>
                  <strong>{value as string}</strong>
                </motion.div>
              ))}
            </div>

            <section className="queue-panel">
              <div className="queue-head">
                <div>
                  <p className="eyebrow">AUTOMATION QUEUE</p>
                  <h2>本地自动化队列</h2>
                </div>
                <span>{queueLoaded ? queueSummary : "加载中"}</span>
              </div>
              <div className="queue-list">
                {jobs.length === 0 ? (
                  <div className="queue-empty">
                    <Sparkle size={19} weight="duotone" />
                    <span>点击新建外壳、导入模型或生成交付包后，任务会出现在这里。</span>
                  </div>
                ) : (
                  jobs.slice(0, 4).map((job) => (
                    <motion.article className={`queue-job ${job.status}`} key={job.id} layout>
                      <div>
                        <strong>{job.title}</strong>
                        <small>
                          {(job.status === "approval_required" ? job.approvalReasons?.[0] : undefined) ||
                            jobEvents[job.id]?.[jobEvents[job.id].length - 1]?.message ||
                            job.lastMessage ||
                            job.result?.outputPath ||
                            job.error ||
                            job.detail}
                        </small>
                      </div>
                      <span>{jobStatusLabel(job.status)}</span>
                      <div className="job-progress" aria-label={`${job.title} 进度 ${job.progress}%`}>
                        <i style={{ width: `${job.progress}%` }} />
                      </div>
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
                    </motion.article>
                  ))
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
