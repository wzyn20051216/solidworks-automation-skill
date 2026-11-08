import type { AgentConversation, AutomationJob, ProjectRecord } from "../types";

export const LEGACY_PROJECT_ID = "project-default";

export const DEFAULT_PROJECT: ProjectRecord = {
  id: LEGACY_PROJECT_ID,
  name: "Adsız proje",
  createdAt: "",
  updatedAt: "",
};

/** @brief Görevin ait olduğu projeyi döndürür; 1.0 görevleriyle uyumludur. */
export function jobProjectId(job: AutomationJob) {
  return job.projectId || LEGACY_PROJECT_ID;
}

/** @brief Eski projelerle çakışmayan yerel bir proje ID'si oluşturur. */
export function newProjectId() {
  return `project-${Date.now()}-${Math.random().toString(16).slice(2, 8)}`;
}

/** @brief Proje adını temizleyerek kenar çubuğu düzeninin kararlı kalmasını sağlar. */
export function normalizeProjectName(value: string) {
  return value.replace(/\s+/g, " ").trim().slice(0, 48) || "Adsız proje";
}

/** @brief Güncellenme zamanına göre projenin en son kullanılan sohbetini döndürür. */
export function latestProjectConversation(conversations: AgentConversation[], projectId: string) {
  return conversations
    .filter((conversation) => conversation.projectId === projectId)
    .reduce<AgentConversation | undefined>((latest, conversation) => (
      !latest || conversation.updatedAt.localeCompare(latest.updatedAt) > 0 ? conversation : latest
    ), undefined);
}

/** @brief Görünür projeleri döndürür; arşivlenmiş projeler yalnızca kullanıcı arşivi açıkça görüntülediğinde listelenir. */
export function filterProjects(projects: ProjectRecord[], query: string, showArchived: boolean) {
  const normalized = query.trim().toLocaleLowerCase("zh-CN");
  return projects.filter((project) => {
    if (Boolean(project.archivedAt) !== showArchived) return false;
    if (!normalized) return true;
    return project.name.toLocaleLowerCase("zh-CN").includes(normalized)
      || project.sourcePath?.toLocaleLowerCase("zh-CN").includes(normalized);
  });
}

/** @brief Proje meta verilerini kopyalar; görevleri, sohbetleri veya CAD teslimat dosyalarını kopyalamaz. */
export function duplicateProjectRecord(project: ProjectRecord, existingCount: number) {
  const now = new Date().toISOString();
  return {
    id: newProjectId(),
    name: normalizeProjectName(`${project.name} kopyası ${existingCount + 1}`),
    sourcePath: project.sourcePath,
    createdAt: now,
    updatedAt: now,
  } satisfies ProjectRecord;
}

/** @brief Projede bitmemiş görev olup olmadığını belirler. */
export function hasActiveProjectJobs(jobs: AutomationJob[], projectId: string) {
  return jobs.some((job) => jobProjectId(job) === projectId && ["queued", "running", "approval_required"].includes(job.status));
}

/** @brief Yalnızca güvenle temizlenebilecek son durumdaki görev kayıtlarını seçer. */
export function terminalProjectJobs(jobs: AutomationJob[], projectId: string) {
  return jobs.filter((job) => jobProjectId(job) === projectId && ["passed", "failed", "cancelled", "review_required", "blocked"].includes(job.status));
}
