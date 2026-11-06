"""用真实 SolidWorks 验证可视化事件、模型统计和窗口快照。"""

import json
import os
import sys
import time
from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from sw_connect import mm
from sw_part import extrude_boss, sketch, sketch_circle
from sw_process import solidworks_processes
from sw_session import SolidWorksSession


def read_events(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line
    ]


def main() -> int:
    output = ROOT / "output" / "live-visual-smoke"
    frames = output / "frames"
    events = output / "events.jsonl"
    part = output / "live-visual-smoke.SLDPRT"
    output.mkdir(parents=True, exist_ok=True)
    frames.mkdir(parents=True, exist_ok=True)
    events.unlink(missing_ok=True)
    part.unlink(missing_ok=True)
    for snapshot in frames.glob("step-*"):
        snapshot.unlink(missing_ok=True)

    os.environ["CADSTUDIO_JOB_ID"] = "live-visual-smoke"
    os.environ["CADSTUDIO_VISUAL_EVENT_FILE"] = str(events)
    os.environ["CADSTUDIO_VISUAL_FRAME_DIR"] = str(frames)
    before = solidworks_processes() or {}

    with SolidWorksSession(version=2026, visible=True) as session:
        model = session.new_part()
        with sketch(model, "Front Plane") as ref:
            sketch_circle(model, 0, 0, mm(20))
        if extrude_boss(model, ref, mm(40)) is None:
            raise RuntimeError("拉伸失败")
        if not session.save(model, str(part)):
            raise RuntimeError("保存失败")

    payload = read_events(events)
    completed = [
        item for item in payload if item.get("type") == "visual.step.completed"
    ]
    phases = {item.get("data", {}).get("phase") for item in payload}
    snapshot_events = [
        item
        for item in completed
        if isinstance(item.get("data", {}).get("snapshotPath"), str)
    ]
    delivery = next(
        (
            item
            for item in reversed(completed)
            if item.get("data", {}).get("phase") == "delivery"
            and item.get("data", {}).get("stats")
        ),
        None,
    )
    if not completed:
        raise RuntimeError("没有生成 visual.step.completed 事件")
    if not {"planning", "sketch", "feature", "delivery"} <= phases:
        raise RuntimeError(f"视觉阶段不完整: {sorted(phases)}")
    if not snapshot_events:
        raise RuntimeError("没有生成 SolidWorks 主窗口快照")
    if delivery is None:
        raise RuntimeError("保存步骤没有写入模型统计")
    if not part.is_file() or part.stat().st_size <= 0:
        raise RuntimeError("SLDPRT 文件不存在或为空")

    snapshot_path = frames / Path(
        snapshot_events[-1]["data"]["snapshotPath"]
    ).name
    if not snapshot_path.is_file():
        raise RuntimeError(f"事件中的快照不存在: {snapshot_path}")
    with Image.open(snapshot_path) as image:
        image.verify()
    if snapshot_path.stat().st_size > 8 * 1024 * 1024:
        raise RuntimeError("快照超过 8 MiB")

    stats = delivery["data"]["stats"]
    if float(stats.get("volumeMm3", 0)) <= 0:
        raise RuntimeError(f"体积统计无效: {stats}")
    if float(stats.get("featureCount", 0)) <= 0:
        raise RuntimeError(f"特征数统计无效: {stats}")

    deadline = time.monotonic() + 10
    remaining_started: list[int] = []
    while time.monotonic() < deadline:
        after = solidworks_processes() or {}
        remaining_started = sorted(set(after) - set(before))
        if not remaining_started:
            break
        time.sleep(0.25)
    if remaining_started:
        raise RuntimeError(f"冒烟结束后仍有新 SolidWorks 进程: {remaining_started}")
    report = {
        "events": len(payload),
        "completed": len(completed),
        "snapshots": len(snapshot_events),
        "part": str(part),
        "snapshot": str(snapshot_path),
        "stats": stats,
        "remaining_started_solidworks_pids": remaining_started,
    }
    (output / "smoke-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
