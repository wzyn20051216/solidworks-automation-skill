import type { ArtifactRecord, AutomationJob } from "../types";

export const deliveryFileExtensions = new Set([
  ".sldprt", ".sldasm", ".slddrw",
  ".step", ".stp", ".iges", ".igs", ".brep",
  ".stl", ".obj", ".glb", ".gltf",
  ".dxf", ".dwg", ".pdf", ".png", ".svg", ".bmp", ".jpg", ".jpeg", ".webp", ".csv",
]);

export function artifactRequiresCurrentRunProof(artifact: ArtifactRecord) {
  const match = (artifact.path ?? "").toLowerCase().match(/\.[^.\\/]+$/);
  return Boolean(match && deliveryFileExtensions.has(match[0]));
}

export function fileNameFromPath(path?: string) {
  if (!path) return "Adsız dosya";
  return path.split(/[\\/]/).pop() || path;
}

export function artifactKindLabel(kind?: string, path?: string) {
  const normalized = (kind || fileNameFromPath(path).split(".").pop() || "artifact").toLowerCase();
  if (normalized.includes("sldprt")) return "SolidWorks parçası";
  if (normalized.includes("sldasm")) return "SolidWorks montajı";
  if (normalized.includes("step") || normalized.includes("stp")) return "STEP";
  if (normalized.includes("stl")) return "STL";
  if (normalized.includes("dwg")) return "DWG";
  if (normalized.includes("dxf")) return "DXF";
  if (normalized.includes("pdf")) return "PDF";
  if (normalized.includes("dfm")) return "DFM inceleme raporu";
  if (normalized.includes("png") || normalized.includes("preview")) return "Önizleme görseli";
  if (normalized.includes("codex")) return "AI sonucu";
  return kind || "Teslimat";
}

export type ArtifactGroup = "model" | "drawing" | "bom" | "preview" | "report" | "other";

export function artifactGroup(artifact: ArtifactRecord): ArtifactGroup {
  const text = `${artifact.kind ?? ""} ${artifact.path ?? ""}`.toLowerCase();
  if (/sldprt|sldasm|step|stp|stl|obj|glb|gltf/.test(text)) return "model";
  if (/slddrw|dwg|dxf/.test(text)) return "drawing";
  if (/bom|bill|物料|malzeme/.test(text)) return "bom";
  if (/png|bmp|jpg|jpeg|webp|preview|预览|önizleme/.test(text)) return "preview";
  if (/review|report|ledger|dfm|复核|报告|inceleme|rapor/.test(text)) return "report";
  return "other";
}

export function groupedArtifacts(artifacts: ArtifactRecord[]): Record<ArtifactGroup, ArtifactRecord[]> {
  const groups: Record<ArtifactGroup, ArtifactRecord[]> = { model: [], drawing: [], bom: [], preview: [], report: [], other: [] };
  for (const artifact of artifacts) groups[artifactGroup(artifact)].push(artifact);
  return groups;
}

export function formatBytes(value?: number) {
  if (!value || value <= 0) return "";
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / 1024 / 1024).toFixed(1)} MB`;
}

export function artifactStatusLabel(artifact: ArtifactRecord) {
  if (artifact.exists === false) return "Eksik";
  if (artifact.isDirectory) return "Dizin";
  if (artifact.producedThisRun === true) return "Bu çalıştırmada üretildi";
  if (artifact.producedThisRun === false) return "Bu çalıştırmaya ait değil";
  if (artifact.exists) return "Güncelliği doğrulanmadı";
  return "Doğrulama bekliyor";
}

export function deliveryFormatStatus(format: string, job: AutomationJob | undefined, artifacts: ArtifactRecord[]) {
  if (format === "İnceleme raporu") return job?.reviewGatePath ? "ready" : job ? "missing" : "optional";
  if (format === "DFM raporu") {
    const ready = artifacts.some((artifact) => artifact.kind?.toLowerCase().includes("dfm") && artifact.exists !== false && artifact.producedThisRun === true);
    return ready ? "ready" : job?.dfmEvidence ? "missing" : "optional";
  }
  const extensionMap: Record<string, string[]> = {
    STEP: [".step", ".stp"], STL: [".stl"], SLDPRT: [".sldprt"], SLDASM: [".sldasm"],
    SLDDRW: [".slddrw"], IGES: [".iges", ".igs"], BREP: [".brep"], OBJ: [".obj"],
    GLB: [".glb"], GLTF: [".gltf"], DWG: [".dwg"], DXF: [".dxf"],
    PDF: [".pdf"], PNG: [".png"], SVG: [".svg"],
  };
  const extensions = extensionMap[format] ?? [];
  const ready = artifacts.some((artifact) => {
    const path = artifact.path?.toLowerCase() ?? "";
    return artifact.exists === true && artifact.producedThisRun === true && extensions.some((extension) => path.endsWith(extension));
  });
  if (ready) return "ready";
  return (job?.expectedOutput ?? "").toUpperCase().includes(format) ? "missing" : "optional";
}

/** @brief Görevin tüm kaynaklarındaki çıktıları birleştirir ve yola göre tekilleştirir; eski dosyaları otomatik olarak bu çalıştırmanın çıktısı saymaz. */
export function collectJobArtifacts(job?: AutomationJob): ArtifactRecord[] {
  if (!job) return [];
  const items: ArtifactRecord[] = [];
  const pushArtifact = (kind: string, path?: string, extra: Partial<ArtifactRecord> = {}) => {
    if (path) items.push({ kind, path, ...extra });
  };
  if (job.previewManifest && !job.artifacts?.some((artifact) => artifact.path === job.previewManifest)) {
    const source = job.artifacts?.find((artifact) => /\.(step|stp|stl|obj|glb|gltf|dxf|dwg|sldprt|sldasm)$/i.test(artifact.path ?? ""));
    pushArtifact("preview_manifest", job.previewManifest, {
      type: "preview",
      format: "json",
      sourceArtifact: source?.path,
      previewManifest: job.previewManifest,
      producedThisRun: source?.producedThisRun === false ? false : null,
    });
  }
  for (const artifact of job.artifacts ?? []) if (artifact?.path) items.push(artifact);
  if (job.result?.outputPath) {
    pushArtifact("codex_output", job.result.outputPath, {
      exists: true,
      producedThisRun: null,
    });
  }
  const outputs = job.result?.outputs;
  if (Array.isArray(outputs)) {
    outputs.forEach((item, index) => typeof item === "string" ? pushArtifact(`output_${index}`, item) : item?.path ? items.push(item) : undefined);
  } else if (outputs && typeof outputs === "object") {
    Object.entries(outputs).forEach(([kind, path]) => pushArtifact(kind, path));
  }
  const seen = new Set<string>();
  return items.filter((item) => {
    const key = item.path || `${item.kind}-${seen.size}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}
