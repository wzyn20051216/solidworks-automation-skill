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
    title: "交付测试",
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
  it("不会把本轮未变化的文件计为可交付产物", () => {
    const assessment = assessDelivery(jobWithArtifacts([
      { kind: "step", path: "old.step", exists: true, producedThisRun: false },
    ]));

    expect(assessment.disposition).toBe("failed");
    expect(assessment.readyArtifacts).toBe(0);
    expect(assessment.issues.join(" ")).toContain("不是本轮生成");
  });

  it("把 null 和缺失的新鲜度标记视为待复核", () => {
    for (const producedThisRun of [null, undefined]) {
      const assessment = assessDelivery(jobWithArtifacts([
        { kind: "step", path: "unknown.step", exists: true, producedThisRun },
      ]));

      expect(assessment.disposition).toBe("review_required");
      expect(assessment.readyArtifacts).toBe(0);
      expect(assessment.issues.join(" ")).toContain("无法确认");
    }
  });

  it("只有明确标记为本轮生成的文件才能满足格式交付", () => {
    const artifacts: ArtifactRecord[] = [
      { kind: "step", path: "fresh.step", exists: true, producedThisRun: true },
    ];

    expect(deliveryFormatStatus("STEP", jobWithArtifacts(artifacts), artifacts)).toBe("ready");
    expect(assessDelivery(jobWithArtifacts(artifacts)).disposition).toBe("ready");
    expect(deliveryFormatStatus("STEP", jobWithArtifacts([
      { kind: "step", path: "unknown.step", exists: true, producedThisRun: null },
    ]), [{ kind: "step", path: "unknown.step", exists: true, producedThisRun: null }])).toBe("missing");
  });

  it("预览清单从源文件继承新鲜度，不按 schema 版本自动伪造", () => {
    const job = jobWithArtifacts([
      { kind: "step", path: "old.step", exists: true, producedThisRun: false },
    ]);
    job.previewManifest = "preview.scene.json";

    const preview = collectJobArtifacts(job).find((artifact) => artifact.kind === "preview_manifest");

    expect(preview?.producedThisRun).toBe(false);
  });
});
