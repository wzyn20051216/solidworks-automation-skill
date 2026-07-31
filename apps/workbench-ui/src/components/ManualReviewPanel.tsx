import type { ManualReviewDraft } from "../types";

type ManualReviewPanelProps = {
  draft: ManualReviewDraft;
  options: Array<readonly [string, string]>;
  onChange: (draft: Partial<ManualReviewDraft>) => void;
  onSubmit: (approved: boolean) => void;
};

/** @brief 强制记录原生 CAD、尺寸、特征和产物的人工复核证据。 */
export function ManualReviewPanel({ draft, options, onChange, onSubmit }: ManualReviewPanelProps) {
  const ready = draft.note.trim().length >= 8 && options.every(([key]) => draft.checks.includes(key));
  return (
    <div className="manual-review-form">
      <strong>人工复核记录</strong>
      <div className="manual-review-checks">
        {options.map(([key, label]) => (
          <label className="manual-review-check" key={key}>
            <input
              type="checkbox"
              checked={draft.checks.includes(key)}
              onChange={(event) => onChange({
                checks: event.target.checked ? [...new Set([...draft.checks, key])] : draft.checks.filter((item) => item !== key),
              })}
            />
            <span>{label}</span>
          </label>
        ))}
      </div>
      <textarea value={draft.note} onChange={(event) => onChange({ note: event.target.value })} placeholder="填写实际检查结果、发现的问题或放行依据" />
      <div className="review-action-row">
        <button className="approval-button" type="button" disabled={!ready} title={ready ? "通过人工复核" : "请完成全部检查项并填写至少 8 个字的复核说明"} onClick={() => onSubmit(true)}>
          通过复核
        </button>
        <button className="review-reject-button" type="button" onClick={() => onSubmit(false)}>驳回</button>
      </div>
    </div>
  );
}
