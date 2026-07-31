import { ArrowClockwise, ArrowsOut, CubeFocus, Minus, Plus, WarningCircle } from "@phosphor-icons/react";
import { invoke } from "@tauri-apps/api/core";
import { useEffect, useRef, useState } from "react";

export type CadPreviewArtifact = {
  path?: string;
  kind?: string;
  exists?: boolean;
};

type PreviewMode = "mesh" | "dxf" | "image" | "unsupported";

function extensionOf(path?: string) {
  return path?.split(/[.?]/).pop()?.toLowerCase() ?? "";
}

function modeFor(artifact?: CadPreviewArtifact): PreviewMode {
  const ext = extensionOf(artifact?.path);
  if (["stl", "glb", "gltf", "obj"].includes(ext)) return "mesh";
  if (ext === "dxf") return "dxf";
  if (["png", "jpg", "jpeg", "webp", "bmp", "gif"].includes(ext)) return "image";
  return "unsupported";
}

function mimeType(path?: string) {
  const extension = extensionOf(path);
  if (extension === "stl") return "model/stl";
  if (extension === "glb") return "model/gltf-binary";
  if (extension === "gltf") return "model/gltf+json";
  if (extension === "obj") return "text/plain";
  if (extension === "dxf") return "text/plain";
  if (extension === "jpg" || extension === "jpeg") return "image/jpeg";
  return `image/${extension || "png"}`;
}

function fileName(path?: string) {
  return path?.split(/[\\/]/).pop() || "未选择文件";
}

type DxfEntity = { kind: "line" | "circle" | "polyline"; points: Array<[number, number]> };

function parseDxf(source: string): DxfEntity[] {
  const rows = source.replace(/\r/g, "").split("\n").map((value) => value.trim());
  const entities: DxfEntity[] = [];
  let section = "";
  for (let index = 0; index < rows.length - 1; index += 2) {
    const code = rows[index];
    const value = rows[index + 1];
    if (code === "0" && value === "SECTION") {
      section = rows[index + 3] || "";
      index += 2;
      continue;
    }
    if (code === "0" && value === "ENDSEC") {
      section = "";
      continue;
    }
    if (section !== "ENTITIES" || code !== "0") continue;
    if (value === "LINE") {
      const values: Record<string, number> = {};
      for (let cursor = index + 2; cursor < rows.length - 1 && rows[cursor] !== "0"; cursor += 2) values[rows[cursor]] = Number(rows[cursor + 1]);
      if (["10", "20", "11", "21"].every((key) => Number.isFinite(values[key]))) entities.push({ kind: "line", points: [[values["10"], values["20"]], [values["11"], values["21"]]] });
    } else if (value === "CIRCLE") {
      const values: Record<string, number> = {};
      for (let cursor = index + 2; cursor < rows.length - 1 && rows[cursor] !== "0"; cursor += 2) values[rows[cursor]] = Number(rows[cursor + 1]);
      if (["10", "20", "40"].every((key) => Number.isFinite(values[key]))) {
        const points: Array<[number, number]> = [];
        for (let step = 0; step <= 32; step += 1) {
          const angle = (step / 32) * Math.PI * 2;
          points.push([values["10"] + Math.cos(angle) * values["40"], values["20"] + Math.sin(angle) * values["40"]]);
        }
        entities.push({ kind: "circle", points });
      }
    } else if (value === "LWPOLYLINE") {
      const points: Array<[number, number]> = [];
      let closed = false;
      for (let cursor = index + 2; cursor < rows.length - 1 && rows[cursor] !== "0"; cursor += 2) {
        if (rows[cursor] === "70") closed = (Number(rows[cursor + 1]) & 1) === 1;
        if (rows[cursor] === "10" && Number.isFinite(Number(rows[cursor + 1])) && rows[cursor + 2] === "20") points.push([Number(rows[cursor + 1]), Number(rows[cursor + 3])]);
      }
      if (closed && points.length > 2) points.push(points[0]);
      if (points.length > 1) entities.push({ kind: "polyline", points });
    }
  }
  return entities;
}

function drawDxf(canvas: HTMLCanvasElement, entities: DxfEntity[]) {
  const width = canvas.clientWidth || 640;
  const height = canvas.clientHeight || 360;
  const ratio = window.devicePixelRatio || 1;
  canvas.width = width * ratio;
  canvas.height = height * ratio;
  const context = canvas.getContext("2d");
  if (!context) return;
  context.setTransform(ratio, 0, 0, ratio, 0, 0);
  context.fillStyle = "#f8faf7";
  context.fillRect(0, 0, width, height);
  const points = entities.flatMap((entity) => entity.points);
  if (points.length === 0) return;
  const minX = Math.min(...points.map(([x]) => x));
  const maxX = Math.max(...points.map(([x]) => x));
  const minY = Math.min(...points.map(([, y]) => y));
  const maxY = Math.max(...points.map(([, y]) => y));
  const scale = Math.min((width - 44) / Math.max(1, maxX - minX), (height - 44) / Math.max(1, maxY - minY));
  const project = ([x, y]: [number, number]) => [22 + (x - minX) * scale, height - 22 - (y - minY) * scale] as const;
  context.strokeStyle = "#176c65";
  context.lineWidth = 1.35;
  context.lineJoin = "round";
  entities.forEach((entity) => {
    context.beginPath();
    entity.points.forEach((point, index) => {
      const [x, y] = project(point);
      if (index === 0) context.moveTo(x, y); else context.lineTo(x, y);
    });
    context.stroke();
  });
}

export function CadPreview({ artifact }: { artifact?: CadPreviewArtifact }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const hostRef = useRef<HTMLDivElement>(null);
  const viewActionsRef = useRef<{ zoom: (direction: number) => void; reset: () => void } | null>(null);
  const [status, setStatus] = useState<"idle" | "loading" | "ready" | "empty" | "error">("idle");
  const [message, setMessage] = useState("");
  const [zoom, setZoom] = useState(1);
  const [url, setUrl] = useState("");
  const mode = modeFor(artifact);

  useEffect(() => {
    const path = artifact?.path;
    let objectUrl = "";
    let disposed = false;
    setUrl("");
    if (!path) return;
    if (/^(https?:|asset:|data:|blob:)/i.test(path)) {
      setUrl(path);
      return;
    }
    if (!("__TAURI_INTERNALS__" in window)) {
      setUrl(path);
      return;
    }
    invoke<ArrayBuffer | number[]>("read_preview_file", { path }).then((payload) => {
      if (disposed) return;
      const bytes = payload instanceof ArrayBuffer ? payload : new Uint8Array(payload);
      objectUrl = URL.createObjectURL(new Blob([bytes], { type: mimeType(path) }));
      setUrl(objectUrl);
    }).catch((error) => {
      if (!disposed) { setStatus("error"); setMessage(String(error)); }
    });
    return () => { disposed = true; if (objectUrl) URL.revokeObjectURL(objectUrl); };
  }, [artifact?.path]);

  useEffect(() => {
    let disposed = false;
    if (!artifact?.path || artifact.exists === false) {
      setStatus("empty");
      return;
    }
    setStatus("loading");
    setMessage("");
    setZoom(1);
    if (!url) return;
    if (mode === "dxf") {
      fetch(url).then((response) => response.ok ? response.text() : Promise.reject(new Error(`HTTP ${response.status}`))).then((source) => {
        if (disposed) return;
        const entities = parseDxf(source);
        if (canvasRef.current) drawDxf(canvasRef.current, entities);
        setStatus(entities.length ? "ready" : "empty");
        setMessage(entities.length ? `${entities.length} 个实体 · 只读预览` : "未解析到可显示的 LINE、CIRCLE 或 LWPOLYLINE");
      }).catch((error: Error) => { if (!disposed) { setStatus("error"); setMessage(`DXF 读取失败: ${error.message}`); } });
      return () => { disposed = true; };
    }
    if (mode !== "mesh" || !hostRef.current) {
      setStatus(mode === "image" ? "ready" : "empty");
      return () => { disposed = true; };
    }
    const host = hostRef.current;
    let renderer: import("three").WebGLRenderer | undefined;
    let animation = 0;
    let controls: import("three/examples/jsm/controls/OrbitControls.js").OrbitControls | undefined;
    let loadedObject: import("three").Object3D | undefined;
    let resizeObserver: ResizeObserver | undefined;
    import("three").then(async (THREE) => {
      const [{ OrbitControls }, { STLLoader }, { GLTFLoader }, { OBJLoader }] = await Promise.all([
        import("three/examples/jsm/controls/OrbitControls.js"),
        import("three/examples/jsm/loaders/STLLoader.js"),
        import("three/examples/jsm/loaders/GLTFLoader.js"),
        import("three/examples/jsm/loaders/OBJLoader.js"),
      ]);
      if (disposed) return;
      const scene = new THREE.Scene();
      scene.background = new THREE.Color("#f8faf7");
      const camera = new THREE.PerspectiveCamera(38, host.clientWidth / Math.max(1, host.clientHeight), 0.01, 10000);
      camera.position.set(2.8, 2.2, 3.2);
      renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
      renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
      renderer.setSize(host.clientWidth, host.clientHeight);
      host.replaceChildren(renderer.domElement);
      resizeObserver = new ResizeObserver(() => {
        if (!renderer || host.clientWidth <= 0 || host.clientHeight <= 0) return;
        camera.aspect = host.clientWidth / host.clientHeight;
        camera.updateProjectionMatrix();
        renderer.setSize(host.clientWidth, host.clientHeight);
      });
      resizeObserver.observe(host);
      const ambient = new THREE.HemisphereLight(0xffffff, 0x8a9d99, 2.2);
      scene.add(ambient);
      const key = new THREE.DirectionalLight(0xffffff, 2.4); key.position.set(4, 5, 6); scene.add(key);
      scene.add(new THREE.GridHelper(5, 10, 0xd6e2dc, 0xe7eee9));
      controls = new OrbitControls(camera, renderer.domElement);
      controls.enableDamping = true;
      const extension = extensionOf(artifact.path);
      try {
        let object: import("three").Object3D;
        if (extension === "stl") {
          const geometry = await new STLLoader().loadAsync(url);
          geometry.computeVertexNormals();
          object = new THREE.Mesh(geometry, new THREE.MeshStandardMaterial({ color: 0x3d8175, metalness: 0.18, roughness: 0.5 }));
        } else if (extension === "obj") object = await new OBJLoader().loadAsync(url);
        else object = (await new GLTFLoader().loadAsync(url)).scene;
        if (disposed) return;
        object.traverse((child) => { if ((child as import("three").Mesh).isMesh) { const mesh = child as import("three").Mesh; if (!mesh.material) mesh.material = new THREE.MeshStandardMaterial({ color: 0x3d8175 }); } });
        const box = new THREE.Box3().setFromObject(object);
        const center = box.getCenter(new THREE.Vector3());
        const size = box.getSize(new THREE.Vector3());
        const radius = Math.max(size.x, size.y, size.z, 0.01);
        object.position.sub(center);
        scene.add(object);
        loadedObject = object;
        camera.position.set(radius * 1.8, radius * 1.35, radius * 1.8);
        camera.near = radius / 1000; camera.far = radius * 100; camera.updateProjectionMatrix();
        controls.target.set(0, 0, 0); controls.update();
        controls.saveState();
        viewActionsRef.current = {
          zoom: (direction) => {
            camera.position.multiplyScalar(direction > 0 ? 0.84 : 1.18);
            controls?.update();
          },
          reset: () => controls?.reset(),
        };
        setStatus("ready");
        const tick = () => { if (disposed) return; controls?.update(); renderer?.render(scene, camera); animation = requestAnimationFrame(tick); };
        tick();
      } catch (error) { if (!disposed) { setStatus("error"); setMessage(`模型读取失败: ${(error as Error).message}`); } }
    }).catch((error: Error) => { if (!disposed) { setStatus("error"); setMessage(`预览引擎加载失败: ${error.message}`); } });
    return () => {
      disposed = true;
      viewActionsRef.current = null;
      cancelAnimationFrame(animation);
      resizeObserver?.disconnect();
      controls?.dispose();
      loadedObject?.traverse((child) => {
        const mesh = child as import("three").Mesh;
        mesh.geometry?.dispose();
        const materials = Array.isArray(mesh.material) ? mesh.material : mesh.material ? [mesh.material] : [];
        materials.forEach((material) => material.dispose());
      });
      renderer?.dispose();
      host.replaceChildren();
    };
  }, [artifact?.exists, artifact?.path, mode, url]);

  const zoomImage = (direction: number) => setZoom((value) => Math.min(2.5, Math.max(0.65, value + direction * 0.15)));
  const zoomPreview = (direction: number) => mode === "mesh" ? viewActionsRef.current?.zoom(direction) : zoomImage(direction);
  const resetPreview = () => mode === "mesh" ? viewActionsRef.current?.reset() : setZoom(1);
  return (
    <section className="cad-preview" aria-label="CAD 预览">
      <div className="cad-preview-heading"><div><span className="eyebrow">LIVE PREVIEW</span><strong>{fileName(artifact?.path)}</strong></div><span className={`cad-preview-status ${status}`}>{status === "ready" ? "可预览" : status === "loading" ? "加载中" : status === "error" ? "预览失败" : "等待文件"}</span></div>
      <div className="cad-preview-stage">
        {mode === "mesh" ? <div ref={hostRef} className="cad-preview-canvas" /> : mode === "dxf" ? <canvas ref={canvasRef} className="cad-preview-dxf" style={{ transform: `scale(${zoom})` }} /> : mode === "image" && url ? <img src={url} alt={fileName(artifact?.path)} style={{ transform: `scale(${zoom})` }} /> : <div className="cad-preview-empty"><WarningCircle size={22} /><span>{message || "选择 STL、GLB、GLTF、OBJ、DXF 或图片产物后显示预览"}</span></div>}
        {status === "error" ? <div className="cad-preview-error">{message}</div> : null}
      </div>
      <div className="cad-preview-tools">
        <button type="button" title="缩小预览" aria-label="缩小预览" disabled={status !== "ready"} onClick={() => zoomPreview(-1)}><Minus size={16} /></button>
        <button type="button" title="适配视图" aria-label="适配视图" disabled={status !== "ready"} onClick={resetPreview}><ArrowsOut size={16} /></button>
        <button type="button" title="重置视图" aria-label="重置视图" disabled={status !== "ready"} onClick={resetPreview}><ArrowClockwise size={16} /></button>
        <button type="button" title="放大预览" aria-label="放大预览" disabled={status !== "ready"} onClick={() => zoomPreview(1)}><Plus size={16} /></button>
        <span><CubeFocus size={15} /> {mode === "dxf" ? "DXF 线稿" : mode === "mesh" ? "Three.js 网格" : "图像"}</span>
      </div>
    </section>
  );
}
