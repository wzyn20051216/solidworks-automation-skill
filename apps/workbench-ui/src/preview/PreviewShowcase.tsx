import { useMemo, useState } from "react";
import { CadPreview } from "../CadPreview";
import { DEMO_SCENES } from "./demoScenes";

/** @brief 与真实交付隔离的固定预览演示台。 */
export function PreviewShowcase() {
  const [activeId, setActiveId] = useState(DEMO_SCENES[0].id);
  const active = useMemo(() => DEMO_SCENES.find((item) => item.id === activeId) ?? DEMO_SCENES[0], [activeId]);
  return (
    <section className="preview-showcase" aria-label="预览演示">
      <div className="preview-showcase-heading">
        <div>
          <span className="eyebrow">DEMO SHOWCASE</span>
          <strong>机械检视台演示</strong>
        </div>
        <label>
          <span>样例</span>
          <select value={activeId} onChange={(event) => setActiveId(event.target.value)}>
            {DEMO_SCENES.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}
          </select>
        </label>
      </div>
      <CadPreview
        artifact={{
          path: `${active.id}.scene.json`,
          kind: "preview-scene",
          exists: true,
          isDemo: true,
          sourceArtifact: `demo:${active.id}`,
          sourceBackend: "demo-showcase",
          sha256: "demo-only",
          previewScene: active.scene,
        }}
      />
    </section>
  );
}
