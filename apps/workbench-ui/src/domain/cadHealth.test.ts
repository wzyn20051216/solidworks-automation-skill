import { describe, expect, it } from "vitest";
import { cadConnectionLabel } from "./cadHealth";

describe("CAD 连接状态", () => {
  it("区分已安装、已连接和探测失败", () => {
    expect(cadConnectionLabel({ installed: true, ok: false, mode: "not_running" })).toBe("已安装，未运行");
    expect(cadConnectionLabel({ installed: true, ok: true, mode: "active" })).toBe("已连接");
    expect(cadConnectionLabel({ installed: true, ok: false, mode: "unavailable" })).toBe("连接待检查");
    expect(cadConnectionLabel({ installed: false, ok: false })).toBe("未检测到安装");
    expect(cadConnectionLabel()).toBe("连接待检查");
  });
});
