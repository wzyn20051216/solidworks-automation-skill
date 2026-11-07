import {
  ArrowRight,
  CheckCircle,
  CircleNotch,
  Cube,
  FileText,
  PencilSimpleLine,
  Ruler,
  WarningCircle,
} from "@phosphor-icons/react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { readPersistedState, writePersistedState } from "../persistence";
import type { AutomationJob } from "../types";
import {
  PIPELINE_STAGE_META,
  PIPELINE_STAGE_ORDER,
  canRunStage,
  createEmptyPipeline,
  pipelineProgress,
  resolveStageState,
  summarizeRequirement,
  type PipelineJobLookup,
  type PipelineStageKey,
  type PipelineStageState,
  type ProjectPipeline,
  type RequirementSpec,
} from "../domain/pipeline";

const STORE_NAMESPACE = "project_pipeline";
const LEGACY_KEY = "cad-studio.project-pipeline";

const STAGE_ICONS = {
  requirements: PencilSimpleLine,
  summary: FileText,
  design: Cube,
  verify: CheckCircle,
  drawing: Ruler,
} as const;

const STATE_LABELS: Record<PipelineStageState, string> = {
  pending: "待开始",
  ready: "可执行",
  running: "执行中",
  passed: "已完成",
  failed: "失败",
  blocked: "待复核",
};

const SPEC_FIELDS: Array<{ key: keyof RequirementSpec; label: string; multiline?: boolean }> = [
  { key: "purpose", label: "用途与目标", multiline: true },
  { key: "dimensions", label: "外形尺寸" },
  { key: "interfaces", label: "孔位与接口" },
  { key: "material", label: "材料" },
  { key: "process", label: "制造工艺" },
  { key: "tolerance", label: "公差与配合" },
  { key: "outputs", label: "交付格式" },
];

type Props = {
  projectId: string;
  projectName: string;
  jobs: AutomationJob[];
  disabled?: boolean;
  onRunStage: (stage: PipelineStageKey, pipeline: ProjectPipeline) => Promise<string | null>;
};

function firstOpenStage(pipeline: ProjectPipeline, jobs: PipelineJobLookup): PipelineStageKey {
  return (
    PIPELINE_STAGE_ORDER.find((stage) => resolveStageState(pipeline, stage, jobs) !== "passed") ??
    "drawing"
  );
}

/** @brief 项目工作台的五阶段流水线：需求 → 总结 → 三维 → 验证 → 工程图。 */
export function ProjectPipelinePanel({ projectId, projectName, jobs, disabled, onRunStage }: Props) {
  const storeRef = useRef<Record<string, ProjectPipeline>>({});
  const [pipeline, setPipeline] = useState<ProjectPipeline | null>(null);
  const [selectedStage, setSelectedStage] = useState<PipelineStageKey>("requirements");
  const [runningStage, setRunningStage] = useState<PipelineStageKey | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const jobLookup = useMemo<PipelineJobLookup>(() => {
    const entries = jobs.map((job) => [
      job.id,
      { status: job.status, lastMessage: job.lastMessage, result: job.result },
    ] as const);
    return Object.fromEntries(entries);
  }, [jobs]);

  const persist = useCallback(async (next: ProjectPipeline) => {
    storeRef.current[next.projectId] = next;
    setPipeline(next);
    const result = await writePersistedState(STORE_NAMESPACE, LEGACY_KEY, storeRef.current);
    if (result.degraded) setNotice("本地数据库不可用，流水线状态暂存到浏览器回退副本。");
  }, []);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      const stored = await readPersistedState(STORE_NAMESPACE, LEGACY_KEY);
      if (cancelled) return;
      const map = (stored.value ?? {}) as Record<string, ProjectPipeline>;
      storeRef.current = map;
      const existing = map[projectId];
      const next =
        existing && existing.schemaVersion === "1.0"
          ? { ...existing, projectName }
          : createEmptyPipeline(projectId, projectName);
      setPipeline(next);
      setSelectedStage(firstOpenStage(next, {}));
    })();
    return () => {
      cancelled = true;
    };
  }, [projectId, projectName]);

  const states = useMemo(() => {
    if (!pipeline) return null;
    return Object.fromEntries(
      PIPELINE_STAGE_ORDER.map((stage) => [stage, resolveStageState(pipeline, stage, jobLookup)]),
    ) as Record<PipelineStageKey, PipelineStageState>;
  }, [pipeline, jobLookup]);

  if (!pipeline || !states) {
    return (
      <section className="pipeline-panel" aria-busy="true">
        <header className="pipeline-head">
          <div>
            <p className="eyebrow">PIPELINE</p>
            <h2>从需求到工程图</h2>
          </div>
          <span className="pipeline-percent">读取中</span>
        </header>
      </section>
    );
  }

  const progress = pipelineProgress(pipeline, jobLookup);
  const selectedState = states[selectedStage];
  const gate = canRunStage(pipeline, selectedStage, jobLookup);

  function update(mutator: (current: ProjectPipeline) => ProjectPipeline) {
    const next = { ...mutator(pipeline!), updatedAt: new Date().toISOString() };
    void persist(next);
  }

  function resetDownstream(stages: ProjectPipeline["stages"], from: PipelineStageKey) {
    const reset: ProjectPipeline["stages"] = { ...stages };
    let clearing = false;
    for (const stage of PIPELINE_STAGE_ORDER) {
      if (stage === from) clearing = true;
      if (clearing) reset[stage] = { state: stage === from ? "ready" : "pending" };
    }
    return reset;
  }

  function handleSummarize() {
    const spec = summarizeRequirement(pipeline!.requirementText);
    update((current) => ({
      ...current,
      spec,
      specConfirmedAt: undefined,
      stages: {
        ...current.stages,
        requirements: { state: "passed", updatedAt: new Date().toISOString() },
        summary: { state: "ready" },
        design: { state: "pending" },
        verify: { state: "pending" },
        drawing: { state: "pending" },
      },
    }));
    setSelectedStage("summary");
    setNotice("需求已整理成结构化清单，请逐项核对后确认。");
  }

  function handleConfirmSpec() {
    const now = new Date().toISOString();
    update((current) => ({
      ...current,
      specConfirmedAt: now,
      stages: {
        ...current.stages,
        summary: { state: "passed", updatedAt: now },
        design: { state: "ready" },
      },
    }));
    setSelectedStage("design");
    setNotice("需求已确认，可以开始三维设计。");
  }

  function handleSpecChange(key: keyof RequirementSpec, value: string) {
    update((current) => ({
      ...current,
      spec: current.spec ? { ...current.spec, [key]: value } : current.spec,
      specConfirmedAt: undefined,
      stages: resetDownstream(current.stages, "design"),
    }));
    setNotice("需求已修改，确认状态和下游阶段已失效，请重新确认。");
  }

  async function handleRunStage(stage: PipelineStageKey) {
    if (!canRunStage(pipeline!, stage, jobLookup).ok) return;
    setRunningStage(stage);
    setNotice(null);
    try {
      const jobId = await onRunStage(stage, pipeline!);
      if (!jobId) {
        setNotice("任务没有进入队列，阶段保持未开始。");
        return;
      }
      update((current) => ({
        ...current,
        stages: {
          ...current.stages,
          [stage]: { state: "running", jobId, updatedAt: new Date().toISOString() },
        },
      }));
      setNotice(`${PIPELINE_STAGE_META[stage].label}已进入本地队列。`);
    } catch (error) {
      setNotice(`${PIPELINE_STAGE_META[stage].label}启动失败：${String(error)}`);
    } finally {
      setRunningStage(null);
    }
  }

  const linkedJobId = pipeline.stages[selectedStage].jobId;
  const linkedJob = linkedJobId ? jobLookup[linkedJobId] : undefined;
  const stageAction = PIPELINE_STAGE_META[selectedStage].action;

  return (
    <section className="pipeline-panel">
      <header className="pipeline-head">
        <div>
          <p className="eyebrow">PIPELINE</p>
          <h2>从需求到工程图</h2>
          <span className="pipeline-sub">说需求 · 需求总结 · 三维设计 · 验证 · 工程图</span>
        </div>
        <strong className="pipeline-percent">{progress}%</strong>
      </header>

      <div className="pipeline-progress" role="progressbar" aria-valuenow={progress} aria-valuemin={0} aria-valuemax={100}>
        <span style={{ width: `${progress}%` }} />
      </div>

      <ol className="pipeline-rail">
        {PIPELINE_STAGE_ORDER.map((stage, index) => {
          const Icon = STAGE_ICONS[stage];
          const state = states[stage];
          return (
            <li key={stage}>
              <button
                type="button"
                className={`pipeline-step stage-${state}${selectedStage === stage ? " selected" : ""}`}
                onClick={() => setSelectedStage(stage)}
                aria-current={selectedStage === stage ? "step" : undefined}
              >
                <span className="pipeline-step-index">{String(index + 1).padStart(2, "0")}</span>
                <Icon size={17} weight="duotone" />
                <strong>{PIPELINE_STAGE_META[stage].label}</strong>
                <small>{STATE_LABELS[state]}</small>
                {state === "passed" ? <CheckCircle size={14} weight="fill" className="pipeline-step-badge" /> : null}
                {state === "running" ? <CircleNotch size={14} className="pipeline-step-badge spin" /> : null}
                {state === "blocked" || state === "failed" ? (
                  <WarningCircle size={14} weight="fill" className="pipeline-step-badge" />
                ) : null}
              </button>
            </li>
          );
        })}
      </ol>

      <article className="pipeline-stage-card">
        <div className="pipeline-stage-head">
          <div>
            <h3>{PIPELINE_STAGE_META[selectedStage].label}</h3>
            <p>{PIPELINE_STAGE_META[selectedStage].detail}</p>
          </div>
          <span className={`pipeline-chip stage-${selectedState}`}>{STATE_LABELS[selectedState]}</span>
        </div>

        {selectedStage === "requirements" ? (
          <div className="pipeline-body">
            <label className="pipeline-field">
              <span>需求描述</span>
              <textarea
                value={pipeline.requirementText}
                onChange={(event) => update((current) => ({ ...current, requirementText: event.target.value }))}
                placeholder="例如：做一个 120×80×12 的 6061 安装板，四角各一个 Ø9 通孔，孔心距边 15 mm，CNC 加工，出 DWG 和 PDF。"
                rows={7}
              />
            </label>
            <footer className="pipeline-actions">
              <span>{pipeline.requirementText.trim().length} 字</span>
              <button
                type="button"
                className="pipeline-primary"
                disabled={!canRunStage(pipeline, "summary").ok}
                onClick={handleSummarize}
              >
                {stageAction}
                <ArrowRight size={15} />
              </button>
            </footer>
          </div>
        ) : null}

        {selectedStage === "summary" ? (
          <div className="pipeline-body">
            {pipeline.spec ? (
              <>
                <div className="pipeline-spec-grid">
                  {SPEC_FIELDS.map((field) => (
                    <label key={field.key} className={`pipeline-field${field.multiline ? " wide" : ""}`}>
                      <span>{field.label}</span>
                      {field.multiline ? (
                        <textarea
                          value={String(pipeline.spec?.[field.key] ?? "")}
                          rows={3}
                          onChange={(event) => handleSpecChange(field.key, event.target.value)}
                        />
                      ) : (
                        <input
                          value={String(pipeline.spec?.[field.key] ?? "")}
                          onChange={(event) => handleSpecChange(field.key, event.target.value)}
                        />
                      )}
                    </label>
                  ))}
                </div>
                {pipeline.spec.openQuestions.length > 0 ? (
                  <ul className="pipeline-questions">
                    {pipeline.spec.openQuestions.map((question) => (
                      <li key={question}>{question}</li>
                    ))}
                  </ul>
                ) : null}
                <footer className="pipeline-actions">
                  <span>{pipeline.specConfirmedAt ? `已确认 ${new Date(pipeline.specConfirmedAt).toLocaleString("zh-CN")}` : "尚未确认"}</span>
                  <button
                    type="button"
                    className="pipeline-primary"
                    disabled={Boolean(pipeline.specConfirmedAt)}
                    onClick={handleConfirmSpec}
                  >
                    {pipeline.specConfirmedAt ? "已确认" : stageAction}
                    <CheckCircle size={15} />
                  </button>
                </footer>
              </>
            ) : (
              <p className="pipeline-empty">还没有需求总结。回到「说需求」生成。</p>
            )}
          </div>
        ) : null}

        {selectedStage === "design" || selectedStage === "verify" || selectedStage === "drawing" ? (
          <div className="pipeline-body">
            <dl className="pipeline-stage-facts">
              <div>
                <dt>阶段状态</dt>
                <dd>{STATE_LABELS[selectedState]}</dd>
              </div>
              <div>
                <dt>关联任务</dt>
                <dd>{linkedJobId ?? "尚未创建"}</dd>
              </div>
              <div>
                <dt>准入条件</dt>
                <dd>{gate.ok ? "满足" : gate.reason}</dd>
              </div>
            </dl>
            {linkedJob?.lastMessage || linkedJob?.result?.message ? (
              <pre className="pipeline-log">{(linkedJob.result?.message ?? linkedJob.lastMessage ?? "").slice(-1200)}</pre>
            ) : null}
            <footer className="pipeline-actions">
              <span>{gate.ok ? "可以执行" : gate.reason}</span>
              <button
                type="button"
                className="pipeline-primary"
                disabled={disabled || !gate.ok || runningStage !== null || selectedState === "running"}
                onClick={() => void handleRunStage(selectedStage)}
              >
                {runningStage === selectedStage ? <CircleNotch size={15} className="spin" /> : null}
                {selectedState === "passed" ? "重新执行" : stageAction}
                <ArrowRight size={15} />
              </button>
            </footer>
          </div>
        ) : null}
      </article>

      {notice ? <p className="pipeline-notice">{notice}</p> : null}
    </section>
  );
}
