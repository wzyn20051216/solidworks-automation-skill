import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import {
  ArrowsOutSimple,
  CaretDown,
  CheckCircle,
  WarningCircle,
} from "@phosphor-icons/react";
import { AnimatePresence, motion } from "motion/react";
import { useEffect, useMemo, useState } from "react";
import type { AutomationJob, QueueEvent } from "../types";
import { demoEvents, demoJob } from "./liveFixtures";
import { deriveLiveVisual } from "./visualState";
import { Mascot } from "./Mascot";
import "./live-hud.css";

const DEMO = new URLSearchParams(location.search).get("demo");
const HUD_STATUSES = [
  "running",
  "review_required",
  "approval_required",
  "queued",
  "passed",
  "failed",
  "blocked",
  "cancelled",
];

function activeJob(jobs: AutomationJob[]) {
  const rank = (job: AutomationJob) => HUD_STATUSES.indexOf(job.status);
  return [...jobs]
    .filter((job) => HUD_STATUSES.includes(job.status))
    .sort((a, b) => rank(a) - rank(b) || b.updatedAt.localeCompare(a.updatedAt))[0];
}

export function LiveHud() {
  const [collapsed, setCollapsed] = useState(false);
  const [job, setJob] = useState<AutomationJob | undefined>(
    DEMO ? demoJob : undefined,
  );
  const [events, setEvents] = useState<QueueEvent[]>(DEMO ? demoEvents : []);
  const [frameUrl, setFrameUrl] = useState<string>();
  const [loadError, setLoadError] = useState("");

  async function load() {
    if (DEMO) return;
    try {
      const jobs = await invoke<AutomationJob[]>("read_queue_jobs");
      const selected = activeJob(jobs);
      setJob(selected);
      setLoadError("");
      if (!selected) {
        setEvents([]);
        return;
      }
      const nextEvents = await invoke<QueueEvent[]>("read_queue_events", {
        id: selected.id,
      });
      setEvents(nextEvents);
    } catch (error) {
      setLoadError(String(error));
    }
  }

  useEffect(() => {
    void load();
    if (DEMO) return;
    let timer: number | undefined;
    let unlisten: (() => void) | undefined;
    void listen("queue-changed", () => {
      window.clearTimeout(timer);
      timer = window.setTimeout(() => void load(), 80);
    }).then((dispose) => {
      unlisten = dispose;
    });
    return () => {
      window.clearTimeout(timer);
      unlisten?.();
    };
  }, []);

  const visual = useMemo(
    () => (job ? deriveLiveVisual(job, events) : undefined),
    [job, events],
  );

  useEffect(() => {
    if (!job || !visual?.snapshotPath || DEMO) {
      setFrameUrl(undefined);
      return;
    }
    const fileName = visual.snapshotPath.split(/[\\/]/).at(-1);
    if (!fileName) return;
    let disposed = false;
    void invoke<ArrayBuffer>("read_live_visual_frame", {
      id: job.id,
      fileName,
    })
      .then((bytes) => {
        if (disposed) return;
        const type = /\.jpe?g$/i.test(fileName) ? "image/jpeg" : "image/png";
        const url = URL.createObjectURL(new Blob([bytes], { type }));
        setFrameUrl((previous) => {
          if (previous) URL.revokeObjectURL(previous);
          return url;
        });
      })
      .catch((error) => {
        if (!disposed) setLoadError(String(error));
      });
    return () => {
      disposed = true;
    };
  }, [job?.id, visual?.snapshotPath]);

  if (!job || !visual) {
    return (
      <main className="live-hud empty" aria-live="polite">
        <Mascot status={loadError ? "warning" : "thinking"} />
        <section>
          <strong>{loadError ? "桌宠连接异常" : "等待可视化任务"}</strong>
          {loadError ? (
            <span>{loadError}</span>
          ) : (
            <span>
              提交任务后
              <br />
              同步真实 SolidWorks 步骤
            </span>
          )}
        </section>
      </main>
    );
  }

  if (collapsed) {
    return (
      <button
        className={`live-hud collapsed status-${visual.status}`}
        type="button"
        onClick={() => setCollapsed(false)}
        aria-label="展开可视化桌宠"
      >
        <Mascot status={visual.status} />
        <span>{visual.progress}%</span>
      </button>
    );
  }

  return (
    <main
      className={`live-hud status-${visual.status}`}
      aria-live="polite"
    >
      <header data-tauri-drag-region>
        <span>LIVE CAD</span>
        <strong>{job.title}</strong>
        <button
          type="button"
          onClick={() => setCollapsed(true)}
          title="收起桌宠"
          aria-label="收起桌宠"
        >
          <CaretDown size={16} />
        </button>
      </header>
      <div className="live-hud-body">
        <Mascot status={visual.status} />
        <section className="live-hud-copy">
          <div className="live-bubble">
            <strong>{visual.title}</strong>
            <p>{loadError || visual.message || "正在等待下一步"}</p>
          </div>
          <div className="live-progress-bar">
            <i style={{ width: `${visual.progress}%` }} />
          </div>
          <div className="live-step-line">
            <span>{visual.phase.toUpperCase()}</span>
            <small>STEP {String(visual.sequence).padStart(2, "0")}</small>
            <small>{visual.progress}%</small>
          </div>
        </section>
        <AnimatePresence>
          {frameUrl ? (
            <motion.img
              className="live-snapshot"
              src={frameUrl}
              alt="SolidWorks 当前步骤快照"
              initial={{ opacity: 0, scale: 0.96 }}
              animate={{ opacity: 1, scale: 1 }}
              exit={{ opacity: 0 }}
            />
          ) : (
            <div className="live-snapshot-placeholder" aria-hidden="true">
              <ArrowsOutSimple size={18} />
            </div>
          )}
        </AnimatePresence>
      </div>
      <footer>
        {visual.status === "complete" ? (
          <CheckCircle size={16} weight="fill" />
        ) : null}
        {visual.status === "warning" ? (
          <WarningCircle size={16} weight="fill" />
        ) : null}
        <span>
          {visual.stats.volumeMm3
            ? `${visual.stats.volumeMm3.toFixed(1)} mm³`
            : "CAD 执行中"}
        </span>
        <span>
          {visual.stats.featureCount
            ? `${visual.stats.featureCount} 个特征`
            : ""}
        </span>
        <span className="live-state-label">
          {visual.status === "thinking"
            ? "整理步骤"
            : visual.status === "working"
              ? "SolidWorks 执行"
              : visual.status === "checking"
                ? "复核中"
                : visual.status === "complete"
                  ? "已完成"
                  : "需处理"}
        </span>
      </footer>
    </main>
  );
}
