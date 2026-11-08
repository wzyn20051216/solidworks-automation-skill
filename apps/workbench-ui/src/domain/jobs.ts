import type { AutomationJob, AutomationJobStatus } from "../types";

/** @brief Tam görev durumu etiketini döndürür. */
export function jobStatusLabel(status: AutomationJobStatus) {
  if (status === "running") return "Yürütülüyor";
  if (status === "passed") return "Tamamlandı";
  if (status === "review_required") return "İnceleme bekliyor";
  if (status === "failed") return "Başarısız";
  if (status === "cancelled") return "İptal edildi";
  if (status === "approval_required") return "Onay bekliyor";
  if (status === "blocked") return "Engellendi";
  return "Kuyrukta";
}

/** @brief Kenar çubuğu, sonuç üretmiş inceleme bekleyen görevleri tamamlandı olarak işaretler. */
export function sidebarJobStatusLabel(job: AutomationJob) {
  if (job.status === "review_required" && job.progress >= 100) return "Tamamlandı";
  return jobStatusLabel(job.status);
}

/** @brief Uzun gereksinimleri kararlı bir görev başlığına sıkıştırır. */
export function conciseTaskTitle(value: string | undefined, fallback: string) {
  const normalized = value?.replace(/\s+/g, " ").trim();
  if (!normalized) return fallback;
  return normalized.length > 24 ? `${normalized.slice(0, 24)}...` : normalized;
}

/** @brief Dahili yürütücü başlıklarını gizler ve kullanıcının görev hedefini öncelikli gösterir. */
export function jobDisplayTitle(job: AutomationJob) {
  const title = job.title.trim();
  // Eski kayıtlarla uyumluluk için Çince anahtar sözcükler korunur; Türkçe karşılıkları eklenmiştir.
  const internalExecutionTitle = /^(Codex|Claude Code|Gemini CLI|OpenCode|Agent|AI 对话|AI sohbeti)\s*(执行|yürütmesi)$/i.test(title);
  if (!internalExecutionTitle) return title;
  return conciseTaskTitle(job.objective, job.target ? `${job.target} görevi` : "AI CAD görevi");
}
