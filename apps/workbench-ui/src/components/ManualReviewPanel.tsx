import type { ManualReviewDraft } from "../types";

type ManualReviewPanelProps = {
  draft: ManualReviewDraft;
  options: Array<readonly [string, string]>;
  onChange: (draft: Partial<ManualReviewDraft>) => void;
  onSubmit: (approved: boolean) => void;
};

/** @brief Yerel CAD, ölçüler, unsurlar ve çıktılar için manuel inceleme kanıtlarının kaydını zorunlu kılar. */
export function ManualReviewPanel({ draft, options, onChange, onSubmit }: ManualReviewPanelProps) {
  const ready = draft.note.trim().length >= 8 && options.every(([key]) => draft.checks.includes(key));
  return (
    <div className="manual-review-form">
      <strong>Manuel inceleme kaydı</strong>
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
      <textarea value={draft.note} onChange={(event) => onChange({ note: event.target.value })} placeholder="Gerçek denetim sonuçlarını, bulunan sorunları veya onay gerekçesini yazın" />
      <div className="review-action-row">
        <button className="approval-button" type="button" disabled={!ready} title={ready ? "Manuel incelemeyi onayla" : "Lütfen tüm denetim maddelerini tamamlayın ve en az 8 karakterlik bir inceleme açıklaması yazın"} onClick={() => onSubmit(true)}>
          İncelemeyi onayla
        </button>
        <button className="review-reject-button" type="button" onClick={() => onSubmit(false)}>Reddet</button>
      </div>
    </div>
  );
}
