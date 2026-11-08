import { WarningCircle } from "@phosphor-icons/react";
import type { PreviewManifest, PreviewPhase } from "./previewTypes";

type PreviewStatusProps = {
  phase: PreviewPhase;
  message: string;
  manifest?: PreviewManifest | null;
};

/** @brief Önizlemenin ayrıntılı yükleme aşamasını ve gerçek/demo kaynağını gösterir. */
export function PreviewStatus({ phase, message, manifest }: PreviewStatusProps) {
  const isDemo = manifest?.isDemo || manifest?.mode === "demo-showcase";
  return (
    <div className={`cad-preview-status-line ${phase === "Önizleme başarısız" ? "error" : phase === "Etkileşime hazır" ? "ready" : "loading"}`}>
      <span>{phase}</span>
      <small>{message}</small>
      <em className={isDemo ? "demo" : "delivery"}>{isDemo ? "Demo verisi" : "Gerçek çıktı"}</em>
      {isDemo ? <WarningCircle size={15} /> : null}
    </div>
  );
}
