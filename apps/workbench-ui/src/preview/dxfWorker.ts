import type { PreviewEntity, PreviewLayer, PreviewScene } from "./previewTypes";

type Pair = { code: string; value: string };

function numberValue(tags: Pair[], code: string) {
  const value = tags.find((tag) => tag.code === code)?.value;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : undefined;
}

function allNumberValues(tags: Pair[], code: string) {
  return tags.map((tag) => (tag.code === code ? Number(tag.value) : NaN)).filter(Number.isFinite);
}

function colorFromIndex(index?: number) {
  const palette: Record<number, string> = { 1: "#c74343", 2: "#c9a227", 3: "#2f7d4f", 4: "#2687a7", 5: "#3454b4", 6: "#8a4fb8", 7: "#25312f" };
  return index ? palette[index] || "#176c65" : "#176c65";
}

function entityBBox(points: Array<[number, number]>) {
  if (!points.length) return undefined;
  return {
    minX: Math.min(...points.map(([x]) => x)),
    minY: Math.min(...points.map(([, y]) => y)),
    maxX: Math.max(...points.map(([x]) => x)),
    maxY: Math.max(...points.map(([, y]) => y)),
  };
}

function pushLayer(layers: Map<string, PreviewLayer>, name: string, color?: string) {
  const current = layers.get(name) || { name, color, count: 0, visible: true };
  current.count = (current.count || 0) + 1;
  current.color = current.color || color;
  layers.set(name, current);
}

function parseEntity(kind: string, tags: Pair[], index: number, layers: Map<string, PreviewLayer>): PreviewEntity | null {
  const layer = tags.find((tag) => tag.code === "8")?.value || "0";
  const color = colorFromIndex(numberValue(tags, "62"));
  const base = { id: `${kind.toLowerCase()}-${index}`, kind: kind.toLowerCase(), layer, color };
  let entity: PreviewEntity | null = null;
  if (kind === "LINE") {
    const x1 = numberValue(tags, "10"); const y1 = numberValue(tags, "20");
    const x2 = numberValue(tags, "11"); const y2 = numberValue(tags, "21");
    if ([x1, y1, x2, y2].every((value) => value !== undefined)) entity = { ...base, kind: "line", points: [[x1!, y1!], [x2!, y2!]] };
  } else if (kind === "CIRCLE" || kind === "ARC") {
    const cx = numberValue(tags, "10"); const cy = numberValue(tags, "20"); const radius = numberValue(tags, "40");
    if ([cx, cy, radius].every((value) => value !== undefined)) {
      const start = kind === "ARC" ? (numberValue(tags, "50") || 0) * Math.PI / 180 : 0;
      const end = kind === "ARC" ? (numberValue(tags, "51") || 360) * Math.PI / 180 : Math.PI * 2;
      const span = end >= start ? end - start : end + Math.PI * 2 - start;
      const points: Array<[number, number]> = [];
      for (let step = 0; step <= 48; step += 1) {
        const angle = start + (step / 48) * span;
        points.push([cx! + Math.cos(angle) * radius!, cy! + Math.sin(angle) * radius!]);
      }
      entity = { ...base, kind: kind === "ARC" ? "arc" : "circle", points };
    }
  } else if (kind === "LWPOLYLINE" || kind === "POLYLINE") {
    const xs = allNumberValues(tags, "10"); const ys = allNumberValues(tags, "20");
    const points = xs.map((x, itemIndex) => [x, ys[itemIndex]] as [number, number]).filter((point) => Number.isFinite(point[1]));
    if ((Number(numberValue(tags, "70") || 0) & 1) === 1 && points.length > 2) points.push(points[0]);
    if (points.length > 1) entity = { ...base, kind: "polyline", points };
  } else if (["TEXT", "MTEXT", "DIMENSION"].includes(kind)) {
    const x = numberValue(tags, "10"); const y = numberValue(tags, "20");
    const text = tags.find((tag) => tag.code === "1")?.value || tags.find((tag) => tag.code === "3")?.value || kind;
    if (x !== undefined && y !== undefined) entity = { ...base, kind: kind === "DIMENSION" ? "dimension" : "text", text, points: [[x, y]], bbox: { minX: x, minY: y, maxX: x, maxY: y } };
  }
  if (entity?.points) entity.bbox = entity.bbox || entityBBox(entity.points);
  if (entity) pushLayer(layers, layer, color);
  return entity;
}

function parseDxf(source: string): PreviewScene {
  const rows = source.replace(/\r/g, "").split("\n").map((value) => value.trim());
  const pairs: Pair[] = [];
  for (let index = 0; index < rows.length - 1; index += 2) pairs.push({ code: rows[index], value: rows[index + 1] });
  const entities: PreviewEntity[] = [];
  const layers = new Map<string, PreviewLayer>();
  let inEntities = false;
  for (let index = 0; index < pairs.length; index += 1) {
    const pair = pairs[index];
    if (pair.code === "0" && pair.value === "SECTION" && pairs[index + 1]?.code === "2" && pairs[index + 1]?.value === "ENTITIES") {
      inEntities = true;
      index += 1;
      continue;
    }
    if (pair.code === "0" && pair.value === "ENDSEC") {
      inEntities = false;
      continue;
    }
    if (!inEntities || pair.code !== "0") continue;
    const kind = pair.value;
    const tags: Pair[] = [];
    let cursor = index + 1;
    while (cursor < pairs.length && pairs[cursor].code !== "0") {
      tags.push(pairs[cursor]);
      cursor += 1;
    }
    const entity = parseEntity(kind, tags, entities.length, layers);
    if (entity) entities.push(entity);
    index = cursor - 1;
  }
  const boxes = entities.map((entity) => entity.bbox).filter(Boolean) as NonNullable<PreviewEntity["bbox"]>[];
  const bounds = boxes.length ? {
    minX: Math.min(...boxes.map((box) => box.minX)),
    minY: Math.min(...boxes.map((box) => box.minY)),
    maxX: Math.max(...boxes.map((box) => box.maxX)),
    maxY: Math.max(...boxes.map((box) => box.maxY)),
  } : undefined;
  return { schemaVersion: "1.0", kind: "dxf-scene", units: "mm", entities, layers: [...layers.values()], bounds, warnings: entities.length ? [] : ["未解析到可显示实体"] };
}

self.onmessage = (event: MessageEvent<string>) => {
  try {
    self.postMessage({ ok: true, scene: parseDxf(event.data) });
  } catch (error) {
    self.postMessage({ ok: false, error: (error as Error).message });
  }
};
