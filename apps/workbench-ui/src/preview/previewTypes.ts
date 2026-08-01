export type PreviewMode = "mesh" | "dxf" | "image" | "manifest" | "unsupported";
export type PreviewPhase = "等待文件" | "正在检查" | "正在读取文件" | "正在解码" | "正在建立场景" | "可交互" | "预览失败";
export type PreviewSourceMode = "delivery-preview" | "demo-showcase";

export type PreviewManifest = {
  previewVersion?: "1.0" | string;
  sourceArtifact?: string;
  previewArtifact?: string;
  fallbackImage?: string;
  mode?: PreviewSourceMode;
  isDemo?: boolean;
  units?: string;
  bounds?: Record<string, unknown>;
  camera?: Record<string, unknown>;
  entities?: PreviewEntity[];
  layers?: PreviewLayer[];
  evidenceRefs?: string[];
  generatedAt?: string;
  sha256?: string;
  limitations?: string[];
};

export type PreviewLayer = {
  name: string;
  color?: string;
  count?: number;
  visible?: boolean;
};

export type PreviewEntity = {
  id: string;
  kind: "line" | "circle" | "arc" | "polyline" | "text" | "dimension" | "mesh" | string;
  layer?: string;
  color?: string;
  points?: Array<[number, number]>;
  text?: string;
  bbox?: { minX: number; minY: number; maxX: number; maxY: number };
  evidenceRefs?: string[];
};

export type PreviewScene = {
  schemaVersion?: "1.0" | string;
  kind?: "dxf-scene" | "preview-scene" | string;
  units?: string;
  bounds?: { minX: number; minY: number; maxX: number; maxY: number };
  entities: PreviewEntity[];
  layers: PreviewLayer[];
  warnings?: string[];
};

export type PreviewSelection = {
  id: string;
  name: string;
  type: string;
  layer?: string;
  evidenceRefs?: string[];
};

export type PreviewStats = {
  entityCount?: number;
  layerCount?: number;
  meshCount?: number;
  boundsLabel?: string;
  units?: string;
  warnings?: string[];
};

export type PreviewActions = {
  zoom: (direction: number) => void;
  fit: () => void;
  reset: () => void;
  setStandardView: (view: "iso" | "front" | "back" | "left" | "right" | "top" | "bottom") => void;
  clearSelection: () => void;
  toggleProjection?: () => void;
};
