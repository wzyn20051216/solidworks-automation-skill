import type { AgentConversation, AutomationJob, ProjectRecord } from "../types";

export const LEGACY_PROJECT_ID = "project-default";

export const DEFAULT_PROJECT: ProjectRecord = {
  id: LEGACY_PROJECT_ID,
  name: "未命名项目",
  createdAt: "",
  updatedAt: "",
};

/** @brief 返回任务所属项目，兼容 1.0 任务。 */
export function jobProjectId(job: AutomationJob) {
  return job.projectId || LEGACY_PROJECT_ID;
}

/** @brief 创建不会与旧项目冲突的本地项目 ID。 */
export function newProjectId() {
  return `project-${Date.now()}-${Math.random().toString(16).slice(2, 8)}`;
}

/** @brief 清洗项目名称，保证侧栏布局稳定。 */
export function normalizeProjectName(value: string) {
  return value.replace(/\s+/g, " ").trim().slice(0, 48) || "未命名项目";
}

/** @brief 按更新时间返回项目最近使用的对话。 */
export function latestProjectConversation(conversations: AgentConversation[], projectId: string) {
  return conversations
    .filter((conversation) => conversation.projectId === projectId)
    .reduce<AgentConversation | undefined>((latest, conversation) => (
      !latest || conversation.updatedAt.localeCompare(latest.updatedAt) > 0 ? conversation : latest
    ), undefined);
}

/** @brief 返回可见项目；归档项目仅在用户明确查看归档时出现。 */
export function filterProjects(projects: ProjectRecord[], query: string, showArchived: boolean) {
  const normalized = query.trim().toLocaleLowerCase("zh-CN");
  return projects.filter((project) => {
    if (Boolean(project.archivedAt) !== showArchived) return false;
    if (!normalized) return true;
    return project.name.toLocaleLowerCase("zh-CN").includes(normalized)
      || project.sourcePath?.toLocaleLowerCase("zh-CN").includes(normalized);
  });
}

/** @brief 复制项目元数据，不复制任务、对话或 CAD 交付文件。 */
export function duplicateProjectRecord(project: ProjectRecord, existingCount: number) {
  const now = new Date().toISOString();
  return {
    id: newProjectId(),
    name: normalizeProjectName(`${project.name} 副本 ${existingCount + 1}`),
    sourcePath: project.sourcePath,
    createdAt: now,
    updatedAt: now,
  } satisfies ProjectRecord;
}

/** @brief 判断项目是否存在未结束任务。 */
export function hasActiveProjectJobs(jobs: AutomationJob[], projectId: string) {
  return jobs.some((job) => jobProjectId(job) === projectId && ["queued", "running", "approval_required"].includes(job.status));
}

/** @brief 只选择可安全清理的终态任务记录。 */
export function terminalProjectJobs(jobs: AutomationJob[], projectId: string) {
  return jobs.filter((job) => jobProjectId(job) === projectId && ["passed", "failed", "cancelled", "review_required", "blocked"].includes(job.status));
}
