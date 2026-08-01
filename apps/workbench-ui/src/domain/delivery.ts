import { artifactGroup, collectJobArtifacts, fileNameFromPath } from "./artifacts";
import type { ArtifactRecord, AutomationJob, BackendDiagnostic, JobRunSnapshot } from "../types";

export type DeliveryDisposition = "idle" | "active" | "ready" | "review_required" | "blocked" | "failed" | "incomplete";
export type DeliveryAssessment = {
  disposition: DeliveryDisposition;
  title: string;
  summary: string;
  issues: string[];
  readyArtifacts: number;
  currentArtifacts: number;
};

const stageLabels: Record<string, string> = {
  requirements: "需求确认",
  "part-modeling": "零件建模",
  "holes-fillet-chamfer": "孔槽与圆角",
  "assembly-mates": "装配配合",
  "motion-study": "运动算例",
  "drawing-bom": "工程图与 BOM",
  "export-delivery": "导出交付",
  "final-review": "最终复核",
  intake: "需求接收",
  planning: "任务规划",
  checking: "环境检查",
  launching: "CAD 启动",
  executing: "CAD 执行",
  reviewing: "结果复核",
  delivery: "交付整理",
  blocked: "能力或环境检查",
};

export function retryStageLabel(stage?: string) {
  if (!stage) return "失败阶段";
  return stageLabels[stage] ?? stage;
}

export function retryStageForJob(job?: AutomationJob) {
  if (!job) return "requirements";
  if (job.retryPolicy?.retryFromStage) return job.retryPolicy.retryFromStage;
  const failedPhase = job.result?.engineeringPlan?.phases?.find((phase) =>
    ["blocked", "failed", "review_required"].includes(phase.status ?? ""),
  );
  if (failedPhase?.id) return failedPhase.id;
  for (const evidence of [job.drawingEvidence, job.bomEvidence]) {
    if (evidence && ["blocked", "failed", "fail", "warning"].includes(String(evidence.status))) return "drawing-bom";
  }
  if (["failed", "review_required"].includes(job.status)) return "final-review";
  return "requirements";
}

function requiresArtifacts(job: AutomationJob) {
  const descriptor = `${job.expectedOutput ?? ""} ${job.target ?? ""} ${(job.requiredArtifacts ?? []).join(" ")}`;
  return job.kind === "delivery_package" || Boolean(job.requiredArtifacts?.length) || /CAD(?:_FILES)?|DRAWING(?:_PACKAGE)?|PACKAGE|SLDPRT|SLDASM|STEP|STL|DWG|DXF|PDF|PNG|BOM|模型|图纸|交付/i.test(descriptor);
}

function artifactMatchesRequirement(artifact: ArtifactRecord, requirement: string) {
  const token = requirement.trim().toLowerCase();
  if (!token) return true;
  const descriptor = `${artifact.kind ?? ""} ${artifact.path ?? ""}`.toLowerCase();
  if (descriptor.includes(token)) return true;
  const aliases: Record<string, string[]> = {
    model: ["model", "模型", "sldprt", "sldasm", "step", "stp", "stl"],
    drawing: ["drawing", "图纸", "工程图", "slddrw", "dwg", "dxf"],
    bom: ["bom", "物料", "明细表"],
    preview: ["preview", "预览", "png", "bmp", "jpg", "jpeg", "webp"],
    report: ["review", "report", "ledger", "复核", "报告"],
  };
  return aliases[artifactGroup(artifact)].some((alias) => token.includes(alias));
}

export function assessDelivery(job?: AutomationJob): DeliveryAssessment {
  if (!job) return { disposition: "idle", title: "等待任务结果", summary: "任务执行后将在这里形成交付判定。", issues: [], readyArtifacts: 0, currentArtifacts: 0 };
  const artifacts = collectJobArtifacts(job);
  const readyArtifacts = artifacts.filter((item) => item.exists !== false && item.producedThisRun !== false);
  const issues: string[] = [];
  const staleOrMissing = artifacts.filter((item) => item.exists === false || item.producedThisRun === false);
  if (staleOrMissing.length) issues.push(`${staleOrMissing.length} 个产物缺失或不是本轮生成`);
  for (const requirement of job.requiredArtifacts ?? []) {
    if (!readyArtifacts.some((artifact) => artifactMatchesRequirement(artifact, requirement))) issues.push(`缺少要求产物：${requirement}`);
  }
  for (const evidence of [job.drawingEvidence, job.bomEvidence]) {
    if (!evidence) continue;
    if (evidence.error_code) issues.push(String(evidence.error_code));
    if (Array.isArray(evidence.limitations)) issues.push(...evidence.limitations.map(String));
  }
  if (job.blockedReasons?.length) issues.push(...job.blockedReasons);
  const uniqueIssues = [...new Set(issues.filter(Boolean))];
  const evidenceStatuses = [job.drawingEvidence?.status, job.bomEvidence?.status].map(String);
  if (job.status === "blocked" || evidenceStatuses.includes("blocked")) {
    return { disposition: "blocked", title: "交付已阻断", summary: "环境、许可证或能力门禁尚未满足。", issues: uniqueIssues, readyArtifacts: readyArtifacts.length, currentArtifacts: artifacts.length };
  }
  if (job.status === "failed" || evidenceStatuses.some((status) => ["failed", "fail"].includes(status))) {
    return { disposition: "failed", title: "交付未通过", summary: "执行或工程复核存在失败项，旧版本证据已保留。", issues: uniqueIssues.length ? uniqueIssues : [job.error || "请查看执行日志和复核报告"], readyArtifacts: readyArtifacts.length, currentArtifacts: artifacts.length };
  }
  if (["queued", "running", "approval_required"].includes(job.status)) {
    return { disposition: "active", title: job.status === "approval_required" ? "等待审批" : "交付生成中", summary: "本轮机器证据尚未完整，不能提前判定完成。", issues: uniqueIssues, readyArtifacts: readyArtifacts.length, currentArtifacts: artifacts.length };
  }
  if (job.status === "cancelled") {
    return { disposition: "incomplete", title: "任务已取消", summary: "本轮执行已取消，现有文件不能自动作为最终交付。", issues: uniqueIssues, readyArtifacts: readyArtifacts.length, currentArtifacts: artifacts.length };
  }
  if ((requiresArtifacts(job) && readyArtifacts.length === 0) || uniqueIssues.some((issue) => issue.startsWith("缺少要求产物"))) {
    return { disposition: "incomplete", title: "交付证据不完整", summary: "任务已结束，但本轮要求的文件或账本尚未齐全。", issues: uniqueIssues.length ? uniqueIssues : ["没有可确认的本轮 CAD 产物"], readyArtifacts: readyArtifacts.length, currentArtifacts: artifacts.length };
  }
  const manualReviewRequired = [job.drawingEvidence, job.bomEvidence].some((item) => item?.manual_review_required);
  if (job.status === "review_required" || manualReviewRequired || job.reviewGate?.status === "warning") {
    return { disposition: "review_required", title: "等待人工复核", summary: "文件已生成，需原生打开并核对尺寸、特征和版面后才能交付。", issues: uniqueIssues, readyArtifacts: readyArtifacts.length, currentArtifacts: artifacts.length };
  }
  return { disposition: "ready", title: "本轮可交付", summary: job.reviewDecision === "approved" ? "机器检查与人工复核均已完成。" : "本轮机器证据完整，任务状态已完成。", issues: uniqueIssues, readyArtifacts: readyArtifacts.length, currentArtifacts: artifacts.length };
}

export function backendDiagnosticsFor(job?: AutomationJob): BackendDiagnostic[] {
  const value = job?.backendDiagnostics ?? job?.result?.backendDiagnostics;
  if (Array.isArray(value)) return value.filter((item): item is BackendDiagnostic => Boolean(item) && typeof item === "object");
  if (value && typeof value === "object") {
    return Object.entries(value).flatMap(([backend, item]) => {
      if (!item || typeof item !== "object" || Array.isArray(item)) return [];
      return [{ ...item, backend: item.backend ?? backend }];
    });
  }
  return [];
}

export function artifactVersionComparison(job?: AutomationJob) {
  const current = collectJobArtifacts(job);
  const latest = job?.runHistory?.at(-1)?.artifacts ?? [];
  const previousByKey = new Map(latest.map((item) => [`${item.kind ?? ""}:${fileNameFromPath(item.path)}`, item]));
  const currentKeys = new Set(current.map((item) => `${item.kind ?? ""}:${fileNameFromPath(item.path)}`));
  let added = 0;
  let changed = 0;
  let unchanged = 0;
  for (const item of current) {
    const previous = previousByKey.get(`${item.kind ?? ""}:${fileNameFromPath(item.path)}`);
    if (!previous) added += 1;
    else if (item.sha256 && previous.sha256 && item.sha256 !== previous.sha256) changed += 1;
    else unchanged += 1;
  }
  const removed = [...previousByKey.keys()].filter((key) => !currentKeys.has(key)).length;
  return { added, removed, changed, unchanged, previous: latest.length, current: current.length };
}

export function createRunSnapshot(job: AutomationJob): JobRunSnapshot {
  return {
    runId: job.runId,
    status: job.status,
    stage: job.stage,
    createdAt: job.createdAt,
    updatedAt: job.updatedAt,
    lastMessage: job.lastMessage,
    error: job.error,
    result: job.result,
    artifacts: job.artifacts,
    artifactLedgerPath: job.artifactLedgerPath,
    reviewGatePath: job.reviewGatePath,
    reviewGate: job.reviewGate,
    drawingEvidence: job.drawingEvidence,
    bomEvidence: job.bomEvidence,
    reviewFindings: job.reviewFindings,
    artifactRelations: job.artifactRelations,
    blockedReasons: job.blockedReasons,
  };
}
