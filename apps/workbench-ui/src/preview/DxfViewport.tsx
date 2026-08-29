import { useEffect, useImperativeHandle, useRef, useState, forwardRef } from "react";
import type { PreviewActions, PreviewEntity, PreviewLayer, PreviewScene, PreviewSelection, PreviewStats } from "./previewTypes";
import { formatBounds } from "./previewUtils";

type DxfViewportProps = {
  url: string;
  visibleLayers: Set<string>;
  onLayers: (layers: PreviewLayer[]) => void;
  onStats: (stats: PreviewStats) => void;
  onPhase: (phase: string, message?: string) => void;
  onSelection: (selection: PreviewSelection | null) => void;
};

type Projection = { scale: number; minX: number; minY: number; height: number; padding: number };

function color(entity: PreviewEntity) {
  return entity.color || "#176c65";
}

function project(point: [number, number], projection: Projection) {
  return [projection.padding + (point[0] - projection.minX) * projection.scale, projection.height - projection.padding - (point[1] - projection.minY) * projection.scale] as const;
}

function drawScene(canvas: HTMLCanvasElement, scene: PreviewScene, visibleLayers: Set<string>, selectedId?: string) {
  const width = canvas.clientWidth || 640;
  const height = canvas.clientHeight || 360;
  const ratio = window.devicePixelRatio || 1;
  canvas.width = width * ratio;
  canvas.height = height * ratio;
  const context = canvas.getContext("2d");
  if (!context) return undefined;
  context.setTransform(ratio, 0, 0, ratio, 0, 0);
  context.fillStyle = "#f8faf7";
  context.fillRect(0, 0, width, height);
  const bounds = scene.bounds;
  if (!bounds) return undefined;
  const padding = 30;
  const scale = Math.min((width - padding * 2) / Math.max(1, bounds.maxX - bounds.minX), (height - padding * 2) / Math.max(1, bounds.maxY - bounds.minY));
  const projection = { scale, minX: bounds.minX, minY: bounds.minY, height, padding };
  context.lineJoin = "round";
  context.lineCap = "round";
  for (const entity of scene.entities) {
    if (entity.layer && !visibleLayers.has(entity.layer)) continue;
    context.save();
    context.strokeStyle = selectedId === entity.id ? "#d66b1f" : color(entity);
    context.fillStyle = selectedId === entity.id ? "#d66b1f" : color(entity);
    context.lineWidth = selectedId === entity.id ? 2.4 : entity.kind === "dimension" ? 1.1 : 1.35;
    if (entity.kind === "text" || entity.kind === "dimension") {
      const point = entity.points?.[0];
      if (point) {
        const [x, y] = project(point, projection);
        context.font = entity.kind === "dimension" ? "600 11px ui-monospace, Consolas" : "600 12px system-ui";
        context.fillText(entity.text || entity.kind, x, y);
      }
    } else if (entity.points?.length) {
      context.beginPath();
      entity.points.forEach((point, index) => {
        const [x, y] = project(point, projection);
        if (index === 0) context.moveTo(x, y); else context.lineTo(x, y);
      });
      context.stroke();
    }
    context.restore();
  }
  return projection;
}

function hitTest(scene: PreviewScene, projection: Projection, visibleLayers: Set<string>, x: number, y: number) {
  let best: { entity: PreviewEntity; distance: number } | undefined;
  for (const entity of scene.entities) {
    if (entity.layer && !visibleLayers.has(entity.layer)) continue;
    const points = entity.points ?? [];
    for (const point of points) {
      const [px, py] = project(point, projection);
      const distance = Math.hypot(px - x, py - y);
      if (distance < 10 && (!best || distance < best.distance)) best = { entity, distance };
    }
  }
  return best?.entity;
}

/** @brief DXF/PreviewScene 画布视口，解析工作在 Worker 中完成。 */
export const DxfViewport = forwardRef<PreviewActions, DxfViewportProps>(function DxfViewport({ url, visibleLayers, onLayers, onStats, onPhase, onSelection }, ref) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const projectionRef = useRef<Projection | undefined>(undefined);
  const [scene, setScene] = useState<PreviewScene | null>(null);
  const [selectedId, setSelectedId] = useState<string>();
  const [zoom, setZoom] = useState(1);

  useImperativeHandle(ref, () => ({
    zoom: (direction) => setZoom((value) => Math.min(2.8, Math.max(0.55, value + direction * 0.18))),
    fit: () => setZoom(1),
    reset: () => { setSelectedId(undefined); setZoom(1); onSelection(null); },
    setStandardView: () => setZoom(1),
    clearSelection: () => { setSelectedId(undefined); onSelection(null); },
  }), [onSelection]);

  useEffect(() => {
    let disposed = false;
    let activeWorker: Worker | undefined;
    onPhase("正在读取文件", "读取 DXF 或 PreviewScene JSON");
    fetch(url).then((response) => response.ok ? response.text() : Promise.reject(new Error(`HTTP ${response.status}`))).then((source) => {
      if (disposed) return;
      onPhase("正在解码", "DXF 解析已移入 Worker");
      if (source.trim().startsWith("{")) {
        const parsed = JSON.parse(source) as PreviewScene;
        setScene(parsed);
        onLayers(parsed.layers ?? []);
        onStats({ entityCount: parsed.entities?.length ?? 0, layerCount: parsed.layers?.length ?? 0, units: parsed.units || "mm", boundsLabel: formatBounds(parsed.bounds, parsed.units || "mm"), warnings: parsed.warnings });
        onPhase("可交互", `${parsed.entities?.length ?? 0} 个实体`);
        return;
      }
      const worker = new Worker(new URL("./dxfWorker.ts", import.meta.url), { type: "module" });
      activeWorker = worker;
      worker.onmessage = (event: MessageEvent<{ ok: boolean; scene?: PreviewScene; error?: string }>) => {
        worker.terminate();
        activeWorker = undefined;
        if (disposed) return;
        if (!event.data.ok || !event.data.scene) {
          onPhase("预览失败", event.data.error || "DXF 解析失败");
          return;
        }
        setScene(event.data.scene);
        onLayers(event.data.scene.layers);
        onStats({ entityCount: event.data.scene.entities.length, layerCount: event.data.scene.layers.length, units: event.data.scene.units || "mm", boundsLabel: formatBounds(event.data.scene.bounds, event.data.scene.units || "mm"), warnings: event.data.scene.warnings });
        onPhase("可交互", `${event.data.scene.entities.length} 个实体 · ${event.data.scene.layers.length} 个图层`);
      };
      worker.onerror = (error) => {
        worker.terminate();
        activeWorker = undefined;
        if (!disposed) onPhase("预览失败", error.message);
      };
      worker.postMessage(source);
    }).catch((error: Error) => { if (!disposed) onPhase("预览失败", `DXF 读取失败: ${error.message}`); });
    return () => {
      disposed = true;
      activeWorker?.terminate();
      activeWorker = undefined;
    };
  }, [onLayers, onPhase, onStats, url]);

  useEffect(() => {
    if (!canvasRef.current || !scene) return;
    projectionRef.current = drawScene(canvasRef.current, scene, visibleLayers, selectedId);
  }, [scene, selectedId, visibleLayers, zoom]);

  return (
    <canvas
      ref={canvasRef}
      className="cad-preview-dxf"
      style={{ transform: `scale(${zoom})` }}
      onClick={(event) => {
        if (!scene || !projectionRef.current) return;
        const rect = event.currentTarget.getBoundingClientRect();
        const entity = hitTest(scene, projectionRef.current, visibleLayers, event.clientX - rect.left, event.clientY - rect.top);
        setSelectedId(entity?.id);
        onSelection(entity ? { id: entity.id, name: entity.text || entity.id, type: entity.kind, layer: entity.layer, evidenceRefs: entity.evidenceRefs } : null);
      }}
    />
  );
});
