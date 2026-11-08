import { ArrowClockwise, ArrowsOut, CubeFocus, Eye, Minus, Plus, Selection, Stack, X } from "@phosphor-icons/react";
import type { PreviewActions, PreviewMode } from "./previewTypes";

type PreviewToolbarProps = {
  ready: boolean;
  mode: PreviewMode;
  projection: "perspective" | "orthographic";
  actions?: PreviewActions | null;
};

/** @brief CAD görünümü için kompakt simge araç çubuğu. */
export function PreviewToolbar({ ready, mode, projection, actions }: PreviewToolbarProps) {
  const disabled = !ready || !actions;
  return (
    <div className="cad-preview-tools mechanical">
      <button type="button" title="Önizlemeyi uzaklaştır" aria-label="Önizlemeyi uzaklaştır" disabled={disabled} onClick={() => actions?.zoom(-1)}><Minus size={16} /></button>
      <button type="button" title="Önizlemeyi yakınlaştır" aria-label="Önizlemeyi yakınlaştır" disabled={disabled} onClick={() => actions?.zoom(1)}><Plus size={16} /></button>
      <button type="button" title="Görünümü sığdır (F)" aria-label="Görünümü sığdır" disabled={disabled} onClick={() => actions?.fit()}><ArrowsOut size={16} /></button>
      <button type="button" title="Görünümü sıfırla" aria-label="Görünümü sıfırla" disabled={disabled} onClick={() => actions?.reset()}><ArrowClockwise size={16} /></button>
      <button type="button" title="Seçimi temizle (Esc)" aria-label="Seçimi temizle" disabled={disabled} onClick={() => actions?.clearSelection()}><X size={16} /></button>
      <span className="view-cluster" aria-label="Standart görünümler">
        {(["iso", "front", "right", "top"] as const).map((view) => (
          <button key={view} type="button" title={`${view} görünümü`} disabled={disabled} onClick={() => actions?.setStandardView(view)}>{view === "iso" ? "ISO" : view === "front" ? "Ön" : view === "right" ? "Sağ" : "Üst"}</button>
        ))}
      </span>
      <button type="button" title="Perspektif/ortografik kamera" aria-label="Perspektif/ortografik kamera" disabled={disabled || mode !== "mesh" || !actions?.toggleProjection} onClick={() => actions?.toggleProjection?.()}><Eye size={16} /></button>
      <span className="preview-mode-chip"><CubeFocus size={15} /> {mode === "dxf" ? "DXF sahnesi" : mode === "mesh" ? "Three.js ağı" : mode === "image" ? "Görüntü yedeği" : "Önizleme"}</span>
      <span className="preview-mode-chip"><Stack size={15} /> {projection === "orthographic" ? "Ortografik" : "Perspektif"}</span>
      <span className="preview-mode-chip"><Selection size={15} /> F / 1-6 / Esc</span>
    </div>
  );
}
