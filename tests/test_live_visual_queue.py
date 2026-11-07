from pathlib import Path

from apps.desktop.cad_workbench.queue_worker import (
    event_path_for,
    visual_frame_dir_for,
    visual_runtime_env,
)


def test_visual_runtime_env_uses_existing_event_stream(tmp_path):
    job = {
        "id": "job-visual-1",
        "uiConfig": {"visualMode": True},
    }

    env = visual_runtime_env(job, tmp_path)

    assert env["CADSTUDIO_JOB_ID"] == "job-visual-1"
    assert env["CADSTUDIO_VISUAL_MODE"] == "1"
    assert env["CADSTUDIO_VISUAL_EVENT_FILE"] == str(
        event_path_for(tmp_path, "job-visual-1")
    )
    assert env["CADSTUDIO_VISUAL_FRAME_DIR"] == str(
        visual_frame_dir_for(tmp_path, "job-visual-1")
    )


def test_visual_runtime_env_is_empty_when_disabled(tmp_path):
    assert (
        visual_runtime_env(
            {"id": "job-normal", "uiConfig": {"visualMode": False}},
            tmp_path,
        )
        == {}
    )
