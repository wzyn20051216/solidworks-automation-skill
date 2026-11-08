import { describe, expect, it } from "vitest";
import { updateDownloadProgress } from "./updateProgress";

describe("updateDownloadProgress", () => {
  it("indirme yüzdesini güncelleme paketinin toplam boyutuna göre hesaplar", () => {
    let progress = updateDownloadProgress({ downloadedBytes: 0 }, { event: "Started", data: { contentLength: 1000 } });
    progress = updateDownloadProgress(progress, { event: "Progress", data: { chunkLength: 260 } });
    expect(progress).toEqual({ downloadedBytes: 260, totalBytes: 1000, percent: 26 });
  });

  it("toplam boyutu aşan ilerlemeyi %100 ile sınırlar", () => {
    const progress = updateDownloadProgress(
      { downloadedBytes: 900, totalBytes: 1000, percent: 90 },
      { event: "Progress", data: { chunkLength: 500 } },
    );
    expect(progress.percent).toBe(100);
  });

  it("toplam boyut bilinmediğinde baytları biriktirmeye devam eder ve sahte yüzde üretmez", () => {
    const progress = updateDownloadProgress({ downloadedBytes: 0 }, { event: "Progress", data: { chunkLength: 128 } });
    expect(progress).toEqual({ downloadedBytes: 128, percent: undefined });
  });
});
