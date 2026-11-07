import json
from pathlib import Path

import pytest

from scripts.sw_visual_trace import VisualTrace, traced_step


def read_events(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def test_step_writes_started_and_completed(tmp_path, monkeypatch):
    event_file = tmp_path / "events" / "job-1.jsonl"
    frames = tmp_path / "frames"
    monkeypatch.setenv("CADSTUDIO_JOB_ID", "job-1")
    monkeypatch.setenv("CADSTUDIO_VISUAL_EVENT_FILE", str(event_file))
    monkeypatch.setenv("CADSTUDIO_VISUAL_FRAME_DIR", str(frames))

    trace = VisualTrace.from_environment()
    assert trace is not None
    with trace.step("main-sketch", "sketch", "绘制主体草图", message="正在创建中心线"):
        pass

    events = read_events(event_file)
    assert [item["type"] for item in events] == [
        "visual.step.started",
        "visual.step.completed",
    ]
    assert events[0]["data"]["stepId"] == "sketch-main-sketch"
    assert events[0]["data"]["phase"] == "sketch"
    assert events[1]["progress"] == 20


def test_step_failure_writes_failed_event(tmp_path, monkeypatch):
    event_file = tmp_path / "events" / "job-1.jsonl"
    monkeypatch.setenv("CADSTUDIO_JOB_ID", "job-1")
    monkeypatch.setenv("CADSTUDIO_VISUAL_EVENT_FILE", str(event_file))

    trace = VisualTrace.from_environment()
    assert trace is not None
    with pytest.raises(RuntimeError, match="boom"):
        with trace.step("main-feature", "feature", "生成主体"):
            raise RuntimeError("boom")

    events = read_events(event_file)
    assert events[-1]["type"] == "visual.step.failed"
    assert events[-1]["data"]["error"] == "boom"


def test_decorator_emits_only_when_environment_is_present(tmp_path, monkeypatch):
    event_file = tmp_path / "events" / "job-2.jsonl"
    monkeypatch.delenv("CADSTUDIO_JOB_ID", raising=False)
    monkeypatch.delenv("CADSTUDIO_VISUAL_EVENT_FILE", raising=False)

    @traced_step("save", "delivery", "保存模型")
    def save_model():
        return "saved"

    assert save_model() == "saved"
    assert not event_file.exists()

    monkeypatch.setenv("CADSTUDIO_JOB_ID", "job-2")
    monkeypatch.setenv("CADSTUDIO_VISUAL_EVENT_FILE", str(event_file))
    assert save_model() == "saved"
    assert [item["type"] for item in read_events(event_file)] == [
        "visual.step.started",
        "visual.step.completed",
    ]


def test_oversized_payload_is_rejected(tmp_path, monkeypatch):
    event_file = tmp_path / "events" / "job-3.jsonl"
    monkeypatch.setenv("CADSTUDIO_JOB_ID", "job-3")
    monkeypatch.setenv("CADSTUDIO_VISUAL_EVENT_FILE", str(event_file))
    trace = VisualTrace.from_environment()
    assert trace is not None

    with pytest.raises(ValueError, match="64 KiB"):
        trace.emit("visual.plan.ready", "x" * 70000)


def test_step_can_attach_real_stats(tmp_path, monkeypatch):
    event_file = tmp_path / "events" / "job-4.jsonl"
    monkeypatch.setenv("CADSTUDIO_JOB_ID", "job-4")
    monkeypatch.setenv("CADSTUDIO_VISUAL_EVENT_FILE", str(event_file))
    trace = VisualTrace.from_environment()
    assert trace is not None

    with trace.step("save", "delivery", "保存模型", snapshot=False) as handle:
        handle.stats.update({"volumeMm3": 28378.5, "featureCount": 6})

    completed = read_events(event_file)[-1]
    assert completed["data"]["stats"] == {
        "volumeMm3": 28378.5,
        "featureCount": 6,
    }


def test_sequence_continues_across_separate_visual_step_calls(tmp_path, monkeypatch):
    from scripts.sw_visual_trace import visual_step

    event_file = tmp_path / "events" / "job-5.jsonl"
    monkeypatch.setenv("CADSTUDIO_JOB_ID", "job-5")
    monkeypatch.setenv("CADSTUDIO_VISUAL_EVENT_FILE", str(event_file))

    with visual_step("first", "feature", "第一步", snapshot=False):
        pass
    with visual_step("second", "feature", "第二步", snapshot=False):
        pass

    sequences = [
        item["data"]["sequence"]
        for item in read_events(event_file)
        if item["type"] == "visual.step.started"
    ]
    assert sequences == [1, 2]
