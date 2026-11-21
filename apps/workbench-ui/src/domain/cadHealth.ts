import type { CadConnectionHealth } from "../types";

export function cadConnectionLabel(health?: CadConnectionHealth) {
  if (health?.ok) return "已连接";
  if (health?.installed === false) return "未检测到安装";
  if (health?.mode === "not_running") return "已安装，未运行";
  if (health?.mode === "missing_dependency") return "缺少 COM 依赖";
  return "连接待检查";
}
