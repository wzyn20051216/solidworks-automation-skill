import type { AutomationJob, QueueEvent } from "../types";

export const demoJob: AutomationJob = {
  schemaVersion: "2.0",
  id: "job-live-demo",
  runId: "run-live-demo",
  kind: "agent_task",
  title: "阶梯轴可视化建模",
  detail: "SolidWorks 2026",
  status: "passed",
  progress: 100,
  stage: "delivery",
  createdAt: "2026-11-06T00:00:00Z",
  updatedAt: "2026-11-06T00:00:20Z",
  requestedBy: "demo",
  createdByAppVersion: "demo",
};

export const demoEvents: QueueEvent[] = [
  {
    type: "visual.step.completed",
    jobId: demoJob.id,
    progress: 55,
    message: "主体阶梯轴已生成",
    at: "2026-11-06T00:00:12Z",
    data: {
      stepId: "feature-main-shaft",
      sequence: 3,
      phase: "feature",
      title: "生成主体阶梯轴",
      message: "旋转特征已重建成实体",
      stats: { volumeMm3: 28378.5, featureCount: 6 },
    },
  },
  {
    type: "visual.delivery.ready",
    jobId: demoJob.id,
    progress: 100,
    message: "交付文件已生成",
    at: "2026-11-06T00:00:20Z",
    data: {
      stepId: "delivery-ready",
      sequence: 7,
      phase: "delivery",
      title: "这一轮搞定啦",
      message: "SLDPRT 与 STEP 已保存",
      stats: { volumeMm3: 28378.5, featureCount: 6 },
    },
  },
];
