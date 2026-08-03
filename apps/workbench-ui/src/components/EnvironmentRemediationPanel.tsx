import { ArrowSquareOut, Copy, Wrench } from "@phosphor-icons/react";
import type { RuntimeRemediation } from "../types";

type EnvironmentRemediationPanelProps = {
  remediations: RuntimeRemediation[];
  onCopyCommand: (command: string) => void | Promise<void>;
  onOpenDownload: (url: string) => void | Promise<void>;
};

/** @brief 展示统一 doctor 返回的环境修复动作。 */
export function EnvironmentRemediationPanel({ remediations, onCopyCommand, onOpenDownload }: EnvironmentRemediationPanelProps) {
  if (!remediations.length) return null;
  const requiredCount = remediations.filter((item) => item.required).length;

  return (
    <section className="environment-remediation" aria-labelledby="environment-remediation-title">
      <div className="environment-remediation-heading">
        <Wrench size={20} weight="duotone" />
        <div>
          <span>环境修复</span>
          <strong id="environment-remediation-title">检测到 {remediations.length} 项可处理问题</strong>
        </div>
        <small>{requiredCount ? `${requiredCount} 项会阻断当前入口` : "均为按需能力，不阻断其他后端"}</small>
      </div>
      <div className="environment-remediation-list">
        {remediations.map((item) => (
          <article className={item.required ? "environment-remediation-row required" : "environment-remediation-row"} key={item.id}>
            <div className="environment-remediation-copy">
              <span>{item.required ? "需要处理" : "按需安装"}</span>
              <strong>{item.title}</strong>
              {item.reason ? <p>{item.reason}</p> : null}
              {item.installCommand ? <code>{item.installCommand}</code> : null}
            </div>
            <div className="environment-remediation-actions">
              {item.installCommand ? (
                <button type="button" title="复制安装命令" aria-label={`复制 ${item.title} 的安装命令`} onClick={() => void onCopyCommand(item.installCommand!)}>
                  <Copy size={16} />
                </button>
              ) : null}
              {item.downloadUrl ? (
                <button type="button" className="download-action" title={`打开 ${item.title} 官方下载页`} onClick={() => void onOpenDownload(item.downloadUrl!)}>
                  <ArrowSquareOut size={16} />
                  <span>官方下载</span>
                </button>
              ) : null}
            </div>
          </article>
        ))}
      </div>
    </section>
  );
}
