import type { PreviewManifest, PreviewSelection } from "./previewTypes";

type PreviewEvidencePanelProps = {
  manifest?: PreviewManifest | null;
  selection?: PreviewSelection | null;
};

/** @brief 展示预览与交付证据图、哈希和限制说明的绑定关系。 */
export function PreviewEvidencePanel({ manifest, selection }: PreviewEvidencePanelProps) {
  const evidence = [...new Set([...(manifest?.evidenceRefs ?? []), ...(selection?.evidenceRefs ?? [])])];
  const limitations = manifest?.limitations ?? [];
  return (
    <div className="cad-preview-evidence">
      <div><span>预览哈希</span><strong>{manifest?.sha256 ? `${manifest.sha256.slice(0, 12)}…` : "未记录"}</strong></div>
      <div><span>生成时间</span><strong>{manifest?.generatedAt || "未记录"}</strong></div>
      {evidence.length ? <div className="evidence-tags">{evidence.map((item) => <small key={item}>{item}</small>)}</div> : <small>暂无 Evidence Graph 绑定。</small>}
      {limitations.length ? <div className="preview-limitations">{limitations.map((item) => <small key={item}>{item}</small>)}</div> : null}
    </div>
  );
}
