import { invoke } from "@tauri-apps/api/core";
import { useEffect, useState } from "react";
import type { AutomationJob } from "../types";

export function showsSolidWorksLivePreview(job: AutomationJob) {
  const cad = job.uiConfig?.cadRuntime as Record<string, unknown> | undefined;
  return job.status === "running" && cad?.localCadAutomation === true
    && (cad.application === "auto" || cad.application === "solidworks");
}

export function SolidWorksLivePreview({ id, runId }: Pick<AutomationJob, "id" | "runId">) {
  const [frameUrl, setFrameUrl] = useState("");

  useEffect(() => {
    let disposed = false;
    let timer: number;
    let url = "";
    let lastFrame = new Uint8Array();

    function updateFrame(frame: Uint8Array<ArrayBuffer>) {
      if (frame.length === lastFrame.length && !frame.some((byte, index) => byte !== lastFrame[index])) return;
      lastFrame = frame;
      if (url) URL.revokeObjectURL(url);
      url = frame.length ? URL.createObjectURL(new Blob([frame], { type: "image/png" })) : "";
      setFrameUrl(url);
    }

    async function poll() {
      try {
        const payload = await invoke<ArrayBuffer | number[]>("read_solidworks_preview", { id, runId });
        if (!disposed) updateFrame(new Uint8Array(payload));
      } catch {
        if (!disposed) updateFrame(new Uint8Array());
      } finally {
        if (!disposed) timer = window.setTimeout(() => void poll(), 800);
      }
    }

    void poll();
    return () => {
      disposed = true;
      window.clearTimeout(timer);
      if (url) URL.revokeObjectURL(url);
    };
  }, [id, runId]);

  return (
    <section className="solidworks-live-preview" aria-label="SolidWorks 实时预览">
      <strong>SolidWorks 实时预览</strong>
      {frameUrl
        ? <img key={frameUrl} src={frameUrl} alt="当前任务的 SolidWorks 建模视图" onError={() => setFrameUrl("")} />
        : <span role="status">预览不可用</span>}
    </section>
  );
}
