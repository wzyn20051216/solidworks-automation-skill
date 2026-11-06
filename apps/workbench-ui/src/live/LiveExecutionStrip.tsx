import type { AutomationJob, QueueEvent } from "../types";
import { deriveLiveVisual } from "./visualState";

export function LiveExecutionStrip({
  job,
  events,
}: {
  job: AutomationJob;
  events: QueueEvent[];
}) {
  const visual = deriveLiveVisual(job, events);
  return (
    <section
      className={`live-execution-strip status-${visual.status}`}
      aria-live="polite"
    >
      <div className="live-execution-copy">
        <span>{visual.phase.toUpperCase()}</span>
        <strong>{visual.title}</strong>
        <small>{visual.message || `步骤 ${visual.sequence}`}</small>
      </div>
      <div className="live-execution-progress">
        <i style={{ width: `${visual.progress}%` }} />
      </div>
      <span className="live-execution-progress-label">{visual.progress}%</span>
    </section>
  );
}
