import { describe, expect, it } from "vitest";
import type { AutomationJob, EngineeringReviewPhase, ProjectRecord } from "../types";
import { chatInputRevision, engineeringInputRevision, jobInputChange, recordChatChange, restoreQueuedChatChanges, restoreStageReview, stagesNeedingReview, updateStageReview } from "./stageReview";

const inputs = { objective: "生成装配体", length: 100, width: 80, height: 60, wallThickness: 2 };
const phases: EngineeringReviewPhase[] = [
  { id: "drawing-bom", depends_on: ["assembly-mates"] },
  { id: "requirements", depends_on: [] },
  { id: "independent", depends_on: ["requirements"] },
  { id: "assembly-mates", depends_on: ["part-modeling"] },
  { id: "part-modeling", depends_on: ["requirements"] },
];
const legacyJob: AutomationJob = {
  schemaVersion: "2.0",
  id: "test-job",
  runId: "test-run",
  kind: "agent_task",
  title: "生成装配体",
  detail: "",
  status: "passed",
  progress: 100,
  createdAt: "",
  updatedAt: "",
  requestedBy: "test",
  createdByAppVersion: "test",
};

describe("项目阶段复核", () => {
  it("关键尺寸只使建模及其传递后继进入待复核", () => {
    const review = updateStageReview(undefined, { width: 90 }, inputs);
    const change = jobInputChange(legacyJob, review);
    expect(change?.roots).toEqual(["part-modeling"]);
    expect([...stagesNeedingReview(phases, change)].map((phase) => phase.id))
      .toEqual(["drawing-bom", "assembly-mates", "part-modeling"]);
  });

  it("旧计划缺依赖时保守地标记该阶段及其后继", () => {
    const legacyPhases = [...phases, { id: "legacy" }, { id: "legacy-child", depends_on: ["legacy"] }];
    const affected = [...stagesNeedingReview(legacyPhases, { reason: "", roots: ["part-modeling"] })].map((phase) => phase.id);
    expect(affected).toContain("legacy");
    expect(affected).toContain("legacy-child");
    expect(affected).not.toContain("requirements");
  });

  it("需求变化要求复核全部阶段，后续尺寸变化保留上次需求版本", () => {
    const first = updateStageReview(undefined, { objective: "改成联动装配体" }, inputs);
    const second = updateStageReview(first, { wallThickness: 3 }, inputs);
    expect(stagesNeedingReview(phases, jobInputChange(legacyJob, second)).size).toBe(phases.length);
    const newerJob = { ...legacyJob, uiConfig: { engineeringInputRevision: engineeringInputRevision(first) } };
    expect(jobInputChange(newerJob, second)?.roots).toEqual(["part-modeling"]);
  });

  it("未修改、无效值和需求首尾空格不使旧结果失效", () => {
    expect(updateStageReview(undefined, { length: 100, height: -1, width: Infinity }, inputs)).toBeUndefined();
    expect(jobInputChange(legacyJob, undefined)).toBeNull();
    const review = updateStageReview(undefined, { objective: "生成装配体 " }, inputs);
    expect(review?.inputs.objective).toBe("生成装配体 ");
    expect(engineeringInputRevision(review)).toBe(0);
    expect(jobInputChange(legacyJob, review)).toBeNull();
  });

  it("持久化保留项目版本，晚完成的任务仍按提交时版本复核", () => {
    const review = updateStageReview(undefined, { length: 120 }, inputs);
    const restored = restoreStageReview(JSON.parse(JSON.stringify(review)));
    const runningJob = { ...legacyJob, status: "running" as const, uiConfig: { engineeringInputRevision: 0 } };
    expect(jobInputChange(runningJob, restored)?.roots).toEqual(["part-modeling"]);
    expect(jobInputChange({ ...runningJob, status: "passed" }, restored)?.roots).toEqual(["part-modeling"]);
    const currentJob = { ...legacyJob, uiConfig: { engineeringInputRevision: engineeringInputRevision(restored) } };
    expect(jobInputChange(currentJob, restored)).toBeNull();
    expect(jobInputChange(legacyJob, undefined)).toBeNull();
  });

  it("孔径修改从特征阶段开始，后续图纸更新不重置之前的变更", () => {
    const hole = { id: "holes-fillet-chamfer", depends_on: ["part-modeling"] };
    const downstream = { id: "drawing-bom", depends_on: [hole.id] };
    const original = [phases[1], phases[4], hole, downstream];
    const afterHoleChange = recordChatChange(undefined, 1, ["holes-fillet-chamfer"]);
    const afterDrawingChange = recordChatChange(afterHoleChange, 2, ["drawing-bom"]);
    expect([...stagesNeedingReview(original, jobInputChange(legacyJob, afterDrawingChange))]).toEqual([hole, downstream]);
    const refreshed = { ...legacyJob, uiConfig: { chatInputRevision: 1 } };
    expect(jobInputChange(refreshed, afterDrawingChange)?.roots).toEqual(["drawing-bom"]);
    const question = { ...legacyJob, uiConfig: { chatInputRevision: 2 } };
    expect(jobInputChange(question, afterDrawingChange)).toBeNull();
    expect(chatInputRevision(restoreStageReview(afterDrawingChange))).toBe(2);
  });

  it("可从成功入队的任务恢复复核记录，保持项目隔离且不降级已保存的版本", () => {
    const projects: ProjectRecord[] = [
      { id: "A", name: "A", createdAt: "", updatedAt: "", stageReview: recordChatChange(undefined, 3, ["requirements"]) },
      { id: "B", name: "B", createdAt: "", updatedAt: "" },
    ];
    const saved = [
      { ...legacyJob, projectId: "A", uiConfig: { chatInputRevision: 2, chatReviewRoots: ["requirements"] } },
      { ...legacyJob, projectId: "A", uiConfig: { chatInputRevision: 4, chatReviewRoots: ["holes-fillet-chamfer"] } },
      { ...legacyJob, projectId: "B", uiConfig: { chatInputRevision: 4 } },
    ];
    const restored = restoreQueuedChatChanges(projects, saved);
    expect(restored[0].stageReview?.chatPhaseRevisions).toEqual({ requirements: 3, "holes-fillet-chamfer": 4 });
    expect(restored[1]).toBe(projects[1]);
    expect(restoreQueuedChatChanges(restored, saved)).toBe(restored);
    const afterFormEdit = updateStageReview(restored[0].stageReview, { width: 120 }, inputs);
    expect(chatInputRevision(afterFormEdit)).toBe(4);
  });
});
