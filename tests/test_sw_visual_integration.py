import contextlib
import json
from types import SimpleNamespace

from scripts import sw_session, sw_visual_trace


def test_new_part_uses_visual_step(monkeypatch):
    entered = []

    @contextlib.contextmanager
    def fake_step(step_id, phase, title, message="", snapshot=True):
        entered.append((step_id, phase, title))
        yield

    monkeypatch.setattr(sw_session, "visual_step", fake_step)
    monkeypatch.setattr(
        sw_session,
        "connect_solidworks",
        lambda **_: (
            SimpleNamespace(),
            None,
            {"started_by_cad_studio": False, "process_id": 7},
        ),
    )
    monkeypatch.setattr(
        sw_session,
        "new_document",
        lambda *_args, **_kwargs: SimpleNamespace(GetTitle=lambda: "Part1"),
    )

    session = sw_session.SolidWorksSession()
    session.new_part()

    assert entered == [("part-new-part", "planning", "创建零件文档")]


def test_save_attaches_measured_visual_stats(tmp_path, monkeypatch):
    event_file = tmp_path / "events" / "job-save.jsonl"
    monkeypatch.setenv("CADSTUDIO_JOB_ID", "job-save")
    monkeypatch.setenv("CADSTUDIO_VISUAL_EVENT_FILE", str(event_file))
    monkeypatch.setattr(sw_session, "save_document", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(
        sw_session,
        "collect_mass_properties",
        lambda _model: {"volume_mm3": 28378.5},
    )
    monkeypatch.setattr(sw_session, "_feature_count", lambda _model: 6)

    session = object.__new__(sw_session.SolidWorksSession)
    session.model = SimpleNamespace()
    session._owned_documents = []

    assert session.save(file_path=str(tmp_path / "part.SLDPRT")) is True

    completed = [
        json.loads(line)
        for line in event_file.read_text(encoding="utf-8").splitlines()
        if line
    ][-1]
    assert completed["type"] == "visual.step.completed"
    assert completed["data"]["stats"] == {
        "volumeMm3": 28378.5,
        "featureCount": 6,
    }
