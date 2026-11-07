import { motion, useReducedMotion } from "motion/react";
import type { VisualStatus } from "./visualTypes";

const idle = new URL("../assets/live-mascot/idle.webp", import.meta.url).href;
const working = new URL("../assets/live-mascot/working.webp", import.meta.url).href;
const checking = new URL("../assets/live-mascot/checking.webp", import.meta.url).href;
const complete = new URL("../assets/live-mascot/complete.webp", import.meta.url).href;

const assets: Record<VisualStatus, string> = {
  thinking: idle,
  working,
  checking,
  complete,
  warning: idle,
};

export function Mascot({ status }: { status: VisualStatus }) {
  const reducedMotion = useReducedMotion();
  return (
    <motion.div
      className={`live-mascot status-${status}`}
      animate={
        reducedMotion
          ? undefined
          : status === "working"
            ? { y: [0, -4, 0], rotate: [-1, 1, -1] }
            : { y: [0, -3, 0] }
      }
      transition={{ duration: status === "working" ? 1.3 : 2.8, repeat: Infinity }}
    >
      <img src={assets[status]} alt="" draggable={false} />
      {status === "working" ? <i className="mascot-ring" /> : null}
    </motion.div>
  );
}
