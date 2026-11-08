import { ArrowSquareOut, Copy, Wrench } from "@phosphor-icons/react";
import type { RuntimeRemediation } from "../types";

type EnvironmentRemediationPanelProps = {
  remediations: RuntimeRemediation[];
  onCopyCommand: (command: string) => void | Promise<void>;
  onOpenDownload: (url: string) => void | Promise<void>;
};

/** @brief Birleşik doctor tarafından döndürülen ortam onarım eylemlerini gösterir. */
export function EnvironmentRemediationPanel({ remediations, onCopyCommand, onOpenDownload }: EnvironmentRemediationPanelProps) {
  if (!remediations.length) return null;
  const requiredCount = remediations.filter((item) => item.required).length;

  return (
    <section className="environment-remediation" aria-labelledby="environment-remediation-title">
      <div className="environment-remediation-heading">
        <Wrench size={20} weight="duotone" />
        <div>
          <span>Ortam onarımı</span>
          <strong id="environment-remediation-title">İşlenebilir {remediations.length} sorun tespit edildi</strong>
        </div>
        <small>{requiredCount ? `${requiredCount} madde mevcut girişi engelliyor` : "Tümü isteğe bağlı yetkinlikler; diğer arka uçları engellemez"}</small>
      </div>
      <div className="environment-remediation-list">
        {remediations.map((item) => (
          <article className={item.required ? "environment-remediation-row required" : "environment-remediation-row"} key={item.id}>
            <div className="environment-remediation-copy">
              <span>{item.required ? "İşlem gerekli" : "İsteğe bağlı kurulum"}</span>
              <strong>{item.title}</strong>
              {item.reason ? <p>{item.reason}</p> : null}
              {item.installCommand ? <code>{item.installCommand}</code> : null}
            </div>
            <div className="environment-remediation-actions">
              {item.installCommand ? (
                <button type="button" title="Kurulum komutunu kopyala" aria-label={`${item.title} kurulum komutunu kopyala`} onClick={() => void onCopyCommand(item.installCommand!)}>
                  <Copy size={16} />
                </button>
              ) : null}
              {item.downloadUrl ? (
                <button type="button" className="download-action" title={`${item.title} resmi indirme sayfasını aç`} onClick={() => void onOpenDownload(item.downloadUrl!)}>
                  <ArrowSquareOut size={16} />
                  <span>Resmi indirme</span>
                </button>
              ) : null}
            </div>
          </article>
        ))}
      </div>
    </section>
  );
}
