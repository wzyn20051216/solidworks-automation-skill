export type VisualPhase =
  | "planning"
  | "sketch"
  | "feature"
  | "assembly"
  | "drawing"
  | "review"
  | "delivery";

export type VisualStatus = "thinking" | "working" | "checking" | "complete" | "warning";

export type VisualStep = {
  stepId: string;
  sequence: number;
  phase: VisualPhase;
  title: string;
  message: string;
  snapshotPath?: string;
  stats?: Record<string, number>;
};

export type LiveVisualState = {
  status: VisualStatus;
  phase: VisualPhase;
  title: string;
  message: string;
  progress: number;
  sequence: number;
  snapshotPath?: string;
  stats: Record<string, number>;
  steps: VisualStep[];
};
