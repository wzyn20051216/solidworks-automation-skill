import {
  Aperture,
  Archive,
  CheckCircle,
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
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { type CSSProperties, type ChangeEvent, type DragEvent, useEffect, useMemo, useRef, useState } from "react";

type StageState = "ready" | "running" | "passed" | "attention";
type PresetWallpaperId = "aurora" | "blueprint" | "studio" | "mist";
type WallpaperId = PresetWallpaperId | "custom";
type WallpaperFile = { url: string; name: string; kind: "image" | "video" };

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

function stateLabel(state: StageState) {
  if (state === "passed") return "通过";
  if (state === "running") return "执行中";
  if (state === "attention") return "注意";
  return "待执行";
}

function App() {
  const [activeTab, setActiveTab] = useState("project");
  const [activeWallpaper, setActiveWallpaper] = useState<WallpaperId>("aurora");
  const [customWallpaper, setCustomWallpaper] = useState<WallpaperFile | null>(null);
  const [appearanceOpen, setAppearanceOpen] = useState(false);
  const [wallpaperBrightness, setWallpaperBrightness] = useState(94);
  const [wallpaperBlur, setWallpaperBlur] = useState(3);
  const [wallpaperVignette, setWallpaperVignette] = useState(18);
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

  function runPreview() {
    setIsRunning(true);
    window.setTimeout(() => setIsRunning(false), 2200);
  }

  function useWallpaperFile(file?: File) {
    if (!file) return;
    const isImage = file.type.startsWith("image/");
    const isVideo = file.type.startsWith("video/");
    if (!isImage && !isVideo) return;

    setCustomWallpaper((previous) => {
      if (previous?.url) URL.revokeObjectURL(previous.url);
      return {
        url: URL.createObjectURL(file),
        name: file.name.replace(/\.[^.]+$/, ""),
        kind: isVideo ? "video" : "image",
      };
    });
    setActiveWallpaper("custom");
    setAppearanceOpen(true);
  }

  function importWallpaper(event: ChangeEvent<HTMLInputElement>) {
    useWallpaperFile(event.target.files?.[0]);
    event.target.value = "";
  }

  function dropWallpaper(event: DragEvent<HTMLButtonElement>) {
    event.preventDefault();
    useWallpaperFile(event.dataTransfer.files?.[0]);
  }

  useEffect(() => {
    return () => {
      if (customWallpaper?.url) URL.revokeObjectURL(customWallpaper.url);
    };
  }, [customWallpaper?.url]);

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
            <div className="traffic-lights" aria-hidden="true">
              <span />
              <span />
              <span />
            </div>
            <div className="project-title">
              <strong>智能外壳项目</strong>
              <span>本地工作区 · SolidWorks 已连接 · 规范库 GB/T</span>
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
                    onClick={() => wallpaperInputRef.current?.click()}
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
              <motion.button className="primary-button shine" onClick={runPreview} whileHover={reducedMotion ? undefined : { y: -2 }} whileTap={{ scale: 0.975 }}>
                <FilePlus size={18} weight="duotone" />
                新建外壳
              </motion.button>
              <motion.button className="ghost-button" whileHover={reducedMotion ? undefined : { y: -2 }} whileTap={{ scale: 0.975 }}>
                <FolderOpen size={18} weight="duotone" />
                导入模型
              </motion.button>
              <motion.button className="ghost-button" whileHover={reducedMotion ? undefined : { y: -2 }} whileTap={{ scale: 0.975 }}>
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

          <footer className="status-strip">
            <div className="metric-row">
              {[
                ["运行模式", "本地桌面", Lightning],
                ["图纸门禁", "GB/T P0", ShieldCheck],
                ["制造场景", "3D 打印", Aperture],
                ["当前壁纸", activeWallpaperName, ImageSquare],
              ].map(([label, value, Icon]) => (
                <motion.div className="metric-card" key={label as string} whileHover={reducedMotion ? undefined : { y: -2 }}>
                  <Icon size={19} weight="duotone" />
                  <span>{label as string}</span>
                  <strong>{value as string}</strong>
                </motion.div>
              ))}
            </div>

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
        <span>后续接入 Tauri / Electron：本地配置持久化、真实文件路径、系统托盘和离线自动化队列。</span>
      </div>
    </main>
  );
}

export default App;
