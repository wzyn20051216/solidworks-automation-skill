from pathlib import Path

from scripts import sw_window_capture


def test_snapshot_filename_contains_sequence_phase_and_step():
    assert sw_window_capture.snapshot_filename(7, "feature", "main-shaft") == (
        "step-007-feature-main-shaft.png"
    )


def test_prune_keeps_first_and_last_per_phase(tmp_path):
    for index in range(1, 101):
        phase = "sketch" if index <= 50 else "feature"
        path = tmp_path / f"step-{index:03d}-{phase}-step-{index}.png"
        path.write_bytes(b"png")

    kept = sw_window_capture.prune_snapshots(tmp_path, max_frames=30)
    names = {path.name for path in kept}

    assert "step-001-sketch-step-1.png" in names
    assert "step-050-sketch-step-50.png" in names
    assert "step-051-feature-step-51.png" in names
    assert "step-100-feature-step-100.png" in names
    assert len(kept) <= 30


def test_capture_returns_none_when_no_solidworks_window(monkeypatch, tmp_path):
    monkeypatch.setattr(sw_window_capture, "_solidworks_window_rect", lambda: None)
    assert (
        sw_window_capture.capture_solidworks_window(
            tmp_path, 1, "planning", "planning-open"
        )
        is None
    )
