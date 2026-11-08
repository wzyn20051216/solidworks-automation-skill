import type { PreviewManifest, PreviewSelection } from "./previewTypes";

type PreviewEvidencePanelProps = {
  manifest?: PreviewManifest | null;
  selection?: PreviewSelection | null;
};

/** @brief Önizleme ile teslimat kanıt grafiği, hash ve kısıtlama açıklamaları arasındaki bağları gösterir. */
export function PreviewEvidencePanel({ manifest, selection }: PreviewEvidencePanelProps) {
  const evidence = [...new Set([...(manifest?.evidenceRefs ?? []), ...(selection?.evidenceRefs ?? [])])];
  const limitations = manifest?.limitations ?? [];
  return (
    <div className="cad-preview-evidence">
      <div><span>Önizleme hash'i</span><strong>{manifest?.sha256 ? `${manifest.sha256.slice(0, 12)}…` : "Kayıt yok"}</strong></div>
      <div><span>Oluşturulma zamanı</span><strong>{manifest?.generatedAt || "Kayıt yok"}</strong></div>
      {evidence.length ? <div className="evidence-tags">{evidence.map((item) => <small key={item}>{item}</small>)}</div> : <small>Henüz Evidence Graph bağlantısı yok.</small>}
      {limitations.length ? <div className="preview-limitations">{limitations.map((item) => <small key={item}>{item}</small>)}</div> : null}
    </div>
  );
}
