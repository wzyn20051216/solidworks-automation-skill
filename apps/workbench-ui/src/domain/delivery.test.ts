import { describe, expect, it } from "vitest";
import type { ArtifactRecord, AutomationJob } from "../types";
import { collectJobArtifacts, deliveryFormatStatus } from "./artifacts";
import { assessDelivery } from "./delivery";

function jobWithArtifacts(artifacts: ArtifactRecord[]): AutomationJob {
  return {
    schemaVersion: "2.0",
    id: "delivery-test",
    runId: "run-delivery-test",
    kind: "agent_task",
    title: "Teslimat testi",
    detail: "STEP",
    status: "passed",
    progress: 100,
    createdAt: "2026-10-30T00:00:00+08:00",
    updatedAt: "2026-10-30T00:00:00+08:00",
    requestedBy: "test",
    createdByAppVersion: "test",
    expectedOutput: "STEP",
    artifacts,
  };
}

describe("artifact freshness delivery gate", () => {
  it("var olmayan dosyaları yalnızca biçim işaretine bakarak hazır saymaz", () => {
    const artifacts: ArtifactRecord[] = [{ kind: "step", path: "absent.step", producedThisRun: true }];
    expect(deliveryFormatStatus("STEP", jobWithArtifacts(artifacts), artifacts)).toBe("missing");
  });

  it("bilinmeyen CAD dosyalarını kind alanına göre muaf tutmaz", () => {
    expect(assessDelivery(jobWithArtifacts([
      { kind: "engineering_plan", path: "unknown.step", exists: true, producedThisRun: null },
    ])).disposition).toBe("review_required");
  });

  it("karma teslimatta yeni dosyalar, varlığı bilinmeyen dosyaları gizleyemez", () => {
    const job = jobWithArtifacts([
      { kind: "step", path: "fresh.step", exists: true, producedThisRun: true },
      { kind: "step", path: "unverified.step", producedThisRun: true },
    ]);
    expect(assessDelivery(job).disposition).toBe("review_required");
    job.artifacts![1].producedThisRun = false;
    expect(assessDelivery(job).disposition).toBe("failed");
  });

  it("önizleme manifestosu yalnızca kaynak model güncel diye güncel sayılamaz ve gerçek defterin üzerine yazamaz", () => {
    const job = jobWithArtifacts([{ kind: "step", path: "fresh.step", exists: true, producedThisRun: true }]);
    job.previewManifest = "preview.json";
    expect(collectJobArtifacts(job).find((item) => item.path === "preview.json")?.producedThisRun).toBeNull();
    job.artifacts?.push({ kind: "preview_manifest", path: "preview.json", exists: true, producedThisRun: false });
    expect(collectJobArtifacts(job).find((item) => item.path === "preview.json")?.producedThisRun).toBe(false);
  });
  it("bu çalıştırmada değişmeyen dosyaları teslim edilebilir çıktı olarak saymaz", () => {
    const assessment = assessDelivery(jobWithArtifacts([
      { kind: "step", path: "old.step", exists: true, producedThisRun: false },
    ]));

    expect(assessment.disposition).toBe("failed");
    expect(assessment.readyArtifacts).toBe(0);
    expect(assessment.issues.join(" ")).toContain("bu çalıştırmada üretilmedi");
  });

  it("null ve eksik güncellik işaretlerini inceleme bekliyor olarak değerlendirir", () => {
    for (const producedThisRun of [null, undefined]) {
      const assessment = assessDelivery(jobWithArtifacts([
        { kind: "step", path: "unknown.step", exists: true, producedThisRun },
      ]));

      expect(assessment.disposition).toBe("review_required");
      expect(assessment.readyArtifacts).toBe(0);
      expect(assessment.issues.join(" ")).toContain("doğrulanamıyor");
    }
  });

  it("biçim teslimatını yalnızca bu çalıştırmada üretildiği açıkça işaretlenen dosyalar karşılayabilir", () => {
    const artifacts: ArtifactRecord[] = [
      { kind: "step", path: "fresh.step", exists: true, producedThisRun: true },
    ];

    expect(deliveryFormatStatus("STEP", jobWithArtifacts(artifacts), artifacts)).toBe("ready");
    expect(assessDelivery(jobWithArtifacts(artifacts)).disposition).toBe("ready");
    expect(deliveryFormatStatus("STEP", jobWithArtifacts([
      { kind: "step", path: "unknown.step", exists: true, producedThisRun: null },
    ]), [{ kind: "step", path: "unknown.step", exists: true, producedThisRun: null }])).toBe("missing");
  });

  it("önizleme manifestosu güncelliği kaynak dosyadan devralır, schema sürümüne göre otomatik uydurmaz", () => {
    const job = jobWithArtifacts([
      { kind: "step", path: "old.step", exists: true, producedThisRun: false },
    ]);
    job.previewManifest = "preview.scene.json";

    const preview = collectJobArtifacts(job).find((artifact) => artifact.kind === "preview_manifest");

    expect(preview?.producedThisRun).toBe(false);
  });
});
