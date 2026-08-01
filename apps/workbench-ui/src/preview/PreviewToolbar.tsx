import { ArrowClockwise, ArrowsOut, CubeFocus, Eye, Minus, Plus, Selection, Stack, X } from "@phosphor-icons/react";
import type { PreviewActions, PreviewMode } from "./previewTypes";

type PreviewToolbarProps = {
  ready: boolean;
  mode: PreviewMode;
  projection: "perspective" | "orthographic";
  actions?: PreviewActions | null;
};

/** @brief CAD 视口的紧凑图标工具栏。 */
export function PreviewToolbar({ ready, mode, projection, actions }: PreviewToolbarProps) {
  const disabled = !ready || !actions;
  return (
    <div className="cad-preview-tools mechanical">
      <button type="button" title="缩小预览" aria-label="缩小预览" disabled={disabled} onClick={() => actions?.zoom(-1)}><Minus size={16} /></button>
      <button type="button" title="放大预览" aria-label="放大预览" disabled={disabled} onClick={() => actions?.zoom(1)}><Plus size={16} /></button>
      <button type="button" title="适配视图 (F)" aria-label="适配视图" disabled={disabled} onClick={() => actions?.fit()}><ArrowsOut size={16} /></button>
      <button type="button" title="重置视图" aria-label="重置视图" disabled={disabled} onClick={() => actions?.reset()}><ArrowClockwise size={16} /></button>
      <button type="button" title="清除选择 (Esc)" aria-label="清除选择" disabled={disabled} onClick={() => actions?.clearSelection()}><X size={16} /></button>
      <span className="view-cluster" aria-label="标准视图">
        {(["iso", "front", "right", "top"] as const).map((view) => (
          <button key={view} type="button" title={`${view} 视图`} disabled={disabled} onClick={() => actions?.setStandardView(view)}>{view === "iso" ? "ISO" : view === "front" ? "前" : view === "right" ? "右" : "俯"}</button>
        ))}
      </span>
      <button type="button" title="透视/正交相机" aria-label="透视/正交相机" disabled={disabled || mode !== "mesh" || !actions?.toggleProjection} onClick={() => actions?.toggleProjection?.()}><Eye size={16} /></button>
      <span className="preview-mode-chip"><CubeFocus size={15} /> {mode === "dxf" ? "DXF 场景" : mode === "mesh" ? "Three.js 网格" : mode === "image" ? "图像回退" : "预览"}</span>
      <span className="preview-mode-chip"><Stack size={15} /> {projection === "orthographic" ? "正交" : "透视"}</span>
      <span className="preview-mode-chip"><Selection size={15} /> F / 1-6 / Esc</span>
    </div>
  );
}
