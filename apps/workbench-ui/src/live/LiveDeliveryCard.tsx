import {
  CheckCircle,
  FolderOpen,
  WarningCircle,
} from "@phosphor-icons/react";
import type { AutomationJob, QueueEvent } from "../types";
import { deriveLiveVisual } from "./visualState";

export function LiveDeliveryCard({
  job,
  events,
  onOpenDelivery,
}: {
  job: AutomationJob;
  events: QueueEvent[];
  onOpenDelivery: () => void;
}) {
  const visual = deriveLiveVisual(job, events);
  const isComplete = job.status === "passed";
  const featureCount =
    visual.stats.featureCount ?? job.result?.features?.length;
  return (
    <section
      className={`live-delivery-card ${isComplete ? "complete" : "review"}`}
    >
      <header>
        {isComplete ? (
          <CheckCircle size={18} weight="fill" />
        ) : (
          <WarningCircle size={18} weight="fill" />
        )}
        <strong>{isComplete ? "本轮交付完成" : "本轮需要复核"}</strong>
        <span>{job.reviewGate?.status || job.status}</span>
      </header>
      <div className="live-delivery-stats">
        <div>
          <span>体积</span>
          <strong>
            {visual.stats.volumeMm3
              ? `${visual.stats.volumeMm3.toFixed(1)} mm³`
              : "未提供"}
          </strong>
        </div>
        <div>
          <span>特征</span>
          <strong>{featureCount ?? "未提供"}</strong>
        </div>
        <div>
          <span>输出</span>
          <strong>
            {job.result?.outputPath?.split(/[\\/]/).at(-1) || "未提供"}
          </strong>
        </div>
      </div>
      <footer>
        <button type="button" onClick={onOpenDelivery}>
          <FolderOpen size={15} />
          查看交付页
        </button>
      </footer>
    </section>
  );
}
