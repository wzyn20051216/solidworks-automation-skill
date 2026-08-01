import { CadPreview } from "../CadPreview";
import { artifactKindLabel, artifactStatusLabel, formatBytes } from "../domain/artifacts";
import type { ArtifactRecord } from "../types";

type ArtifactBrowserProps = {
  artifacts: ArtifactRecord[];
  selected?: ArtifactRecord;
  onSelect: (path?: string) => void;
  showPreview?: boolean;
};

/** @brief 展示真实交付文件并为支持格式提供预览。 */
export function ArtifactBrowser({ artifacts, selected, onSelect, showPreview = true }: ArtifactBrowserProps) {
  return (
    <div className="artifact-list delivery-artifacts">
      {artifacts.length ? artifacts.map((artifact, index) => (
        <button
          type="button"
          className={`${artifact.exists === false ? "artifact-row missing" : "artifact-row"} ${selected?.path === artifact.path ? "selected" : ""}`}
          key={`${artifact.path}-${index}`}
          onClick={() => onSelect(artifact.path)}
          title="在右侧预览此交付物"
        >
          <div>
            <strong>{artifactKindLabel(artifact.kind, artifact.path)}</strong>
            <span>{artifact.path}</span>
          </div>
          <small>{formatBytes(artifact.sizeBytes) || artifactStatusLabel(artifact)}</small>
        </button>
      )) : (
        <div className="inspector-empty">
          <strong>还没有可交付文件</strong>
          <p>先让 AI 完成建模、出图或转换任务，交付中心会读取真实输出物。</p>
        </div>
      )}
      {showPreview ? <CadPreview artifact={selected} /> : null}
    </div>
  );
}
