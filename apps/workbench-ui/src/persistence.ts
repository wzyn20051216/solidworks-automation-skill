import { invoke } from "@tauri-apps/api/core";

export type PersistedStateRead = {
  value: unknown | null;
  degraded: boolean;
};

export type PersistedStateWrite = {
  degraded: boolean;
};

/**
 * @brief 判断当前页面是否运行在 Tauri 桌面容器中。
 */
export function isTauriRuntime() {
  return typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;
}

/**
 * @brief 安全解析旧版 localStorage 数据，损坏数据不会阻断应用启动。
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
 * @brief 优先读取 SQLite；不可用时保留并读取 localStorage 回退副本。
 */
export async function readPersistedState(namespace: string, legacyKey: string): Promise<PersistedStateRead> {
  const legacyRaw = localStorage.getItem(legacyKey);
  const legacyValue = parsePersistedJson(legacyRaw);
  if (!isTauriRuntime()) {
    return { value: legacyValue, degraded: false };
  }

  // localStorage 只会在旧版迁移或 SQLite 写入失败时存在，因此它可能比数据库副本更新。
  // 必须先回灌该副本，不能先返回数据库中的旧值，否则重启后会悄悄丢失最近一次编辑。
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
    // SQLite 临时锁定且没有可用回退副本时，显式进入降级状态。
    return { value: null, degraded: true };
  }
}

/**
 * @brief 写入 SQLite；写入失败时同步保存到 localStorage，确保重启后仍可恢复。
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
