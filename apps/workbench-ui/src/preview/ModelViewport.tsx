import { forwardRef, useEffect, useImperativeHandle, useRef } from "react";
import type { PreviewActions, PreviewSelection, PreviewStats } from "./previewTypes";
import { extensionOf, hasWebGlSupport } from "./previewUtils";

type StandardView = "iso" | "front" | "back" | "left" | "right" | "top" | "bottom";

type ModelViewportProps = {
  url: string;
  path?: string;
  onPhase: (phase: string, message?: string) => void;
  onSelection: (selection: PreviewSelection | null) => void;
  onStats: (stats: PreviewStats) => void;
  onProjection: (projection: "perspective" | "orthographic") => void;
  onFailure: (reason: string) => void;
};

function boundsLabel(size: { x: number; y: number; z: number }) {
  return `${size.x.toFixed(1)} × ${size.y.toFixed(1)} × ${size.z.toFixed(1)}`;
}

/** @brief Three.js 网格视口，采用按需渲染避免预览空转。 */
export const ModelViewport = forwardRef<PreviewActions, ModelViewportProps>(function ModelViewport({ url, path, onPhase, onSelection, onStats, onProjection, onFailure }, ref) {
  const hostRef = useRef<HTMLDivElement>(null);
  const actionsRef = useRef<PreviewActions | null>(null);

  useImperativeHandle(ref, () => ({
    zoom: (direction) => actionsRef.current?.zoom(direction),
    fit: () => actionsRef.current?.fit(),
    reset: () => actionsRef.current?.reset(),
    setStandardView: (view) => actionsRef.current?.setStandardView(view),
    clearSelection: () => actionsRef.current?.clearSelection(),
    toggleProjection: () => actionsRef.current?.toggleProjection?.(),
  }), []);

  useEffect(() => {
    const host = hostRef.current;
    if (!host) return;
    let disposed = false;
    let renderer: import("three").WebGLRenderer | undefined;
    let resizeObserver: ResizeObserver | undefined;
    let controls: import("three/examples/jsm/controls/OrbitControls.js").OrbitControls | undefined;
    let loadedObject: import("three").Object3D | undefined;
    let selectionHelper: import("three").BoxHelper | undefined;
    let cleanupMaterials: Array<() => void> = [];
    actionsRef.current = null;
    host.replaceChildren();
    onSelection(null);
    onPhase("正在检查", "检查 WebGL 能力");
    if (!hasWebGlSupport()) {
      const reason = "当前环境不支持 WebGL。";
      onFailure(reason);
      return;
    }
    onPhase("正在解码", "加载 Three.js 与模型解析器");
    import("three").then(async (THREE) => {
      const [{ OrbitControls }, { STLLoader }, { GLTFLoader }, { OBJLoader }] = await Promise.all([
        import("three/examples/jsm/controls/OrbitControls.js"),
        import("three/examples/jsm/loaders/STLLoader.js"),
        import("three/examples/jsm/loaders/GLTFLoader.js"),
        import("three/examples/jsm/loaders/OBJLoader.js"),
      ]);
      if (disposed) return;
      onPhase("正在建立场景", "构建机械检视台场景");
      const scene = new THREE.Scene();
      scene.background = new THREE.Color("#f8faf7");
      const perspective = new THREE.PerspectiveCamera(38, host.clientWidth / Math.max(1, host.clientHeight), 0.01, 100000);
      const orthographic = new THREE.OrthographicCamera(-1, 1, 1, -1, 0.01, 100000);
      let camera: import("three").PerspectiveCamera | import("three").OrthographicCamera = perspective;
      let projection: "perspective" | "orthographic" = "perspective";
      renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false, powerPreference: "high-performance" });
      renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
      renderer.setSize(host.clientWidth, host.clientHeight);
      host.replaceChildren(renderer.domElement);
      scene.add(new THREE.HemisphereLight(0xffffff, 0x7f8f8b, 2.2));
      const keyLight = new THREE.DirectionalLight(0xffffff, 2.4); keyLight.position.set(4, 5, 6); scene.add(keyLight);
      scene.add(new THREE.GridHelper(5, 10, 0xc8d7d1, 0xe4ece7));
      scene.add(new THREE.AxesHelper(1.2));
      controls = new OrbitControls(camera, renderer.domElement);
      controls.enableDamping = false;
      controls.enablePan = true;
      const render = () => renderer?.render(scene, camera);
      controls.addEventListener("change", render);
      resizeObserver = new ResizeObserver(() => {
        if (!renderer || host.clientWidth <= 0 || host.clientHeight <= 0) return;
        perspective.aspect = host.clientWidth / host.clientHeight;
        perspective.updateProjectionMatrix();
        const aspect = host.clientWidth / Math.max(1, host.clientHeight);
        const span = Math.max(1, controls?.target.length() || 1);
        orthographic.left = -span * aspect;
        orthographic.right = span * aspect;
        orthographic.top = span;
        orthographic.bottom = -span;
        orthographic.updateProjectionMatrix();
        renderer.setSize(host.clientWidth, host.clientHeight);
        render();
      });
      resizeObserver.observe(host);
      const extension = extensionOf(path);
      let object: import("three").Object3D;
      if (extension === "stl") {
        const geometry = await new STLLoader().loadAsync(url);
        geometry.computeVertexNormals();
        object = new THREE.Mesh(geometry, new THREE.MeshStandardMaterial({ color: 0x3d8175, metalness: 0.16, roughness: 0.52 }));
      } else if (extension === "obj") object = await new OBJLoader().loadAsync(url);
      else object = (await new GLTFLoader().loadAsync(url)).scene;
      if (disposed) {
        object.traverse((child) => {
          const mesh = child as import("three").Mesh;
          mesh.geometry?.dispose();
          const materials = Array.isArray(mesh.material) ? mesh.material : mesh.material ? [mesh.material] : [];
          materials.forEach((material) => material.dispose());
        });
        return;
      }
      let meshCount = 0;
      object.traverse((child) => {
        const mesh = child as import("three").Mesh;
        if (mesh.isMesh) {
          meshCount += 1;
          mesh.name = mesh.name || `Mesh ${meshCount}`;
          if (!mesh.material) mesh.material = new THREE.MeshStandardMaterial({ color: 0x3d8175, metalness: 0.1, roughness: 0.55 });
        }
      });
      const box = new THREE.Box3().setFromObject(object);
      const center = box.getCenter(new THREE.Vector3());
      const size = box.getSize(new THREE.Vector3());
      const radius = Math.max(size.x, size.y, size.z, 0.01);
      object.position.sub(center);
      scene.add(object);
      loadedObject = object;
      const setCameraPosition = (view: StandardView) => {
        const distance = radius * 2.35;
        const vectors: Record<StandardView, [number, number, number]> = {
          iso: [distance, distance * 0.72, distance], front: [0, 0, distance], back: [0, 0, -distance], left: [-distance, 0, 0], right: [distance, 0, 0], top: [0, distance, 0], bottom: [0, -distance, 0],
        };
        camera.position.set(...vectors[view]);
        camera.near = Math.max(radius / 1000, 0.001); camera.far = radius * 200; camera.updateProjectionMatrix();
        controls?.target.set(0, 0, 0); controls?.update(); render();
      };
      const fit = () => setCameraPosition("iso");
      const reset = () => { selectionHelper?.removeFromParent(); selectionHelper = undefined; onSelection(null); fit(); };
      const clearSelection = () => { selectionHelper?.removeFromParent(); selectionHelper = undefined; onSelection(null); render(); };
      const updateOrthographic = () => {
        const aspect = host.clientWidth / Math.max(1, host.clientHeight);
        orthographic.left = -radius * 1.35 * aspect;
        orthographic.right = radius * 1.35 * aspect;
        orthographic.top = radius * 1.35;
        orthographic.bottom = -radius * 1.35;
        orthographic.position.copy(perspective.position);
        orthographic.near = perspective.near;
        orthographic.far = perspective.far;
        orthographic.updateProjectionMatrix();
      };
      actionsRef.current = {
        zoom: (direction) => { camera.position.multiplyScalar(direction > 0 ? 0.84 : 1.18); controls?.update(); render(); },
        fit,
        reset,
        setStandardView: setCameraPosition,
        clearSelection,
        toggleProjection: () => {
          if (projection === "perspective") {
            updateOrthographic();
            camera = orthographic;
            projection = "orthographic";
          } else {
            perspective.position.copy(orthographic.position);
            camera = perspective;
            projection = "perspective";
          }
          controls?.dispose();
          controls = new OrbitControls(camera, renderer!.domElement);
          controls.enableDamping = false;
          controls.addEventListener("change", render);
          controls.target.set(0, 0, 0); controls.update();
          onProjection(projection); render();
        },
      };
      renderer.domElement.addEventListener("click", (event) => {
        const rect = renderer!.domElement.getBoundingClientRect();
        const pointer = new THREE.Vector2(((event.clientX - rect.left) / rect.width) * 2 - 1, -((event.clientY - rect.top) / rect.height) * 2 + 1);
        const raycaster = new THREE.Raycaster();
        raycaster.setFromCamera(pointer, camera);
        const hit = raycaster.intersectObjects([object], true)[0]?.object as import("three").Mesh | undefined;
        selectionHelper?.removeFromParent();
        if (!hit) { onSelection(null); render(); return; }
        selectionHelper = new THREE.BoxHelper(hit, 0xd66b1f); scene.add(selectionHelper);
        onSelection({ id: hit.uuid, name: hit.name || "Mesh", type: "mesh" });
        render();
      });
      renderer.domElement.addEventListener("dblclick", () => actionsRef.current?.fit());
      fit();
      controls.saveState();
      onStats({ meshCount, boundsLabel: boundsLabel(size), units: "mm" });
      onProjection(projection);
      onPhase("可交互", `${meshCount} 个网格 · 按需渲染`);
      render();
    }).catch((error: Error) => {
      if (!disposed) onFailure(`模型读取失败: ${error.message}`);
    });
    return () => {
      disposed = true;
      actionsRef.current = null;
      resizeObserver?.disconnect();
      controls?.dispose();
      selectionHelper?.removeFromParent();
      loadedObject?.traverse((child) => {
        const mesh = child as import("three").Mesh;
        mesh.geometry?.dispose();
        const materials = Array.isArray(mesh.material) ? mesh.material : mesh.material ? [mesh.material] : [];
        cleanupMaterials.push(...materials.map((material) => () => material.dispose()));
      });
      cleanupMaterials.forEach((cleanup) => cleanup());
      renderer?.dispose();
      host.replaceChildren();
    };
  }, [onFailure, onPhase, onProjection, onSelection, onStats, path, url]);

  return <div ref={hostRef} className="cad-preview-canvas" onContextMenu={(event) => event.preventDefault()} />;
});
