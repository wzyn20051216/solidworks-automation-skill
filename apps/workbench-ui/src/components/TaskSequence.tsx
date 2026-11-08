import { Check, SpinnerGap, Trash } from "@phosphor-icons/react";
import { useState } from "react";
import { jobDisplayTitle, sidebarJobStatusLabel } from "../domain/jobs";
import type { AutomationJob } from "../types";

type TaskSequenceProps = {
  jobs: AutomationJob[];
  activeJobId?: string;
  deleteCandidateJobId: string | null;
  deletingJobId: string | null;
  terminalCount: number;
  onSelect: (job: AutomationJob) => void;
  onDelete: (job: AutomationJob) => void;
  onClearTerminal: () => Promise<void>;
};

/** @brief Projedeki son görev listesi; tekil silme ve son durumdaki kayıtların toplu temizliğini sağlar. */
export function TaskSequence({
  jobs,
  activeJobId,
  deleteCandidateJobId,
  deletingJobId,
  terminalCount,
  onSelect,
  onDelete,
  onClearTerminal,
}: TaskSequenceProps) {
  const [clearArmed, setClearArmed] = useState(false);
  const [clearing, setClearing] = useState(false);

  async function clearTerminalRecords() {
    if (!clearArmed) {
      setClearArmed(true);
      return;
    }
    setClearing(true);
    try {
      await onClearTerminal();
      setClearArmed(false);
    } finally {
      setClearing(false);
    }
  }

  return (
    <nav className="project-sequence" aria-label="Proje görev dizisi">
      <div className="project-sequence-head">
        <span className="sidebar-label">Son görevler</span>
        {terminalCount ? (
          <button
            className={clearArmed ? "clear-terminal-button confirm" : "clear-terminal-button"}
            type="button"
            disabled={clearing || deletingJobId !== null}
            title={clearArmed ? `${terminalCount} son durum kaydını temizlemek için tekrar tıklayın` : "Tamamlanmış görev kayıtlarını temizle"}
            aria-label={clearArmed ? `${terminalCount} son durumdaki görev kaydının temizlenmesini onayla` : "Son durumdaki görev kayıtlarını toplu temizle"}
            onBlur={() => setClearArmed(false)}
            onClick={() => void clearTerminalRecords()}
          >
            {clearing ? <SpinnerGap className="spin" size={13} /> : clearArmed ? <Check size={13} weight="bold" /> : <Trash size={13} />}
          </button>
        ) : null}
      </div>
      {jobs.length ? jobs.map((job) => (
        <div className={activeJobId === job.id ? "project-sequence-item active" : "project-sequence-item"} key={job.id}>
          <button className="project-sequence-select" type="button" onClick={() => onSelect(job)}>
            <i className={job.status === "review_required" && job.progress >= 100 ? "passed" : job.status} />
            <span>
              <strong>{jobDisplayTitle(job)}</strong>
              <small>{sidebarJobStatusLabel(job)} · {job.progress}%</small>
            </span>
          </button>
          <button
            className={deleteCandidateJobId === job.id ? "project-sequence-delete confirm" : "project-sequence-delete"}
            type="button"
            disabled={deletingJobId !== null}
            aria-label={deleteCandidateJobId === job.id ? `${jobDisplayTitle(job)} silinmesini onayla` : `${jobDisplayTitle(job)} sil`}
            title={deleteCandidateJobId === job.id ? "Silmeyi onaylamak için tekrar tıklayın" : "Görev kaydını sil"}
            onClick={() => onDelete(job)}
          >
            {deletingJobId === job.id ? <SpinnerGap className="spin" size={15} /> : deleteCandidateJobId === job.id ? <Check size={15} weight="bold" /> : <Trash size={15} weight="duotone" />}
          </button>
        </div>
      )) : (
        <div className="sidebar-empty">Burada gerçekten yürütülmüş görevler gösterilir. Şablon seçmek yeni kayıt eklemez.</div>
      )}
    </nav>
  );
}
