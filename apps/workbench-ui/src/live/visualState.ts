import type { AutomationJob, QueueEvent } from "../types";
import type {
  LiveVisualState,
  VisualPhase,
  VisualStatus,
  VisualStep,
} from "./visualTypes";

const phases = new Set<VisualPhase>([
  "planning",
  "sketch",
  "feature",
  "assembly",
  "drawing",
  "review",
  "delivery",
]);

function phaseOf(value: unknown): VisualPhase {
  return typeof value === "string" && phases.has(value as VisualPhase)
    ? (value as VisualPhase)
    : "planning";
}

function numericStats(value: unknown) {
  if (!value || typeof value !== "object" || Array.isArray(value)) return {};
  return Object.fromEntries(
    Object.entries(value).filter((entry): entry is [string, number] => {
      return typeof entry[1] === "number" && Number.isFinite(entry[1]);
    }),
  );
}

function eventStep(event: QueueEvent): VisualStep | null {
  const data = event.data;
  if (!data || typeof data !== "object" || Array.isArray(data)) return null;
  const value = data as Record<string, unknown>;
  if (typeof value.stepId !== "string" || typeof value.title !== "string") return null;
  return {
    stepId: value.stepId,
    sequence: typeof value.sequence === "number" ? value.sequence : 0,
    phase: phaseOf(value.phase),
    title: value.title,
    message: event.message || (typeof value.message === "string" ? value.message : ""),
    snapshotPath: typeof value.snapshotPath === "string" ? value.snapshotPath : undefined,
    stats: numericStats(value.stats),
  };
}

function jobFallback(job: AutomationJob): LiveVisualState {
  const checking = job.stage === "reviewing" || job.stage === "checking";
  const status: VisualStatus =
    job.status === "passed"
      ? "complete"
      : ["failed", "blocked", "cancelled", "approval_required"].includes(job.status)
        ? "warning"
        : checking
          ? "checking"
          : job.status === "queued"
            ? "thinking"
            : "working";
  return {
    status,
    phase: checking ? "review" : job.stage === "delivery" ? "delivery" : "planning",
    title: job.lastMessage || job.title,
    message: job.lastMessage || "",
    progress: job.progress,
    sequence: 0,
    stats: {},
    steps: [],
  };
}

export function deriveLiveVisual(job: AutomationJob, events: QueueEvent[]): LiveVisualState {
  const visualEvents = events.filter((event) => event.type?.startsWith("visual."));
  const steps = visualEvents
    .map(eventStep)
    .filter((item): item is VisualStep => Boolean(item));
  const latest = steps.at(-1);
  const latestEvent = visualEvents.at(-1);
  if (!latest || !latestEvent) return jobFallback(job);

  let status: VisualStatus = "working";
  if (latestEvent.type === "visual.step.started" && latest.phase === "planning") {
    status = "thinking";
  }
  if (latest.phase === "review") status = "checking";
  if (latestEvent.type === "visual.step.failed" || latestEvent.type === "visual.session.failed") {
    status = "warning";
  }
  if (latestEvent.type === "visual.delivery.ready") {
    status = job.status === "passed" ? "complete" : "checking";
  }
  if (job.status === "passed") status = "complete";
  if (job.status === "review_required") status = "checking";
  if (["failed", "blocked", "cancelled", "approval_required"].includes(job.status)) {
    status = "warning";
  }

  return {
    status,
    phase: latest.phase,
    title: latest.title,
    message: latest.message,
    progress:
      typeof latestEvent.progress === "number" ? latestEvent.progress : job.progress,
    sequence: latest.sequence,
    snapshotPath: [...steps].reverse().find((step) => step.snapshotPath)?.snapshotPath,
    stats: Object.assign({}, ...steps.map((step) => step.stats ?? {})),
    steps,
  };
}
