export type UpdateProgress = {
  downloadedBytes: number;
  totalBytes?: number;
  percent?: number;
};

/**
 * @brief 合并更新下载事件并计算稳定的百分比，防止超范围和除零。
 */
export function updateDownloadProgress(
  current: UpdateProgress,
  event: { event: "Started"; data: { contentLength?: number } } | { event: "Progress"; data: { chunkLength: number } } | { event: "Finished" },
): UpdateProgress {
  if (event.event === "Started") {
    return { downloadedBytes: 0, totalBytes: event.data.contentLength, percent: event.data.contentLength ? 0 : undefined };
  }
  if (event.event === "Finished") {
    return { ...current, percent: current.totalBytes ? 100 : current.percent };
  }
  const downloadedBytes = Math.max(0, current.downloadedBytes + Math.max(0, event.data.chunkLength));
  const percent = current.totalBytes
    ? Math.min(100, Math.round((downloadedBytes / current.totalBytes) * 100))
    : undefined;
  return { ...current, downloadedBytes, percent };
}
