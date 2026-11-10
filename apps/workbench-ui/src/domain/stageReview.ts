import type { AutomationJob, EngineeringReviewPhase, ProjectReviewInputs, ProjectStageReview } from "../types";

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
  };
}

export function engineeringInputRevision(review?: ProjectStageReview): number {
  return Math.max(review?.requirementsRevision ?? 0, review?.geometryRevision ?? 0);
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
    inputs: { ...previous?.inputs, ...edits },
    requirementsRevision: changed.includes("objective") ? next : previous?.requirementsRevision ?? 0,
    geometryRevision: changed.some((field) => field !== "objective") ? next : previous?.geometryRevision ?? 0,
  };
}

export function jobInputChange(job?: AutomationJob, review?: ProjectStageReview) {
  if (!job || !review) return null;
  const submitted = revision(job.uiConfig?.engineeringInputRevision);
  if (review.requirementsRevision > submitted) return "项目需求已修改";
  if (review.geometryRevision > submitted) return "项目关键尺寸已修改";
  return null;
}

export function stagesNeedingReview(phases: EngineeringReviewPhase[], change: ReturnType<typeof jobInputChange>) {
  if (!change) return new Set<EngineeringReviewPhase>();
  if (change === "项目需求已修改") return new Set(phases);
  if (!phases.some((phase) => phase.id === "part-modeling")) {
    return new Set(phases.filter((phase) => phase.id !== "requirements"));
  }

  const affectedIds = new Set(["part-modeling"]);
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
