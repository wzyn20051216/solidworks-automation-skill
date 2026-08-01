import { WarningCircle } from "@phosphor-icons/react";
import type { PreviewManifest, PreviewPhase } from "./previewTypes";

type PreviewStatusProps = {
  phase: PreviewPhase;
  message: string;
  manifest?: PreviewManifest | null;
};

/** @brief 显示预览的细粒度加载阶段和真实/演示来源。 */
export function PreviewStatus({ phase, message, manifest }: PreviewStatusProps) {
  const isDemo = manifest?.isDemo || manifest?.mode === "demo-showcase";
  return (
    <div className={`cad-preview-status-line ${phase === "预览失败" ? "error" : phase === "可交互" ? "ready" : "loading"}`}>
      <span>{phase}</span>
      <small>{message}</small>
      <em className={isDemo ? "demo" : "delivery"}>{isDemo ? "演示数据" : "真实产物"}</em>
      {isDemo ? <WarningCircle size={15} /> : null}
    </div>
  );
}
