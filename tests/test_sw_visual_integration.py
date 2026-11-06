import contextlib
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
