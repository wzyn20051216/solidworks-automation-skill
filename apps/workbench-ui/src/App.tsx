import {
  Aperture,
  Archive,
  CheckCircle,
  CubeFocus,
  FolderOpen,
  GearSix,
  Graph,
  Layout,
  Lightning,
  Play,
  Ruler,
  ShieldCheck,
  Sparkle,
} from "@phosphor-icons/react";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { useMemo, useState } from "react";

type StageState = "ready" | "running" | "passed" | "attention";
type WallpaperId = "aurora" | "blueprint" | "studio" | "mist";

type Stage = {
  key: string;
  label: string;
  state: StageState;
  detail: string;
};

const wallpapers: Array<{ id: WallpaperId; name: string; hint: string }> = [
  { id: "aurora", name: "Aurora", hint: "柔和蓝青流光" },
  { id: "blueprint", name: "Blueprint", hint: "淡蓝工程网格" },
  { id: "studio", name: "Studio", hint: "白色摄影棚光" },
  { id: "mist", name: "Mist", hint: "晨雾玻璃质感" },
];

const navItems = [
  ["project", "首页", Layout],
  ["shell", "外壳", CubeFocus],
  ["features", "开孔", Ruler],
  ["review", "复核", ShieldCheck],
  ["output", "交付", Archive],
  ["skills", "Skills", GearSix],
] as const;

const stages: Stage[] = [
  { key: "preflight", label: "环境", state: "passed", detail: "SolidWorks COM 可用" },
  { key: "model", label: "建模", state: "ready", detail: "等待参数输入" },
  { key: "drawing", label: "图纸", state: "attention", detail: "国标门禁待复核" },
  { key: "package", label: "交付", state: "ready", detail: "STL 与 DWG 打包" },
];

const features = [
  { name: "安装孔", spec: "4 x Φ3.4", pos: "X10 Y10, pitch 100 x 60" },
  { name: "USB-C", spec: "10 x 4 R1", pos: "Front, X60 Y15" },
  { name: "螺丝柱", spec: "M3, OD7, H8", pos: "Bottom, X10 Y10" },
];

const reviewItems = [
  { label: "真实开孔", state: "通过", note: "孔槽将参与实体切除" },
  { label: "壁厚检查", state: "通过", note: "适配 3D 打印壳体" },
  { label: "国标图纸", state: "注意", note: "需接入 DWG 实体复核" },
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
  const [isRunning, setIsRunning] = useState(false);
  const [focusFeature, setFocusFeature] = useState(0);
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

  const activeWallpaperName = wallpapers.find((item) => item.id === activeWallpaper)?.name ?? "Aurora";

  return (
    <main className={`app-shell theme-${activeWallpaper}`}>
      <div className="wallpaper" aria-hidden="true">
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
                whileHover={reducedMotion ? undefined : { x: 4, scale: 1.015 }}
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
          <header className="window-bar">
            <div className="traffic-lights" aria-hidden="true">
              <span />
              <span />
              <span />
            </div>
            <div className="search-pill">
              <Sparkle size={16} weight="duotone" />
              <span>用自然语言描述外壳、开孔、图纸规范</span>
            </div>
            <div className="wallpaper-current">
              <Aperture size={16} weight="duotone" />
              <span>{activeWallpaperName}</span>
            </div>
          </header>

          <section className="hero-row">
            <motion.div
              className="hero-copy"
              initial={reducedMotion ? false : { x: -18, opacity: 0 }}
              animate={{ x: 0, opacity: 1 }}
              transition={{ duration: 0.58, delay: 0.12 }}
            >
              <p className="eyebrow">SOLIDWORKS AUTOMATION</p>
              <h1>把壳体建模、开孔和国标图纸做成好用的软件。</h1>
              <p className="subtitle">简约界面承载复杂机械流程，适合 3D 打印外壳、孔槽复核、DWG 与 STL 本地交付。</p>
              <div className="command-row">
                <motion.button className="primary-button shine" onClick={runPreview} whileHover={reducedMotion ? undefined : { y: -3, scale: 1.015 }} whileTap={{ scale: 0.975 }}>
                  <Play size={18} weight="fill" />
                  执行预览
                </motion.button>
                <motion.button className="ghost-button" whileHover={reducedMotion ? undefined : { y: -3, scale: 1.015 }} whileTap={{ scale: 0.975 }}>
                  <FolderOpen size={18} weight="duotone" />
                  打开项目
                </motion.button>
                <motion.button className="ghost-button" whileHover={reducedMotion ? undefined : { y: -3, scale: 1.015 }} whileTap={{ scale: 0.975 }}>
                  <CheckCircle size={18} weight="duotone" />
                  规范检查
                </motion.button>
              </div>
            </motion.div>

            <motion.div
              className="wallpaper-switcher"
              initial={reducedMotion ? false : { x: 18, opacity: 0 }}
              animate={{ x: 0, opacity: 1 }}
              transition={{ duration: 0.58, delay: 0.18 }}
            >
              <div className="switcher-head">
                <span>动态壁纸</span>
                <small>点击切换</small>
              </div>
              <div className="wallpaper-grid">
                {wallpapers.map((wallpaper) => (
                  <motion.button
                    className={activeWallpaper === wallpaper.id ? `wallpaper-tile ${wallpaper.id} active` : `wallpaper-tile ${wallpaper.id}`}
                    key={wallpaper.id}
                    onClick={() => setActiveWallpaper(wallpaper.id)}
                    whileHover={reducedMotion ? undefined : { y: -4, scale: 1.02 }}
                    whileTap={{ scale: 0.97 }}
                  >
                    <span className="tile-preview" />
                    <strong>{wallpaper.name}</strong>
                    <small>{wallpaper.hint}</small>
                  </motion.button>
                ))}
              </div>
            </motion.div>
          </section>

          <section className="content-grid">
            <motion.article className="preview-card" layout>
              <div className="panel-heading">
                <div>
                  <p className="eyebrow">MODEL PREVIEW</p>
                  <h2>参数化外壳草案</h2>
                </div>
                <span className={isRunning ? "status-pill running" : "status-pill"}>{isRunning ? "运行中" : "Mock"}</span>
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

            <aside className="side-stack">
              <section className="compact-card">
                <div className="panel-heading compact">
                  <div>
                    <p className="eyebrow">FEATURES</p>
                    <h2>孔槽明细</h2>
                  </div>
                  <Ruler size={22} weight="duotone" />
                </div>
                <div className="feature-tabs">
                  {features.map((feature, index) => (
                    <motion.button
                      className={focusFeature === index ? "feature-chip active" : "feature-chip"}
                      key={feature.name}
                      onClick={() => setFocusFeature(index)}
                      whileHover={reducedMotion ? undefined : { y: -2 }}
                      whileTap={{ scale: 0.97 }}
                    >
                      {feature.name}
                    </motion.button>
                  ))}
                </div>
                <AnimatePresence mode="wait">
                  <motion.div
                    className="feature-detail"
                    key={features[focusFeature].name}
                    initial={reducedMotion ? false : { opacity: 0, y: 10, filter: "blur(6px)" }}
                    animate={{ opacity: 1, y: 0, filter: "blur(0px)" }}
                    exit={reducedMotion ? undefined : { opacity: 0, y: -8, filter: "blur(6px)" }}
                    transition={{ duration: 0.22 }}
                  >
                    <strong>{features[focusFeature].spec}</strong>
                    <span>{features[focusFeature].pos}</span>
                  </motion.div>
                </AnimatePresence>
              </section>

              <section className="compact-card">
                <div className="panel-heading compact">
                  <div>
                    <p className="eyebrow">P0 GATE</p>
                    <h2>复核门禁</h2>
                  </div>
                  <ShieldCheck size={22} weight="duotone" />
                </div>
                <div className="review-list">
                  {reviewItems.map((item, index) => (
                    <motion.button
                      className={item.state === "通过" ? "review-row passed" : "review-row attention"}
                      key={item.label}
                      initial={reducedMotion ? false : { x: 12, opacity: 0 }}
                      animate={{ x: 0, opacity: 1 }}
                      transition={{ duration: 0.35, delay: index * 0.05 }}
                      whileHover={reducedMotion ? undefined : { x: 4 }}
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

          <section className="bottom-strip">
            <div className="metric-row">
              {[
                ["运行模式", "本地桌面", Lightning],
                ["图纸门禁", "GB/T P0", ShieldCheck],
                ["制造场景", "3D 打印", Aperture],
                ["当前阶段", isRunning ? "建模中" : "待执行", Graph],
              ].map(([label, value, Icon]) => (
                <motion.div className="metric-card" key={label as string} whileHover={reducedMotion ? undefined : { y: -3 }}>
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
          </section>
        </section>
      </motion.section>
    </main>
  );
}

export default App;
