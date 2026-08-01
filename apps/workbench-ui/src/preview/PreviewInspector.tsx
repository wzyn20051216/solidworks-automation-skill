import type { PreviewLayer, PreviewManifest, PreviewSelection, PreviewStats } from "./previewTypes";
import { fileName } from "./previewUtils";

type PreviewInspectorProps = {
  artifactPath?: string;
  manifest?: PreviewManifest | null;
  stats: PreviewStats;
  selection?: PreviewSelection | null;
  layers: PreviewLayer[];
  visibleLayers: Set<string>;
  onToggleLayer: (layer: string) => void;
};

/** @brief 展示模型树、图层、尺寸范围和选中实体信息。 */
export function PreviewInspector({ artifactPath, manifest, stats, selection, layers, visibleLayers, onToggleLayer }: PreviewInspectorProps) {
  return (
    <aside className="cad-preview-inspector" aria-label="预览检查器">
      <div className="inspector-block">
        <span>文件</span>
        <strong>{fileName(artifactPath)}</strong>
        {manifest?.sourceArtifact ? <small>源: {fileName(manifest.sourceArtifact)}</small> : null}
      </div>
      <div className="inspector-grid">
        <div><span>单位</span><strong>{stats.units || manifest?.units || "mm"}</strong></div>
        <div><span>实体</span><strong>{stats.entityCount ?? stats.meshCount ?? 0}</strong></div>
        <div><span>图层</span><strong>{stats.layerCount ?? layers.length}</strong></div>
        <div><span>范围</span><strong>{stats.boundsLabel || "待读取"}</strong></div>
      </div>
      {selection ? (
        <div className="inspector-block selected">
          <span>当前选择</span>
          <strong>{selection.name}</strong>
          <small>{selection.type}{selection.layer ? ` · ${selection.layer}` : ""}</small>
        </div>
      ) : <div className="inspector-empty-mini">点击模型实体或 DXF 线条查看证据引用。</div>}
      {layers.length ? (
        <div className="layer-list" aria-label="DXF 图层">
          <span>图层</span>
          {layers.map((layer) => (
            <label key={layer.name}>
              <input type="checkbox" checked={visibleLayers.has(layer.name)} onChange={() => onToggleLayer(layer.name)} />
              <i style={{ background: layer.color || "#176c65" }} />
              <strong>{layer.name}</strong>
              <small>{layer.count ?? 0}</small>
            </label>
          ))}
        </div>
      ) : null}
    </aside>
  );
}
