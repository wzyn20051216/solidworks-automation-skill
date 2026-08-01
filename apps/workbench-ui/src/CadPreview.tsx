import { WarningCircle } from "@phosphor-icons/react";
import { invoke } from "@tauri-apps/api/core";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { DxfViewport } from "./preview/DxfViewport";
import { ModelViewport } from "./preview/ModelViewport";
import { PreviewEvidencePanel } from "./preview/PreviewEvidencePanel";
import { PreviewInspector } from "./preview/PreviewInspector";
import { PreviewStatus } from "./preview/PreviewStatus";
import { PreviewToolbar } from "./preview/PreviewToolbar";
import type { PreviewActions, PreviewLayer, PreviewManifest, PreviewMode, PreviewPhase, PreviewSelection, PreviewStats } from "./preview/previewTypes";
import { fileName, mimeType, modeForPath, resolveSiblingPath } from "./preview/previewUtils";

export type CadPreviewArtifact = {
  path?: string;
  kind?: string;
  exists?: boolean;
  previewManifest?: string;
  sourceArtifact?: string;
  sourceBackend?: string;
  fallback?: string;
  isDemo?: boolean;
  sha256?: string;
};

type LoadedPreview = {
  url: string;
  path: string;
  mode: PreviewMode;
  manifest?: PreviewManifest | null;
  revoke?: () => void;
};

function isLocalRuntime() {
  return "__TAURI_INTERNALS__" in window;
}

async function readPreviewUrl(path: string) {
  if (/^(https?:|asset:|data:|blob:)/i.test(path) || !isLocalRuntime()) return { url: path, revoke: undefined };
  const payload = await invoke<ArrayBuffer | number[]>("read_preview_file", { path });
  const bytes = payload instanceof ArrayBuffer ? payload : new Uint8Array(payload);
  const objectUrl = URL.createObjectURL(new Blob([bytes], { type: mimeType(path) }));
  return { url: objectUrl, revoke: () => URL.revokeObjectURL(objectUrl) };
}

async function readPreviewText(path: string) {
  const { url, revoke } = await readPreviewUrl(path);
  try {
    const response = await fetch(url);
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return await response.text();
  } finally {
    revoke?.();
  }
}

function manifestFromArtifact(artifact?: CadPreviewArtifact): PreviewManifest | null {
  if (!artifact) return null;
  return {
    previewVersion: "1.0",
    sourceArtifact: artifact.sourceArtifact || artifact.path,
    previewArtifact: artifact.path,
    fallbackImage: artifact.fallback,
    mode: artifact.isDemo ? "demo-showcase" : "delivery-preview",
    isDemo: artifact.isDemo,
    units: "mm",
    sha256: artifact.sha256,
    limitations: artifact.isDemo ? ["演示预览不能作为本轮交付证据"] : [],
  };
}

/** @brief CAD 交付预览调度层，统一模型、DXF、图片和预览清单。 */
export function CadPreview({ artifact }: { artifact?: CadPreviewArtifact }) {
  const actionsRef = useRef<PreviewActions | null>(null);
  const dxfActionsRef = useRef<PreviewActions | null>(null);
  const modelActionsRef = useRef<PreviewActions | null>(null);
  const [loaded, setLoaded] = useState<LoadedPreview | null>(null);
  const [phase, setPhase] = useState<PreviewPhase>("等待文件");
  const [message, setMessage] = useState("选择 STL、GLB、GLTF、OBJ、DXF、预览清单或图片产物后显示预览");
  const [selection, setSelection] = useState<PreviewSelection | null>(null);
  const [stats, setStats] = useState<PreviewStats>({});
  const [layers, setLayers] = useState<PreviewLayer[]>([]);
  const [visibleLayers, setVisibleLayers] = useState<Set<string>>(new Set());
  const [projection, setProjection] = useState<"perspective" | "orthographic">("perspective");
  const effectiveMode = loaded?.mode ?? modeForPath(artifact?.path);
  const ready = phase === "可交互";

  const setPreviewPhase = useCallback((next: string, detail = "") => {
    setPhase(next as PreviewPhase);
    setMessage(detail || next);
  }, []);

  useEffect(() => {
    let disposed = false;
    let revoke: (() => void) | undefined;
    setLoaded(null);
    setSelection(null);
    setStats({});
    setLayers([]);
    setVisibleLayers(new Set());
    actionsRef.current = null;
    const sourcePath = artifact?.previewManifest || artifact?.path;
    if (!sourcePath || artifact?.exists === false) {
      setPreviewPhase("等待文件", artifact?.exists === false ? "文件缺失，不能预览。" : "等待选择产物。");
      return;
    }
    const load = async () => {
      try {
        setPreviewPhase("正在读取文件", fileName(sourcePath));
        let manifest = manifestFromArtifact(artifact);
        let displayPath = artifact?.path || sourcePath;
        if (artifact?.previewManifest || modeForPath(sourcePath) === "manifest") {
          const raw = await readPreviewText(sourcePath);
          manifest = { ...manifest, ...(JSON.parse(raw) as PreviewManifest) };
          displayPath = resolveSiblingPath(sourcePath, manifest.previewArtifact || manifest.fallbackImage || artifact?.path || sourcePath);
        }
        let mode = modeForPath(displayPath);
        if (mode === "unsupported" && manifest?.fallbackImage) {
          displayPath = resolveSiblingPath(sourcePath, manifest.fallbackImage);
          mode = modeForPath(displayPath);
        }
        const loadedUrl = await readPreviewUrl(displayPath);
        revoke = loadedUrl.revoke;
        if (!disposed) {
          setLoaded({ url: loadedUrl.url, path: displayPath, mode, manifest, revoke });
          setPreviewPhase(mode === "image" ? "可交互" : "正在解码", mode === "image" ? "图像回退预览已就绪" : fileName(displayPath));
        }
      } catch (error) {
        if (!disposed) setPreviewPhase("预览失败", (error as Error).message);
      }
    };
    void load();
    return () => { disposed = true; revoke?.(); };
  }, [artifact, setPreviewPhase]);

  useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      if (!actionsRef.current) return;
      if (event.key === "f" || event.key === "F") actionsRef.current.fit();
      if (event.key === "Escape") actionsRef.current.clearSelection();
      const viewMap: Record<string, Parameters<PreviewActions["setStandardView"]>[0]> = { "1": "front", "2": "right", "3": "top", "4": "left", "5": "back", "6": "bottom" };
      if (viewMap[event.key]) actionsRef.current.setStandardView(viewMap[event.key]);
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, []);

  const manifest = loaded?.manifest;
  const layerNames = useMemo(() => new Set(layers.map((layer) => layer.name)), [layers]);
  useEffect(() => { setVisibleLayers(layerNames); }, [layerNames]);
  const activeActions = effectiveMode === "mesh" ? modelActionsRef.current : effectiveMode === "dxf" ? dxfActionsRef.current : null;
  actionsRef.current = activeActions;

  return (
    <section className="cad-preview mechanical-bench" aria-label="CAD 预览">
      <div className="cad-preview-heading">
        <div><span className="eyebrow">CAD INSPECTION BENCH</span><strong>{fileName(loaded?.path || artifact?.path)}</strong></div>
        <span className={`cad-preview-status ${phase === "可交互" ? "ready" : phase === "预览失败" ? "error" : "loading"}`}>{phase}</span>
      </div>
      <PreviewStatus phase={phase} message={message} manifest={manifest} />
      <div className="cad-preview-layout">
        <PreviewInspector
          artifactPath={loaded?.path || artifact?.path}
          manifest={manifest}
          stats={stats}
          selection={selection}
          layers={layers}
          visibleLayers={visibleLayers}
          onToggleLayer={(layer) => setVisibleLayers((current) => {
            const next = new Set(current);
            if (next.has(layer)) next.delete(layer); else next.add(layer);
            return next;
          })}
        />
        <div className="cad-preview-stage">
          {loaded?.mode === "mesh" ? (
            <ModelViewport ref={modelActionsRef} url={loaded.url} path={loaded.path} onPhase={setPreviewPhase} onSelection={setSelection} onStats={setStats} onProjection={setProjection} />
          ) : loaded?.mode === "dxf" ? (
            <DxfViewport ref={dxfActionsRef} url={loaded.url} visibleLayers={visibleLayers} onLayers={setLayers} onStats={setStats} onPhase={setPreviewPhase} onSelection={setSelection} />
          ) : loaded?.mode === "image" ? (
            <img src={loaded.url} alt={fileName(loaded.path)} />
          ) : (
            <div className="cad-preview-empty"><WarningCircle size={22} /><span>{message}</span></div>
          )}
          {phase === "预览失败" ? <div className="cad-preview-error">{message}</div> : null}
        </div>
        <PreviewEvidencePanel manifest={manifest} selection={selection} />
      </div>
      <PreviewToolbar ready={ready} mode={effectiveMode} projection={projection} actions={activeActions} />
    </section>
  );
}
