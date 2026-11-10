import type { AutomationJob, EngineeringChangeRoot, EngineeringReviewPhase, ProjectRecord, ProjectReviewInputs, ProjectStageReview } from "../types";
import { engineeringChangeRoots } from "./chatEngineeringChange";
import { jobProjectId } from "./projects";

const dimensionFields = ["length", "width", "height", "wallThickness"] as const;
const reviewFields = ["objective", ...dimensionFields] as const;

function revision(value: unknown): number {
  return typeof value === "number" && Number.isSafeInteger(value) && value >= 0 ? value : 0;
}

function validInputs(value: Partial<ProjectReviewInputs> | undefined): Partial<ProjectReviewInputs> {
  const inputs: Partial<ProjectReviewInputs> = {};
  if (typeof value?.objective === "string") inputs.objective = value.objective;
  for (const field of dimensionFields) {
    const dimension = value?.[field];
    if (typeof dimension === "number" && Number.isFinite(dimension) && dimension >= 0) inputs[field] = dimension;
  }
  return inputs;
}

export function restoreStageReview(value?: ProjectStageReview): ProjectStageReview | undefined {
  if (!value || typeof value !== "object") return undefined;
  return {
    inputs: validInputs(value.inputs),
    requirementsRevision: revision(value.requirementsRevision),
    geometryRevision: revision(value.geometryRevision),
    chatPhaseRevisions: value.chatPhaseRevisions && Object.fromEntries(engineeringChangeRoots
      .map((root) => [root, revision(value.chatPhaseRevisions?.[root])] as const)
      .filter(([, value]) => value > 0)),
  };
}

export function engineeringInputRevision(review?: ProjectStageReview): number {
  return Math.max(review?.requirementsRevision ?? 0, review?.geometryRevision ?? 0);
}

export function chatInputRevision(review?: ProjectStageReview): number {
  return Math.max(0, ...Object.values(review?.chatPhaseRevisions ?? {}));
}

export function recordChatChange(review: ProjectStageReview | undefined, submitted: number, roots: readonly EngineeringChangeRoot[]) {
  const changed = roots.filter((root) => submitted > (review?.chatPhaseRevisions?.[root] ?? 0));
  if (!changed.length) return review;
  return {
    inputs: {},
    requirementsRevision: 0,
    geometryRevision: 0,
    ...review,
    chatPhaseRevisions: {
      ...review?.chatPhaseRevisions,
      ...Object.fromEntries(changed.map((root) => [root, submitted])),
    },
  };
}

export function restoreQueuedChatChanges(projects: ProjectRecord[], jobs: AutomationJob[]): ProjectRecord[] {
  const recovered = new Map<string, ProjectStageReview>();
  for (const job of jobs) {
    const roots = job.uiConfig?.chatReviewRoots;
    if (!Array.isArray(roots)) continue;
    const projectId = jobProjectId(job);
    const review = recordChatChange(recovered.get(projectId), revision(job.uiConfig?.chatInputRevision),
      engineeringChangeRoots.filter((root) => roots.includes(root)));
    if (review) recovered.set(projectId, review);
  }
  if (!recovered.size) return projects;
  let changed = false;
  const updated = projects.map((project) => {
    const clocks = recovered.get(project.id)?.chatPhaseRevisions;
    if (!clocks) return project;
    let stageReview = project.stageReview;
    for (const root of engineeringChangeRoots) {
      stageReview = recordChatChange(stageReview, clocks[root] ?? 0, [root]);
    }
    if (stageReview === project.stageReview) return project;
    changed = true;
    return { ...project, stageReview };
  });
  return changed ? updated : projects;
}

export function updateStageReview(
  previous: ProjectStageReview | undefined,
  patch: Partial<ProjectReviewInputs>,
  defaults: ProjectReviewInputs,
): ProjectStageReview | undefined {
  const edits = validInputs(patch);
  const current = { ...defaults, ...previous?.inputs };
  const changed = reviewFields.filter((field) => {
    const next = edits[field];
    if (next === undefined) return false;
    return typeof next === "string" ? next.trim() !== current.objective.trim() : next !== current[field];
  });
  // Preserve the text being typed, but whitespace alone does not invalidate evidence.
  if (reviewFields.every((field) => edits[field] === undefined || edits[field] === current[field])) return previous;
  const next = engineeringInputRevision(previous) + 1;
  return {
    ...previous,
    inputs: { ...previous?.inputs, ...edits },
    requirementsRevision: changed.includes("objective") ? next : previous?.requirementsRevision ?? 0,
    geometryRevision: changed.some((field) => field !== "objective") ? next : previous?.geometryRevision ?? 0,
  };
}

export type JobInputChange = { reason: string; roots: EngineeringChangeRoot[] };

export function jobInputChange(job?: AutomationJob, review?: ProjectStageReview): JobInputChange | null {
  if (!job || !review) return null;
  const submitted = revision(job.uiConfig?.engineeringInputRevision);
  const submittedChat = revision(job.uiConfig?.chatInputRevision);
  const chatRoots = engineeringChangeRoots.filter((root) => (review.chatPhaseRevisions?.[root] ?? 0) > submittedChat);
  if (review.requirementsRevision > submitted || chatRoots.includes("requirements")) {
    return { reason: "项目需求已修改", roots: ["requirements"] };
  }
  const geometryChanged = review.geometryRevision > submitted;
  if (!geometryChanged && !chatRoots.length) return null;
  const roots = geometryChanged ? [...new Set(["part-modeling" as const, ...chatRoots])] : chatRoots;
  return { reason: "项目关键尺寸已修改", roots };
}

export function stagesNeedingReview(phases: EngineeringReviewPhase[], change: JobInputChange | null) {
  if (!change) return new Set<EngineeringReviewPhase>();
  if (change.roots.includes("requirements")) return new Set(phases);

  const knownIds = new Set(phases.map((phase) => phase.id));
  const affectedIds = new Set<string>();
  for (const root of change.roots) {
    if (knownIds.has(root)) affectedIds.add(root);
    else if (root === "drawing-bom" && knownIds.has("export-delivery")) affectedIds.add("export-delivery");
    else if (root === "drawing-bom" && knownIds.has("final-review")) affectedIds.add("final-review");
    else if (knownIds.has("part-modeling")) affectedIds.add("part-modeling");
    else return new Set(phases.filter((phase) => phase.id !== "requirements"));
  }
  // Older plans without dependency data cannot prove independence from geometry.
  const unknownDependencies = phases.filter((phase) => phase.id !== "requirements" && !Array.isArray(phase.depends_on));
  for (const phase of unknownDependencies) {
    if (phase.id) affectedIds.add(phase.id);
  }
  let size: number;
  do {
    size = affectedIds.size;
    for (const phase of phases) {
      if (phase.id && phase.depends_on?.some((parent) => affectedIds.has(parent))) affectedIds.add(phase.id);
    }
  } while (size !== affectedIds.size);
  return new Set([...unknownDependencies, ...phases.filter((phase) => affectedIds.has(phase.id ?? ""))]);
}
