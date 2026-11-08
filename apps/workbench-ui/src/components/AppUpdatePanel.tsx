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
 * @brief GitHub Release güncellemelerini otomatik denetler ve kullanıcı onayından sonra imzalı kurulum paketini indirip yükler.
 */
export function AppUpdatePanel({ expanded }: { expanded: boolean }) {
  const [currentVersion, setCurrentVersion] = useState("Okunuyor");
  const [availableVersion, setAvailableVersion] = useState<string>();
  const [releaseNotes, setReleaseNotes] = useState<string>();
  const [status, setStatus] = useState<UpdateStatus>("idle");
  const [message, setMessage] = useState("Başlangıçta bir kez otomatik denetlenir; istediğiniz zaman manuel olarak da denetleyebilirsiniz.");
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
    setMessage("Yeni sürümü denetlemek için GitHub Release'e bağlanılıyor...");
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
        setMessage("Zaten en son sürümü kullanıyorsunuz.");
        return;
      }
      updateRef.current = nextUpdate;
      setAvailableVersion(nextUpdate.version);
      setReleaseNotes(nextUpdate.body?.trim());
      setStatus("available");
      setMessage(`CAD Studio ${nextUpdate.version} bulundu; yüklemeden önce mevcut çalışmanızı kaydetmeye devam edebilirsiniz.`);
    } catch (error) {
      if (!mountedRef.current) return;
      const detail = error instanceof Error ? error.message : String(error);
      setStatus(silent ? "idle" : "error");
      setMessage(silent ? `Son otomatik denetim tamamlanamadı: ${detail}. Buradan manuel olarak yeniden deneyebilirsiniz.` : `Güncelleme denetimi başarısız: ${detail}`);
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
    setMessage("İmzalı güncelleme paketi indiriliyor ve doğrulanıyor...");
    try {
      let currentProgress: UpdateProgress = { downloadedBytes: 0 };
      await update.downloadAndInstall((event: DownloadEvent) => {
        currentProgress = updateDownloadProgress(currentProgress, event);
        setProgress(currentProgress);
        if (event.event === "Finished") {
          setStatus("installing");
          setMessage("Güncelleme paketi doğrulandı; kurulum programı devralacak ve mevcut pencereyi kapatacak.");
        }
      }, { timeout: 120_000 });
    } catch (error) {
      setStatus("error");
      setMessage(`Güncelleme kurulumu başarısız: ${error instanceof Error ? error.message : String(error)}`);
    }
  }, [checkForUpdates]);

  useEffect(() => {
    mountedRef.current = true;
    let timer: number | undefined;
    if (!isTauriRuntime()) {
      setCurrentVersion("Tarayıcı önizlemesi");
      setMessage("Otomatik güncelleme yalnızca CAD Studio Windows masaüstü sürümünde etkindir.");
    } else {
      void getVersion().then(setCurrentVersion).catch(() => setCurrentVersion("Bilinmiyor"));
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
          <span>Yazılım güncellemesi</span>
          <strong>{availableVersion ? `${currentVersion} → ${availableVersion}` : `CAD Studio ${currentVersion}`}</strong>
        </div>
      </div>
      <p>{message}</p>
      {status === "downloading" || status === "installing" ? (
        <div className="update-progress" aria-label={progress.percent === undefined ? "Güncelleme indiriliyor" : `Güncelleme indirme ilerlemesi %${progress.percent}`}>
          <i style={{ width: `${progress.percent ?? 12}%` }} />
          <small>{progress.percent === undefined ? "Güncelleme paketi alınıyor" : `%${progress.percent}`}</small>
        </div>
      ) : null}
      {releaseNotes && status === "available" ? <details><summary>Sürüm notlarını görüntüle</summary><p>{releaseNotes}</p></details> : null}
      <div className="update-actions">
        {status === "available" ? <button type="button" disabled={busy} onClick={() => void installUpdate()}>İndir ve yükle</button> : null}
        <button type="button" disabled={busy || !isTauriRuntime()} onClick={() => void checkForUpdates()}>
          {status === "checking" ? "Denetleniyor" : "Güncellemeleri denetle"}
        </button>
        {status === "error" ? <button type="button" onClick={() => void invoke("open_external_download", { url: RELEASES_URL }).catch((error) => setMessage(`İndirme sayfası açılamadı: ${error instanceof Error ? error.message : String(error)}`))}>İndirme sayfasını aç</button> : null}
        {!expanded ? <button type="button" onClick={() => setDismissed(true)}>Daha sonra</button> : null}
      </div>
    </article>
  );
}
