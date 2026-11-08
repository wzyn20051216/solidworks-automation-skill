import { afterEach, describe, expect, it, vi } from "vitest";

const invokeMock = vi.hoisted(() => vi.fn());
vi.mock("@tauri-apps/api/core", () => ({ invoke: invokeMock }));

import { parsePersistedJson, readPersistedState, writePersistedState } from "./persistence";

function installDesktopStorage(initial: Record<string, string> = {}) {
  const values = new Map(Object.entries(initial));
  const storage = {
    getItem: vi.fn((key: string) => values.get(key) ?? null),
    setItem: vi.fn((key: string, value: string) => { values.set(key, value); }),
    removeItem: vi.fn((key: string) => { values.delete(key); }),
  };
  vi.stubGlobal("window", { __TAURI_INTERNALS__: {} });
  vi.stubGlobal("localStorage", storage);
  return { storage, values };
}

afterEach(() => {
  invokeMock.mockReset();
  vi.unstubAllGlobals();
});

describe("parsePersistedJson", () => {
  it("geçerli yerel yedek veriyi okur", () => {
    expect(parsePersistedJson('{"project":"fixture"}')).toEqual({ project: "fixture" });
  });

  it("bozuk veri uygulama başlangıcını engellemez", () => {
    expect(parsePersistedJson("{broken")).toBeNull();
    expect(parsePersistedJson(null)).toBeNull();
  });
});

describe("readPersistedState", () => {
  it("daha yeni yerel yedek kopyayı önce geri yükler ve eski SQLite verisinin üzerine yazmasını önler", async () => {
    const { values } = installDesktopStorage({ "cad.settings": '{"revision":2}' });
    invokeMock.mockResolvedValueOnce(undefined);

    const result = await readPersistedState("settings", "cad.settings");

    expect(result).toEqual({ value: { revision: 2 }, degraded: false });
    expect(invokeMock).toHaveBeenCalledWith("write_app_store", {
      namespace: "settings",
      payload: { revision: 2 },
    });
    expect(invokeMock).not.toHaveBeenCalledWith("read_app_store", expect.anything());
    expect(values.has("cad.settings")).toBe(false);
    expect(values.get("cad.settings.migration-backup")).toBe('{"revision":2}');
  });

  it("SQLite hâlâ kullanılamıyorsa yedek kopyayı korur ve düşük durumu bildirir", async () => {
    const { values } = installDesktopStorage({ "cad.messages": '[{"id":"latest"}]' });
    invokeMock.mockRejectedValueOnce(new Error("database is locked"));

    const result = await readPersistedState("messages", "cad.messages");

    expect(result).toEqual({ value: [{ id: "latest" }], degraded: true });
    expect(values.get("cad.messages")).toBe('[{"id":"latest"}]');
  });

  it("yedek kopya yokken SQLite okur", async () => {
    installDesktopStorage();
    invokeMock.mockResolvedValueOnce({ revision: 3 });

    await expect(readPersistedState("settings", "cad.settings")).resolves.toEqual({
      value: { revision: 3 },
      degraded: false,
    });
    expect(invokeMock).toHaveBeenCalledWith("read_app_store", { namespace: "settings" });
  });
});

describe("writePersistedState", () => {
  it("SQLite yazma hatasında kurtarılabilir kopyayı eşzamanlı korur", async () => {
    const { values } = installDesktopStorage();
    invokeMock.mockRejectedValueOnce(new Error("disk busy"));

    await expect(writePersistedState("settings", "cad.settings", { revision: 4 })).resolves.toEqual({ degraded: true });
    expect(values.get("cad.settings")).toBe('{"revision":4}');
  });
});
