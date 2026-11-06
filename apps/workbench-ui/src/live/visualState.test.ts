import { describe, expect, it } from "vitest";
import type { AutomationJob, QueueEvent } from "../types";
import { deriveLiveVisual } from "./visualState";

function job(overrides: Partial<AutomationJob> = {}): AutomationJob {
  return {
    schemaVersion: "2.0",
    id: "job-visual",
    runId: "run-visual",
    kind: "agent_task",
    title: "阶梯轴可视化",
    detail: "SolidWorks",
    status: "running",
    progress: 30,
    stage: "executing",
    createdAt: "2026-11-06T00:00:00Z",
    updatedAt: "2026-11-06T00:00:01Z",
    requestedBy: "test",
    createdByAppVersion: "test",
    lastMessage: "正在执行",
    ...overrides,
  };
}

function visualEvent(
  type: string,
  data: Record<string, unknown>,
  progress = 30,
): QueueEvent {
  return {
    type,
    jobId: "job-visual",
    progress,
    message: String(data.message ?? data.title ?? ""),
    at: "2026-11-06T00:00:02Z",
    data,
  };
}

describe("deriveLiveVisual", () => {
  it("maps a running feature step to working", () => {
    const state = deriveLiveVisual(job(), [
      visualEvent("visual.step.started", {
        stepId: "feature-main-shaft",
        sequence: 3,
        phase: "feature",
        title: "生成主体阶梯轴",
        message: "正在旋转轮廓",
      }),
    ]);

    expect(state.status).toBe("working");
    expect(state.title).toBe("生成主体阶梯轴");
    expect(state.phase).toBe("feature");
    expect(state.sequence).toBe(3);
  });

  it("maps delivery completion to complete only for passed jobs", () => {
    const events = [
      visualEvent(
        "visual.delivery.ready",
        {
          stepId: "delivery-ready",
          phase: "delivery",
          title: "交付文件已生成",
          message: "模型与 STEP 已保存",
        },
        100,
      ),
    ];

    expect(deriveLiveVisual(job({ status: "passed", progress: 100 }), events).status).toBe(
      "complete",
    );
    expect(
      deriveLiveVisual(job({ status: "review_required", progress: 100 }), events).status,
    ).toBe("checking");
  });

  it("falls back to job state when visual events are absent", () => {
    expect(deriveLiveVisual(job({ status: "failed", lastMessage: "COM 失败" }), []).status).toBe(
      "warning",
    );
    expect(deriveLiveVisual(job({ status: "running", stage: "reviewing" }), []).status).toBe(
      "checking",
    );
  });

  it("keeps the latest snapshot path and stats", () => {
    const state = deriveLiveVisual(job(), [
      visualEvent("visual.step.completed", {
        stepId: "feature-main-shaft",
        sequence: 4,
        phase: "feature",
        title: "主体完成",
        message: "实体已重建",
        snapshotPath: "visual/job-visual/step-004-feature-main-shaft.png",
        stats: { volumeMm3: 28378.5, featureCount: 6 },
      }),
    ]);

    expect(state.snapshotPath).toContain("step-004-feature-main-shaft.png");
    expect(state.stats.volumeMm3).toBe(28378.5);
    expect(state.stats.featureCount).toBe(6);
  });

  it("uses the queue terminal state after the last save step", () => {
    const events = [
      visualEvent("visual.step.completed", {
        stepId: "delivery-model-save",
        sequence: 8,
        phase: "delivery",
        title: "保存 SolidWorks 模型",
        message: "模型已保存",
        snapshotPath: "visual/job-visual/step-008-delivery-model-save.png",
      }),
    ];

    expect(
      deriveLiveVisual(
        job({ status: "passed", progress: 100, stage: "delivery" }),
        events,
      ).status,
    ).toBe("complete");
    expect(
      deriveLiveVisual(
        job({ status: "review_required", progress: 100, stage: "reviewing" }),
        events,
      ).status,
    ).toBe("checking");
  });
});
