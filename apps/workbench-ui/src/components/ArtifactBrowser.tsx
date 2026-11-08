import { CadPreview } from "../CadPreview";
import { artifactKindLabel, artifactStatusLabel, formatBytes } from "../domain/artifacts";
import type { ArtifactRecord } from "../types";

type ArtifactBrowserProps = {
  artifacts: ArtifactRecord[];
  selected?: ArtifactRecord;
  onSelect: (path?: string) => void;
  showPreview?: boolean;
};

/** @brief Gerçek teslimat dosyalarını listeler ve desteklenen biçimler için önizleme sunar. */
export function ArtifactBrowser({ artifacts, selected, onSelect, showPreview = true }: ArtifactBrowserProps) {
  return (
    <div className="artifact-list delivery-artifacts">
      {artifacts.length ? artifacts.map((artifact, index) => (
        <button
          type="button"
          className={`${artifact.exists === false ? "artifact-row missing" : "artifact-row"} ${selected?.path === artifact.path ? "selected" : ""}`}
          key={`${artifact.path}-${index}`}
          onClick={() => onSelect(artifact.path)}
          title="Bu teslimatı sağda önizle"
        >
          <div>
            <strong>{artifactKindLabel(artifact.kind, artifact.path)}</strong>
            <span>{artifact.path}</span>
          </div>
          <small>{formatBytes(artifact.sizeBytes) || artifactStatusLabel(artifact)}</small>
        </button>
      )) : (
        <div className="inspector-empty">
          <strong>Henüz teslim edilebilir dosya yok</strong>
          <p>Önce AI'nın modelleme, çizim veya dönüştürme görevini tamamlamasını sağlayın; teslimat merkezi gerçek çıktıları okuyacaktır.</p>
        </div>
      )}
      {showPreview ? <CadPreview artifact={selected} /> : null}
    </div>
  );
}
