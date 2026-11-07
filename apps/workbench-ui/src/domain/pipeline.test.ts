import { describe, expect, it } from "vitest";
import {
  canRunStage,
  createEmptyPipeline,
  pipelineProgress,
  resolveStageState,
  stageStateForJob,
  summarizeRequirement,
} from "./pipeline";

describe("project pipeline", () => {
  it("从自然语言里提取尺寸、材料、工艺和输出", () => {
    const spec = summarizeRequirement(
      "做一个 120x80x12 的 6061 安装板，4个Ø9通孔，CNC 加工，输出 DWG 和 STEP",
    );
    expect(spec.dimensions).toBe("120 × 80 × 12 mm");
    expect(spec.material).toContain("6061");
    expect(spec.process).toContain("CNC");
    expect(spec.outputs).toContain("DWG");
    expect(spec.interfaces).toContain("Ø9");
  });

  it("需求未确认时不允许进入三维设计", () => {
    const pipeline = createEmptyPipeline("p1", "测试项目");
    pipeline.requirementText = "做一个安装板";
    expect(canRunStage(pipeline, "design").ok).toBe(false);
    pipeline.specConfirmedAt = new Date().toISOString();
    expect(canRunStage(pipeline, "design").ok).toBe(true);
  });

  it("识别中文数量词与四角孔，不产生 undefined", () => {
    const spec = summarizeRequirement(
      "做一个 120×80×12 的 6061 安装板，四角各一个 Ø9 通孔，孔心距边 15 mm，CNC 加工，出 DWG 和 PDF。",
    );
    expect(spec.interfaces).toContain("Ø9");
    expect(spec.interfaces).toContain("4 × Ø9");
    expect(spec.interfaces).not.toContain("undefined");
    expect(spec.interfaces).not.toContain("9 个");
  });

  it("三维设计未通过时不允许验证", () => {
    const pipeline = createEmptyPipeline("p1", "测试项目");
    pipeline.specConfirmedAt = new Date().toISOString();
    pipeline.stages.design = { state: "pending", jobId: "job-a" };
    const running = canRunStage(pipeline, "verify", { "job-a": { status: "running" } });
    expect(running.ok).toBe(false);
    const passed = canRunStage(pipeline, "verify", { "job-a": { status: "passed" } });
    expect(passed.ok).toBe(true);
  });

  it("验证未通过时不允许出工程图", () => {
    const pipeline = createEmptyPipeline("p1", "测试项目");
    pipeline.stages.verify = { state: "pending", jobId: "job-b" };
    expect(canRunStage(pipeline, "drawing", { "job-b": { status: "failed" } }).ok).toBe(false);
    expect(canRunStage(pipeline, "drawing", { "job-b": { status: "passed" } }).ok).toBe(true);
  });

  it("把任务状态映射为阶段状态", () => {
    expect(stageStateForJob("queued")).toBe("running");
    expect(stageStateForJob("running")).toBe("running");
    expect(stageStateForJob("passed")).toBe("passed");
    expect(stageStateForJob("review_required")).toBe("blocked");
    expect(stageStateForJob("failed")).toBe("failed");
    expect(stageStateForJob("cancelled")).toBe("failed");
  });

  it("按已通过阶段计算整体进度", () => {
    const pipeline = createEmptyPipeline("p1", "测试项目");
    pipeline.stages.requirements = { state: "passed" };
    pipeline.stages.summary = { state: "passed" };
    expect(pipelineProgress(pipeline)).toBe(40);
    expect(resolveStageState(pipeline, "summary")).toBe("passed");
  });
});
