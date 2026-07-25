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

type Stage = {
  key: string;
  label: string;
  state: StageState;
  detail: string;
};

const stages: Stage[] = [
  { key: "preflight", label: "环境", state: "passed", detail: "COM 依赖可用" },
  { key: "model", label: "模型", state: "ready", detail: "等待真实 CAD 引擎" },
  { key: "drawing", label: "图纸", state: "attention", detail: "P0 门禁开启" },
  { key: "package", label: "交付", state: "ready", detail: "manifest 已规划" },
];

const features = [
  { name: "安装孔 H1", spec: "4 x Φ3.4", pos: "X10 Y10, pitch 100 x 60" },
  { name: "USB-C I1", spec: "10 x 4 R1", pos: "Front, X60 Y15" },
  { name: "螺丝柱 B1", spec: "M3, OD7, H8", pos: "Bottom, X10 Y10" },
];

const reviewItems = [
  { label: "真实开孔", state: "通过", note: "参数已包含切除规格" },
  { label: "孔槽定位", state: "通过", note: "X/Y 基准完整" },
  { label: "图纸规范", state: "注意", note: "需接入 DWG 实体复核" },
  { label: "打印交付", state: "注意", note: "STL 仍为 Mock 输出" },
];

function stateLabel(state: StageState) {
  if (state === "passed") return "通过";
  if (state === "running") return "执行中";
  if (state === "attention") return "注意";
  return "待执行";
}

function App() {
  const [activeTab, setActiveTab] = useState("project");
  const [isRunning, setIsRunning] = useState(false);
  const [focusFeature, setFocusFeature] = useState(0);
  const reducedMotion = useReducedMotion();

  const visualStages = useMemo(() => {
    if (!isRunning) return stages;
    return stages.map((stage, index) => ({
      ...stage,
      state: index === 1 ? "running" : stage.state,
      detail: index === 1 ? "正在准备外壳参数" : stage.detail,
    })) as Stage[];
  }, [isRunning]);

  function runPreview() {
    setIsRunning(true);
    window.setTimeout(() => setIsRunning(false), 2200);
  }

  return (
    <main className="app-shell">
      <motion.aside
        className="sidebar"
        initial={reducedMotion ? false : { x: -28, opacity: 0 }}
        animate={{ x: 0, opacity: 1 }}
        transition={{ duration: 0.7, ease: [0.22, 1, 0.36, 1] }}
      >
        <div className="brand-block">
          <div className="brand-mark">
            <CubeFocus size={24} weight="duotone" />
          </div>
          <div>
            <h1>CAD Studio</h1>
            <p>Local automation workbench</p>
          </div>
        </div>

        <nav className="nav-stack" aria-label="主导航">
          {[
            ["project", "项目", Layout],
            ["shell", "外壳", CubeFocus],
            ["features", "孔槽", Ruler],
            ["review", "复核", ShieldCheck],
            ["output", "交付", Archive],
            ["skills", "Skills", GearSix],
          ].map(([key, label, Icon]) => (
            <button
              className={activeTab === key ? "nav-item active" : "nav-item"}
              key={key as string}
              onClick={() => setActiveTab(key as string)}
            >
              <Icon size={19} weight="duotone" />
              <span>{label as string}</span>
            </button>
          ))}
        </nav>

        <div className="privacy-note">
          <ShieldCheck size={18} weight="duotone" />
          <span>本地运行，工程文件不出电脑</span>
        </div>
      </motion.aside>

      <section className="workspace">
        <header className="topbar glass">
          <div>
            <p className="eyebrow">3D PRINT SHELL</p>
            <h2>3D 打印外壳自动交付</h2>
            <p className="subtitle">用苹果风格的本地软件界面，承载 SolidWorks 与 AutoCAD 自动化。</p>
          </div>
          <div className="command-row">
            <button className="ghost-button">
              <FolderOpen size={18} weight="duotone" />
              打开
            </button>
            <button className="ghost-button">
              <CheckCircle size={18} weight="duotone" />
              检查
            </button>
            <button className="primary-button" onClick={runPreview}>
              <Play size={18} weight="fill" />
              执行预览
            </button>
          </div>
        </header>

        <section className="summary-grid">
          {[
            ["运行模式", "本地桌面", Lightning],
            ["图纸门禁", "GB/T P0", ShieldCheck],
            ["制造场景", "3D 打印外壳", Aperture],
            ["当前阶段", isRunning ? "模型准备中" : "等待执行", Graph],
          ].map(([label, value, Icon], index) => (
            <motion.article
              className="metric-card glass"
              key={label as string}
              initial={reducedMotion ? false : { y: 16, opacity: 0 }}
              animate={{ y: 0, opacity: 1 }}
              transition={{ duration: 0.55, delay: index * 0.08 }}
            >
              <Icon size={20} weight="duotone" />
              <span>{label as string}</span>
              <strong>{value as string}</strong>
            </motion.article>
          ))}
        </section>

        <section className="content-grid">
          <motion.div className="canvas-panel glass" layout>
            <div className="panel-heading">
              <div>
                <p className="eyebrow">MODEL PREVIEW</p>
                <h3>参数化外壳草案</h3>
              </div>
              <span className="status-pill">{isRunning ? "运行中" : "Mock"}</span>
            </div>
            <div className={isRunning ? "cad-stage active" : "cad-stage"}>
              <motion.div
                className="device-body"
                animate={
                  reducedMotion
                    ? undefined
                    : {
                        rotateX: isRunning ? [58, 62, 58] : 58,
                        rotateZ: isRunning ? [-8, -5, -8] : -8,
                      }
                }
                transition={{ duration: 2.2, repeat: isRunning ? Infinity : 0 }}
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
          </motion.div>

          <motion.div className="right-stack" layout>
            <section className="review-panel glass">
              <div className="panel-heading compact">
                <div>
                  <p className="eyebrow">P0 GATE</p>
                  <h3>复核门禁</h3>
                </div>
                <Sparkle size={22} weight="duotone" />
              </div>
              <div className="review-list">
                {reviewItems.map((item, index) => (
                  <motion.button
                    className={item.state === "通过" ? "review-row passed" : "review-row attention"}
                    key={item.label}
                    initial={reducedMotion ? false : { x: 18, opacity: 0 }}
                    animate={{ x: 0, opacity: 1 }}
                    transition={{ duration: 0.45, delay: index * 0.08 }}
                  >
                    <span>{item.label}</span>
                    <strong>{item.state}</strong>
                    <small>{item.note}</small>
                  </motion.button>
                ))}
              </div>
            </section>

            <section className="feature-panel glass">
              <div className="panel-heading compact">
                <div>
                  <p className="eyebrow">FEATURES</p>
                  <h3>孔槽明细</h3>
                </div>
              </div>
              <div className="feature-tabs">
                {features.map((feature, index) => (
                  <button
                    className={focusFeature === index ? "feature-chip active" : "feature-chip"}
                    key={feature.name}
                    onClick={() => setFocusFeature(index)}
                  >
                    {feature.name}
                  </button>
                ))}
              </div>
              <AnimatePresence mode="wait">
                <motion.div
                  className="feature-detail"
                  key={features[focusFeature].name}
                  initial={reducedMotion ? false : { opacity: 0, y: 10 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={reducedMotion ? undefined : { opacity: 0, y: -10 }}
                  transition={{ duration: 0.22 }}
                >
                  <strong>{features[focusFeature].spec}</strong>
                  <span>{features[focusFeature].pos}</span>
                </motion.div>
              </AnimatePresence>
            </section>
          </motion.div>
        </section>

        <section className="pipeline glass">
          {visualStages.map((stage, index) => (
            <motion.div
              className={`stage-card ${stage.state}`}
              key={stage.key}
              initial={reducedMotion ? false : { y: 6 }}
              animate={{ y: 0 }}
              transition={{ duration: 0.28, delay: index * 0.03 }}
            >
              <span className="stage-index">{String(index + 1).padStart(2, "0")}</span>
              <strong>{stage.label}</strong>
              <small>{stateLabel(stage.state)}</small>
              <p>{stage.detail}</p>
            </motion.div>
          ))}
        </section>
      </section>
    </main>
  );
}

export default App;
