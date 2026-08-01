import type { ArtifactRecord, AutomationJob } from "../types";

export function fileNameFromPath(path?: string) {
  if (!path) return "未命名文件";
  return path.split(/[\\/]/).pop() || path;
}

export function artifactKindLabel(kind?: string, path?: string) {
  const normalized = (kind || fileNameFromPath(path).split(".").pop() || "artifact").toLowerCase();
  if (normalized.includes("sldprt")) return "SolidWorks 零件";
  if (normalized.includes("sldasm")) return "SolidWorks 装配";
  if (normalized.includes("step") || normalized.includes("stp")) return "STEP";
  if (normalized.includes("stl")) return "STL";
  if (normalized.includes("dwg")) return "DWG";
  if (normalized.includes("dxf")) return "DXF";
  if (normalized.includes("pdf")) return "PDF";
  if (normalized.includes("png") || normalized.includes("preview")) return "预览图";
  if (normalized.includes("codex")) return "AI 结果";
  return kind || "交付物";
}

export type ArtifactGroup = "model" | "drawing" | "bom" | "preview" | "report" | "other";

export function artifactGroup(artifact: ArtifactRecord): ArtifactGroup {
  const text = `${artifact.kind ?? ""} ${artifact.path ?? ""}`.toLowerCase();
  if (/sldprt|sldasm|step|stp|stl|obj|glb|gltf/.test(text)) return "model";
  if (/slddrw|dwg|dxf/.test(text)) return "drawing";
  if (/bom|bill|物料/.test(text)) return "bom";
  if (/png|bmp|jpg|jpeg|webp|preview|预览/.test(text)) return "preview";
  if (/review|report|ledger|复核|报告/.test(text)) return "report";
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
  if (artifact.exists === false) return "缺失";
  if (artifact.isDirectory) return "目录";
  if (artifact.exists) return "已生成";
  return "待确认";
}

export function deliveryFormatStatus(format: string, job: AutomationJob | undefined, artifacts: ArtifactRecord[]) {
  if (format === "复核报告") return job?.reviewGatePath ? "ready" : job ? "missing" : "optional";
  const extensionMap: Record<string, string[]> = {
    STEP: [".step", ".stp"], STL: [".stl"], SLDPRT: [".sldprt"], SLDASM: [".sldasm"],
    DWG: [".dwg"], DXF: [".dxf"], PDF: [".pdf"], PNG: [".png"],
  };
  const extensions = extensionMap[format] ?? [];
  const ready = artifacts.some((artifact) => {
    const path = artifact.path?.toLowerCase() ?? "";
    return artifact.exists !== false && artifact.producedThisRun !== false && extensions.some((extension) => path.endsWith(extension));
  });
  if (ready) return "ready";
  return (job?.expectedOutput ?? "").toUpperCase().includes(format) ? "missing" : "optional";
}

/** @brief 合并任务各来源产物并按路径去重，不将旧文件自动视为本轮产物。 */
export function collectJobArtifacts(job?: AutomationJob): ArtifactRecord[] {
  if (!job) return [];
  const items: ArtifactRecord[] = [];
  const pushArtifact = (kind: string, path?: string, extra: Partial<ArtifactRecord> = {}) => {
    if (path) items.push({ kind, path, ...extra });
  };
  if (job.previewManifest) {
    const source = job.artifacts?.find((artifact) => /\.(step|stp|stl|obj|glb|gltf|dxf|dwg|sldprt|sldasm)$/i.test(artifact.path ?? ""));
    pushArtifact("preview_manifest", job.previewManifest, {
      type: "preview",
      format: "json",
      sourceArtifact: source?.path,
      previewManifest: job.previewManifest,
      exists: true,
      producedThisRun: job.schemaVersion !== "1.0",
    });
  }
  for (const artifact of job.artifacts ?? []) if (artifact?.path) items.push(artifact);
  if (job.result?.outputPath) {
    pushArtifact("codex_output", job.result.outputPath, {
      exists: true,
      producedThisRun: job.schemaVersion === "1.0" ? false : undefined,
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
