"""@brief 完全定义以求解回读及可编辑尺寸为准，不接受返回码假通过。"""
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from scripts.sw_sketch_quality import fully_define_sketch, inspect_sketch


def sketch_fixture(status=3, fix=False):
    """@brief 构造可检查的草图证据。"""
    dim = SimpleNamespace(GetNameForSelection=lambda: "D1@Sketch1")
    relation = SimpleNamespace(GetRelationType=lambda: 17 if fix else 1, GetDisplayDimension=lambda: dim)
    return SimpleNamespace(GetConstrainedStatus=lambda: status,
        RelationManager=SimpleNamespace(GetRelations=lambda _: [relation]))


def test_actual_dimensions_and_no_fix_are_required():
    record = inspect_sketch(sketch_fixture())
    assert record["status"] == "pass"
    assert record["dimension_count"] == 1
    assert inspect_sketch(sketch_fixture(fix=True))["status"] == "review_required"


def test_api_return_does_not_override_underdefined_state():
    active = sketch_fixture(status=2)
    model = SimpleNamespace(SketchManager=SimpleNamespace(ActiveSketch=active, FullyDefineSketch=lambda *args: 0),
        Extension=SimpleNamespace(SelectByID2=lambda *args: True), ClearSelection2=lambda _: None)
    with pytest.raises(RuntimeError, match="草图未通过"):
        fully_define_sketch(model)


def test_missing_evidence_is_blocked():
    record = inspect_sketch(SimpleNamespace(GetConstrainedStatus=lambda: 3))
    assert record["status"] == "blocked"
    assert record["dimension_count"] is None
