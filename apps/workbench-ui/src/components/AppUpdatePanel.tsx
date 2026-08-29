import { ArrowClockwise, CheckCircle, DownloadSimple, WarningCircle } from "@phosphor-icons/react";
import { getVersion } from "@tauri-apps/api/app";
import { invoke } from "@tauri-apps/api/core";
import { check, type DownloadEvent, type Update } from "@tauri-apps/plugin-updater";
import { useCallback, useEffect, useRef, useState } from "react";
import { updateDownloadProgress, type UpdateProgress } from "../domain/updateProgress";
import { isTauriRuntime } from "../persistence";

const RELEASES_URL = "https://github.com/wzyn20051216/solidworks-automation-skill/releases/latest";

type UpdateStatus = "idle" | "checking" | "current" | "available" | "downloading" | "installing" | "error";

/**
 * @brief 自动检测 GitHub Release 更新，并在用户确认后下载和安装签名安装包。
 */
export function AppUpdatePanel({ expanded }: { expanded: boolean }) {
  const [currentVersion, setCurrentVersion] = useState("读取中");
  const [availableVersion, setAvailableVersion] = useState<string>();
  const [releaseNotes, setReleaseNotes] = useState<string>();
  const [status, setStatus] = useState<UpdateStatus>("idle");
  const [message, setMessage] = useState("启动后会自动检测一次，也可以随时手动检查。");
  const [dismissed, setDismissed] = useState(false);
  const [progress, setProgress] = useState<UpdateProgress>({ downloadedBytes: 0 });
  const updateRef = useRef<Update | null>(null);
  const checkingRef = useRef(false);
  const mountedRef = useRef(false);

  const closeCurrentUpdate = useCallback(async () => {
    const current = updateRef.current;
    updateRef.current = null;
    if (current) await current.close().catch(() => undefined);
  }, []);

  const checkForUpdates = useCallback(async (silent = false) => {
    if (!isTauriRuntime() || checkingRef.current) return;
    checkingRef.current = true;
    setDismissed(false);
    setStatus("checking");
    setMessage("正在连接 GitHub Release 检查新版本...");
    setAvailableVersion(undefined);
    setReleaseNotes(undefined);
    setProgress({ downloadedBytes: 0 });
    try {
      await closeCurrentUpdate();
      const nextUpdate = await check({ timeout: 30_000 });
      if (!mountedRef.current) {
        await nextUpdate?.close().catch(() => undefined);
        return;
      }
      if (!nextUpdate) {
        setAvailableVersion(undefined);
        setStatus("current");
        setMessage("当前已是最新版本。");
        return;
      }
      updateRef.current = nextUpdate;
      setAvailableVersion(nextUpdate.version);
      setReleaseNotes(nextUpdate.body?.trim());
      setStatus("available");
      setMessage(`发现 CAD Studio ${nextUpdate.version}，安装前可继续保存当前工作。`);
    } catch (error) {
      if (!mountedRef.current) return;
      const detail = error instanceof Error ? error.message : String(error);
      setStatus(silent ? "idle" : "error");
      setMessage(silent ? `上次自动检查未完成：${detail}。可在此手动重试。` : `检查更新失败：${detail}`);
    } finally {
      checkingRef.current = false;
    }
  }, [closeCurrentUpdate]);

  const installUpdate = useCallback(async () => {
    const update = updateRef.current;
    if (!update) {
      await checkForUpdates();
      return;
    }
    setStatus("downloading");
    setProgress({ downloadedBytes: 0 });
    setMessage("正在下载并验证签名更新包...");
    try {
      let currentProgress: UpdateProgress = { downloadedBytes: 0 };
      await update.downloadAndInstall((event: DownloadEvent) => {
        currentProgress = updateDownloadProgress(currentProgress, event);
        setProgress(currentProgress);
        if (event.event === "Finished") {
          setStatus("installing");
          setMessage("更新包校验完成，安装程序即将接管并关闭当前窗口。");
        }
      }, { timeout: 120_000 });
    } catch (error) {
      setStatus("error");
      setMessage(`更新安装失败：${error instanceof Error ? error.message : String(error)}`);
    }
  }, [checkForUpdates]);

  useEffect(() => {
    mountedRef.current = true;
    let timer: number | undefined;
    if (!isTauriRuntime()) {
      setCurrentVersion("浏览器预览");
      setMessage("自动更新仅在 CAD Studio Windows 桌面版中启用。");
    } else {
      void getVersion().then(setCurrentVersion).catch(() => setCurrentVersion("未知"));
      timer = window.setTimeout(() => void checkForUpdates(true), 1_500);
    }
    return () => {
      mountedRef.current = false;
      if (timer !== undefined) window.clearTimeout(timer);
      void closeCurrentUpdate();
    };
  }, [checkForUpdates, closeCurrentUpdate]);

  const busy = status === "checking" || status === "downloading" || status === "installing";
  const Icon = status === "error" ? WarningCircle : status === "current" ? CheckCircle : status === "available" ? DownloadSimple : ArrowClockwise;
  if (!expanded && (dismissed || (status !== "available" && status !== "error"))) return null;

  return (
    <article className={`setting-card update-setting ${status} ${expanded ? "expanded" : "floating"}`} aria-live="polite">
      <div className="update-heading">
        <Icon size={22} weight="duotone" />
        <div>
          <span>软件更新</span>
          <strong>{availableVersion ? `${currentVersion} → ${availableVersion}` : `CAD Studio ${currentVersion}`}</strong>
        </div>
      </div>
      <p>{message}</p>
      {status === "downloading" || status === "installing" ? (
        <div className="update-progress" aria-label={progress.percent === undefined ? "正在下载更新" : `更新下载进度 ${progress.percent}%`}>
          <i style={{ width: `${progress.percent ?? 12}%` }} />
          <small>{progress.percent === undefined ? "正在接收更新包" : `${progress.percent}%`}</small>
        </div>
      ) : null}
      {releaseNotes && status === "available" ? <details><summary>查看版本说明</summary><p>{releaseNotes}</p></details> : null}
      <div className="update-actions">
        {status === "available" ? <button type="button" disabled={busy} onClick={() => void installUpdate()}>下载并安装</button> : null}
        <button type="button" disabled={busy || !isTauriRuntime()} onClick={() => void checkForUpdates()}>
          {status === "checking" ? "检查中" : "检查更新"}
        </button>
        {status === "error" ? <button type="button" onClick={() => void invoke("open_external_download", { url: RELEASES_URL }).catch((error) => setMessage(`打开下载页失败：${error instanceof Error ? error.message : String(error)}`))}>打开下载页</button> : null}
        {!expanded ? <button type="button" onClick={() => setDismissed(true)}>稍后</button> : null}
      </div>
    </article>
  );
}
