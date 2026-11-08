import { invoke } from "@tauri-apps/api/core";

export type PersistedStateRead = {
  value: unknown | null;
  degraded: boolean;
};

export type PersistedStateWrite = {
  degraded: boolean;
};

/**
 * @brief Geçerli sayfanın Tauri masaüstü kapsayıcısında çalışıp çalışmadığını belirler.
 */
export function isTauriRuntime() {
  return typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;
}

/**
 * @brief Eski sürüm localStorage verisini güvenle ayrıştırır; bozuk veri uygulama başlangıcını engellemez.
 */
export function parsePersistedJson(raw: string | null): unknown | null {
  if (!raw) return null;
  try {
    return JSON.parse(raw) as unknown;
  } catch {
    return null;
  }
}

/**
 * @brief Önce SQLite okunur; kullanılamıyorsa localStorage yedek kopyası korunur ve okunur.
 */
export async function readPersistedState(namespace: string, legacyKey: string): Promise<PersistedStateRead> {
  const legacyRaw = localStorage.getItem(legacyKey);
  const legacyValue = parsePersistedJson(legacyRaw);
  if (!isTauriRuntime()) {
    return { value: legacyValue, degraded: false };
  }

  // localStorage yalnızca eski sürüm geçişinde veya SQLite yazma hatasında bulunur; bu nedenle veritabanı kopyasından daha güncel olabilir.
  // Önce bu kopya geri yüklenmelidir; veritabanındaki eski değer önce döndürülürse yeniden başlatma sonrasında son düzenleme sessizce kaybolur.
  if (legacyRaw !== null && legacyValue !== null) {
    try {
      await invoke("write_app_store", { namespace, payload: legacyValue });
      localStorage.setItem(`${legacyKey}.migration-backup`, legacyRaw);
      localStorage.removeItem(legacyKey);
      return { value: legacyValue, degraded: false };
    } catch {
      return { value: legacyValue, degraded: true };
    }
  }

  try {
    const stored = await invoke<unknown | null>("read_app_store", { namespace });
    return { value: stored, degraded: false };
  } catch {
    // SQLite geçici olarak kilitliyse ve kullanılabilir yedek kopya yoksa açıkça düşük (degraded) duruma geçilir.
    return { value: null, degraded: true };
  }
}

/**
 * @brief SQLite'a yazar; yazma başarısız olursa eşzamanlı olarak localStorage'a kaydeder ve yeniden başlatma sonrasında kurtarılabilirliği garanti eder.
 */
export async function writePersistedState(namespace: string, legacyKey: string, payload: unknown): Promise<PersistedStateWrite> {
  const serialized = JSON.stringify(payload);
  if (!isTauriRuntime()) {
    localStorage.setItem(legacyKey, serialized);
    return { degraded: false };
  }

  try {
    await invoke("write_app_store", { namespace, payload });
    localStorage.removeItem(legacyKey);
    return { degraded: false };
  } catch {
    localStorage.setItem(legacyKey, serialized);
    return { degraded: true };
  }
}
