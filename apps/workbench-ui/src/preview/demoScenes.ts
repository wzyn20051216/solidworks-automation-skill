import type { PreviewEntity, PreviewLayer, PreviewScene } from "./previewTypes";

export type DemoSceneRecord = {
  id: string;
  label: string;
  scene: PreviewScene;
};

const layer = (name: string, color: string, count: number): PreviewLayer => ({ name, color, count, visible: true });

const line = (id: string, points: Array<[number, number]>, layerName: string, color: string, evidenceRefs: string[] = []): PreviewEntity => ({
  id,
  kind: "polyline",
  points,
  layer: layerName,
  color,
  evidenceRefs,
});

const circle = (id: string, center: [number, number], radius: number, layerName = "HOLES", color = "#176c65"): PreviewEntity => {
  const points: Array<[number, number]> = [];
  for (let index = 0; index <= 48; index += 1) {
    const angle = index / 48 * Math.PI * 2;
    points.push([center[0] + Math.cos(angle) * radius, center[1] + Math.sin(angle) * radius]);
  }
  return { id, kind: "circle", points, layer: layerName, color, evidenceRefs: [`feature:${id}`] };
};

const text = (id: string, value: string, point: [number, number], layerName = "TEXT", color = "#42514e"): PreviewEntity => ({
  id,
  kind: "text",
  text: value,
  points: [point],
  layer: layerName,
  color,
});

function scene(
  entities: PreviewEntity[],
  layers: PreviewLayer[],
  bounds: NonNullable<PreviewScene["bounds"]>,
  warnings: string[] = [],
): PreviewScene {
  return { schemaVersion: "1.0", kind: "preview-scene", units: "mm", entities, layers, bounds, warnings };
}

export const DEMO_SCENES: DemoSceneRecord[] = [
  {
    id: "installation-plate",
    label: "安装板",
    scene: scene(
      [
        line("plate-outline", [[0, 0], [120, 0], [120, 70], [0, 70], [0, 0]], "OUTLINE", "#25312f", ["feature:base"]),
        circle("hole-1", [15, 15], 4),
        circle("hole-2", [105, 15], 4),
        circle("hole-3", [105, 55], 4),
        circle("hole-4", [15, 55], 4),
        line("center-x", [[0, 35], [120, 35]], "CENTER", "#8a9a95"),
        line("center-y", [[60, 0], [60, 70]], "CENTER", "#8a9a95"),
      ],
      [layer("OUTLINE", "#25312f", 1), layer("HOLES", "#176c65", 4), layer("CENTER", "#8a9a95", 2)],
      { minX: -8, minY: -8, maxX: 128, maxY: 78 },
    ),
  },
  {
    id: "hole-bracket",
    label: "带孔支架",
    scene: scene(
      [
        line("bracket-outline", [[0, 0], [85, 0], [85, 18], [35, 18], [35, 62], [0, 62], [0, 0]], "OUTLINE", "#25312f"),
        circle("mount-a", [16, 14], 5),
        circle("mount-b", [68, 9], 4),
        circle("pivot", [17, 45], 8),
        line("datum-a", [[-4, 0], [92, 0]], "DATUM", "#b36b22"),
      ],
      [layer("OUTLINE", "#25312f", 1), layer("HOLES", "#176c65", 3), layer("DATUM", "#b36b22", 1)],
      { minX: -10, minY: -10, maxX: 98, maxY: 72 },
    ),
  },
  {
    id: "cpu-enclosure",
    label: "CPU 外壳",
    scene: scene(
      [
        line("shell", [[0, 0], [140, 0], [140, 90], [0, 90], [0, 0]], "OUTLINE", "#25312f"),
        line("io-cutout", [[12, 28], [12, 62], [28, 62], [28, 28], [12, 28]], "CUTOUT", "#176c65"),
        ...Array.from({ length: 7 }, (_, index) => line(`vent-${index + 1}`, [[52 + index * 9, 22], [52 + index * 9, 68]], "VENT", "#4f7770")),
        circle("post-1", [12, 12], 3.2, "POST"),
        circle("post-2", [128, 12], 3.2, "POST"),
        circle("post-3", [128, 78], 3.2, "POST"),
        circle("post-4", [12, 78], 3.2, "POST"),
      ],
      [layer("OUTLINE", "#25312f", 1), layer("CUTOUT", "#176c65", 1), layer("VENT", "#4f7770", 7), layer("POST", "#176c65", 4)],
      { minX: -10, minY: -10, maxX: 150, maxY: 100 },
    ),
  },
  {
    id: "mini-assembly",
    label: "小型装配体",
    scene: scene(
      [
        line("base", [[0, 0], [110, 0], [110, 28], [0, 28], [0, 0]], "BASE", "#25312f", ["component:base"]),
        line("slider", [[30, 28], [82, 28], [82, 50], [30, 50], [30, 28]], "COMPONENT", "#176c65", ["component:slider"]),
        circle("shaft-a", [18, 14], 8, "SHAFT"),
        circle("shaft-b", [94, 14], 8, "SHAFT"),
        line("mate-axis", [[18, 14], [94, 14]], "MATE", "#b36b22", ["mate:concentric"]),
      ],
      [layer("BASE", "#25312f", 1), layer("COMPONENT", "#176c65", 1), layer("SHAFT", "#176c65", 2), layer("MATE", "#b36b22", 1)],
      { minX: -10, minY: -10, maxX: 120, maxY: 62 },
    ),
  },
  {
    id: "gbt-drawing",
    label: "GB/T 图框",
    scene: scene(
      [
        line("border", [[0, 0], [210, 0], [210, 297], [0, 297], [0, 0]], "FRAME", "#25312f"),
        line("inner", [[20, 10], [200, 10], [200, 287], [20, 287], [20, 10]], "FRAME", "#25312f"),
        line("title-box", [[120, 10], [200, 10], [200, 48], [120, 48], [120, 10]], "TITLE", "#176c65"),
        line("title-row", [[120, 28], [200, 28]], "TITLE", "#176c65"),
        line("title-col", [[162, 10], [162, 48]], "TITLE", "#176c65"),
        text("drawing-title", "安装板", [126, 39]),
        text("scale", "比例 1:1", [166, 20]),
      ],
      [layer("FRAME", "#25312f", 2), layer("TITLE", "#176c65", 3), layer("TEXT", "#42514e", 2)],
      { minX: -8, minY: -8, maxX: 218, maxY: 305 },
      ["演示图框不替代企业模板或正式审图。"],
    ),
  },
  {
    id: "fea-cloud",
    label: "FEA 云图",
    scene: scene(
      [
        line("beam", [[0, 20], [120, 20], [120, 48], [0, 48], [0, 20]], "MODEL", "#25312f"),
        ...Array.from({ length: 12 }, (_, index) => line(`fea-band-${index}`, [[index * 10, 20], [index * 10 + 10, 48]], "RESULT", index < 4 ? "#315ca8" : index < 8 ? "#d1a62b" : "#c74343")),
        line("fixed", [[0, 12], [0, 56]], "CONSTRAINT", "#176c65"),
        line("load", [[110, 62], [110, 50]], "LOAD", "#c74343"),
        text("max-result", "MAX", [104, 55], "RESULT", "#c74343"),
      ],
      [layer("MODEL", "#25312f", 1), layer("RESULT", "#c74343", 13), layer("CONSTRAINT", "#176c65", 1), layer("LOAD", "#c74343", 1)],
      { minX: -12, minY: 0, maxX: 132, maxY: 72 },
      ["演示云图不是求解结果，不得用于安全判断。"],
    ),
  },
  {
    id: "routing-path",
    label: "Routing 路径",
    scene: scene(
      [
        line("route-main", [[8, 14], [36, 14], [36, 46], [78, 46], [78, 22], [118, 22]], "ROUTE", "#176c65", ["route:main"]),
        circle("endpoint-a", [8, 14], 4, "ENDPOINT", "#b36b22"),
        circle("endpoint-b", [118, 22], 4, "ENDPOINT", "#b36b22"),
        circle("support-a", [36, 30], 3, "SUPPORT", "#4f7770"),
        circle("support-b", [78, 34], 3, "SUPPORT", "#4f7770"),
        line("clearance-zone", [[48, 30], [68, 30], [68, 60], [48, 60], [48, 30]], "CLEARANCE", "#c74343"),
      ],
      [layer("ROUTE", "#176c65", 1), layer("ENDPOINT", "#b36b22", 2), layer("SUPPORT", "#4f7770", 2), layer("CLEARANCE", "#c74343", 1)],
      { minX: -4, minY: 0, maxX: 130, maxY: 70 },
      ["Routing 当前为演示路径，不代表已生成原生管路或线束。"],
    ),
  },
];
