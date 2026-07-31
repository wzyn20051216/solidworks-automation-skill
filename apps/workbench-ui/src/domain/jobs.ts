import type { AutomationJob, AutomationJobStatus } from "../types";

/** @brief 返回完整任务状态标签。 */
export function jobStatusLabel(status: AutomationJobStatus) {
  if (status === "running") return "执行中";
  if (status === "passed") return "完成";
  if (status === "review_required") return "待复核";
  if (status === "failed") return "失败";
  if (status === "cancelled") return "已取消";
  if (status === "approval_required") return "待审批";
  if (status === "blocked") return "已阻断";
  return "排队";
}

/** @brief 侧栏将已产出结果的待复核任务标为已完成。 */
export function sidebarJobStatusLabel(job: AutomationJob) {
  if (job.status === "review_required" && job.progress >= 100) return "已完成";
  return jobStatusLabel(job.status);
}

/** @brief 把长需求压缩为稳定的任务标题。 */
export function conciseTaskTitle(value: string | undefined, fallback: string) {
  const normalized = value?.replace(/\s+/g, " ").trim();
  if (!normalized) return fallback;
  return normalized.length > 24 ? `${normalized.slice(0, 24)}...` : normalized;
}

/** @brief 隐藏内部执行器标题，优先显示用户任务目标。 */
export function jobDisplayTitle(job: AutomationJob) {
  const title = job.title.trim();
  const internalExecutionTitle = /^(Codex|Claude Code|Gemini CLI|OpenCode|Agent|AI 对话)\s*执行$/i.test(title);
  if (!internalExecutionTitle) return title;
  return conciseTaskTitle(job.objective, job.target ? `${job.target}任务` : "AI CAD 任务");
}
