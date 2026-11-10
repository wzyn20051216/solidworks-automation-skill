import { stagesNeedingReview, type JobInputChange } from "../domain/stageReview";
import type { EngineeringReviewPhase } from "../types";

type Props = {
  phases: EngineeringReviewPhase[];
  change: JobInputChange | null;
};

export function StageReviewPanel({ phases, change }: Props) {
  const affected = stagesNeedingReview(phases, change);
  if (!phases.length && !change) return null;

  return (
    <section className="engineering-plan-view" aria-label="阶段复核">
      <strong>阶段复核</strong>
      {change ? <p className="stage-review-notice">{change.reason}。请按当前输入重新执行并复核受影响阶段。原记录仍可查看。</p> : null}
      {phases.length > 0 ? (
        <ol>
          {phases.map((phase, index) => {
            const needsReview = affected.has(phase);
            const status = needsReview ? "待复核"
              : phase.status === "blocked" ? "已阻断"
              : phase.status === "completed" ? "已完成"
              : phase.human_gate ? "待人工确认" : "待确认";
            return (
              <li key={phase.id || index}>
                <div>
                  <strong>{phase.name || phase.id || `阶段 ${index + 1}`}</strong>
                  <span className={needsReview || phase.human_gate ? "stage-review-notice" : undefined}>{status}</span>
                </div>
                {phase.acceptance?.length ? (
                  <ul>{phase.acceptance.map((check, checkIndex) => <li key={checkIndex}>{check}</li>)}</ul>
                ) : <p>此阶段暂无明确的验收条件。</p>}
              </li>
            );
          })}
        </ol>
      ) : null}
    </section>
  );
}
