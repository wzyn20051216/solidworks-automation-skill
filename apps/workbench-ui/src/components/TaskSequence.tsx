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

/** @brief 项目内最近任务列表，提供单条删除和终态记录批量清理。 */
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
    <nav className="project-sequence" aria-label="项目任务序列">
      <div className="project-sequence-head">
        <span className="sidebar-label">最近任务</span>
        {terminalCount ? (
          <button
            className={clearArmed ? "clear-terminal-button confirm" : "clear-terminal-button"}
            type="button"
            disabled={clearing || deletingJobId !== null}
            title={clearArmed ? `再次点击清理 ${terminalCount} 条终态记录` : "清理已结束的任务记录"}
            aria-label={clearArmed ? `确认清理 ${terminalCount} 条终态任务记录` : "批量清理终态任务记录"}
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
            aria-label={deleteCandidateJobId === job.id ? `确认删除 ${jobDisplayTitle(job)}` : `删除 ${jobDisplayTitle(job)}`}
            title={deleteCandidateJobId === job.id ? "再次点击确认删除" : "删除任务记录"}
            onClick={() => onDelete(job)}
          >
            {deletingJobId === job.id ? <SpinnerGap className="spin" size={15} /> : deleteCandidateJobId === job.id ? <Check size={15} weight="bold" /> : <Trash size={15} weight="duotone" />}
          </button>
        </div>
      )) : (
        <div className="sidebar-empty">这里会显示真正执行过的任务。选择模板不会新增记录。</div>
      )}
    </nav>
  );
}
