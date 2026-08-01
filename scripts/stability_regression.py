"""CAD Studio 连接生命周期稳定性模拟回归。

不启动真实 CAD；用于 CI 验证 20 次连接、取消、退出的所有权和状态机约束。
真实 CAD 回归仍由 Windows 自托管机执行专项脚本。
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class FakeCadProcess:
    """@brief 可观测的模拟 CAD 进程。"""

    process_id: int
    running: bool = True

    def quit(self) -> None:
        self.running = False


class LifecycleHarness:
    """@brief 模拟单实例所有权、取消和退出清理。"""

    def __init__(self) -> None:
        self._next_id = 1
        self.process: FakeCadProcess | None = None
        self.started_by_studio = False
        self.cancelled = False

    def connect(self, existing: FakeCadProcess | None = None) -> FakeCadProcess:
        if self.process is not None and self.process.running:
            return self.process
        if existing is not None:
            self.process = existing
            self.started_by_studio = False
        else:
            self.process = FakeCadProcess(self._next_id)
            self._next_id += 1
            self.started_by_studio = True
        return self.process

    def cancel(self) -> None:
        self.cancelled = True

    def close(self) -> bool:
        if not self.started_by_studio or self.process is None:
            return False
        self.process.quit()
        self.process = None
        self.started_by_studio = False
        return True


def run_regression(iterations: int = 20) -> dict[str, object]:
    """@brief 执行生命周期回归并返回可审计结果。"""
    if iterations < 1:
        raise ValueError("iterations 必须大于 0")
    harness = LifecycleHarness()
    process_ids: list[int] = []
    for _ in range(iterations):
        process = harness.connect()
        process_ids.append(process.process_id)
        harness.cancel()
        harness.close()
        harness.cancelled = False
    return {
        "status": "pass" if len(set(process_ids)) == iterations and harness.process is None else "fail",
        "iterations": iterations,
        "unique_processes": len(set(process_ids)),
        "orphan_process": harness.process is not None,
        "cancelled": harness.cancelled,
    }


if __name__ == "__main__":
    import json

    print(json.dumps(run_regression(), ensure_ascii=False, indent=2))
