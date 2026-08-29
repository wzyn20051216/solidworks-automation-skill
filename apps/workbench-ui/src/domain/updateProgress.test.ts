import { describe, expect, it } from "vitest";
import { updateDownloadProgress } from "./updateProgress";

describe("updateDownloadProgress", () => {
  it("按更新包总大小计算下载百分比", () => {
    let progress = updateDownloadProgress({ downloadedBytes: 0 }, { event: "Started", data: { contentLength: 1000 } });
    progress = updateDownloadProgress(progress, { event: "Progress", data: { chunkLength: 260 } });
    expect(progress).toEqual({ downloadedBytes: 260, totalBytes: 1000, percent: 26 });
  });

  it("将超出总大小的进度限制为 100%", () => {
    const progress = updateDownloadProgress(
      { downloadedBytes: 900, totalBytes: 1000, percent: 90 },
      { event: "Progress", data: { chunkLength: 500 } },
    );
    expect(progress.percent).toBe(100);
  });

  it("未知总大小时仍累计字节且不伪造百分比", () => {
    const progress = updateDownloadProgress({ downloadedBytes: 0 }, { event: "Progress", data: { chunkLength: 128 } });
    expect(progress).toEqual({ downloadedBytes: 128, percent: undefined });
  });
});
