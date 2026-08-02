import type { PreviewMode } from "./previewTypes";

export function extensionOf(path?: string) {
  return path?.split(/[.?]/).pop()?.toLowerCase() ?? "";
}

export function dirnameOf(path?: string) {
  if (!path) return "";
  const index = Math.max(path.lastIndexOf("/"), path.lastIndexOf("\\"));
  return index >= 0 ? path.slice(0, index) : "";
}

export function resolveSiblingPath(basePath: string | undefined, nextPath: string | undefined) {
  if (!nextPath) return "";
  if (/^(https?:|asset:|data:|blob:)/i.test(nextPath) || /^[A-Za-z]:[\\/]/.test(nextPath) || nextPath.startsWith("/")) return nextPath;
  const base = dirnameOf(basePath);
  if (!base) return nextPath;
  return `${base}${base.includes("\\") ? "\\" : "/"}${nextPath}`;
}

export function modeForPath(path?: string): PreviewMode {
  if (path?.toLowerCase().split(/[?#]/)[0].endsWith(".scene.json")) return "dxf";
  const ext = extensionOf(path);
  if (["stl", "glb", "gltf", "obj"].includes(ext)) return "mesh";
  if (ext === "dxf") return "dxf";
  if (ext === "json") return "manifest";
  if (["png", "jpg", "jpeg", "webp", "bmp", "gif", "svg"].includes(ext)) return "image";
  return "unsupported";
}

export function mimeType(path?: string) {
  const extension = extensionOf(path);
  if (extension === "stl") return "model/stl";
  if (extension === "glb") return "model/gltf-binary";
  if (extension === "gltf") return "model/gltf+json";
  if (extension === "obj") return "text/plain";
  if (extension === "dxf" || extension === "json") return "text/plain";
  if (extension === "svg") return "image/svg+xml";
  if (extension === "jpg" || extension === "jpeg") return "image/jpeg";
  return `image/${extension || "png"}`;
}

export function fileName(path?: string) {
  return path?.split(/[\\/]/).pop() || "未选择文件";
}

export function formatBounds(bounds?: { minX?: number; minY?: number; maxX?: number; maxY?: number }, units = "mm") {
  if (!bounds) return "";
  const width = Math.abs((bounds.maxX ?? 0) - (bounds.minX ?? 0));
  const height = Math.abs((bounds.maxY ?? 0) - (bounds.minY ?? 0));
  if (!Number.isFinite(width) || !Number.isFinite(height) || (width === 0 && height === 0)) return "";
  return `${width.toFixed(1)} × ${height.toFixed(1)} ${units}`;
}

export function hasWebGlSupport() {
  try {
    const canvas = document.createElement("canvas");
    return Boolean(window.WebGLRenderingContext && (canvas.getContext("webgl2") || canvas.getContext("webgl")));
  } catch {
    return false;
  }
}
