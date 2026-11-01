"""GTol 输入必须明确且不会被误当成任意 XML。"""
import xml.etree.ElementTree as ET

import pytest

from scripts.sw_gdt_annotation import build_frame_xml, _check_position, _confirm_attachment, _set_position


def test_position_frame_records_explicit_value_and_datum_order():
    root = ET.fromstring(build_frame_xml("position", "0.20", True, ["A", "B", "C"]))
    assert root.findtext("ToleranceSymbol") == "IGTOL-POSI"
    assert root.findtext("ToleranceRangeInfo/PrimaryToleranceValue") == "0.20"
    assert root.findtext("ToleranceRangeInfo/PrimaryRangeSymbol") == "phi"
    assert [x.text for x in root.findall(".//DatumLetter")] == ["A", "B", "C"]


@pytest.mark.parametrize("characteristic,tolerance,diameter,datums", [
    ("flatness", "0.2", True, ["A"]),
    ("position", "0", True, ["A"]),
    ("position", "nan", True, ["A"]),
    ("position", "1e-3", True, ["A"]),
    ("position", "0.2", 1, ["A"]),
    ("position", "0.2", True, ["A", "A"]),
    ("position", "0.2", True, ["<A>"]),
    ("position", "0.2", True, ["A", "B", "C", "D"]),
])
def test_rejects_unverified_or_ambiguous_input(characteristic, tolerance, diameter, datums):
    with pytest.raises(ValueError):
        build_frame_xml(characteristic, tolerance, diameter, datums)


@pytest.mark.parametrize("position", [(float("nan"), 0), (True, 0), (-1, 0), (0,), "1,2"])
def test_position_must_be_explicit_finite_sheet_coordinates(position):
    with pytest.raises(ValueError):
        _check_position(position)


def test_attachment_must_resolve_to_exact_selected_entity():
    edge, other = object(), object()

    class App:
        def IsSame(self, a, b):
            return int(a is b)

    class Annotation:
        def __init__(self, target):
            self.target = target

        def GetAttachedEntityCount3(self):
            return 1

        def GetAttachedEntities3(self):
            return [self.target]

    _confirm_attachment(App(), Annotation(edge), edge)
    for target in (other, None):
        with pytest.raises(RuntimeError):
            _confirm_attachment(App(), Annotation(target), edge)


def test_position_setter_success_does_not_hide_adjusted_position():
    class Annotation:
        def SetPosition(self, x, y, z):
            return True

        def GetPosition(self):
            return (0.141, 0.1, 0.0)

    with pytest.raises(RuntimeError, match="实际位置"):
        _set_position(Annotation(), 0.07, 0.1)
    _set_position(Annotation(), 0.141, 0.1)


@pytest.mark.parametrize("kind,code", [
    ("straightness", "STRAIGHT"), ("flatness", "FLAT"), ("circularity", "CIRC"),
    ("cylindricity", "CYL"), ("line_profile", "LPROF"), ("surface_profile", "SPROF"),
    ("parallelism", "PARA"), ("perpendicularity", "PERP"), ("angularity", "ANGULAR"),
    ("position", "POSI"), ("concentricity", "CONC"), ("symmetry", "SYMMETRY"),
    ("circular_runout", "SRUN"), ("total_runout", "TRUN"),
])
def test_native_symbol_mapping_uses_official_iso_library(kind, code):
    datums = [] if kind in {"straightness", "flatness", "circularity", "cylindricity"} else ["A"]
    root = ET.fromstring(build_frame_xml(kind, "0.02", False, datums))
    assert root.findtext("ToleranceSymbol") == "IGTOL-" + code


@pytest.mark.parametrize("condition,node", [("M", "MaximumMaterialCondition"), ("L", "LeastMaterialCondition"), ("S", "RegardlessToFeatureSize")])
def test_material_condition_is_structured_not_free_text(condition, node):
    root = ET.fromstring(build_frame_xml("position", "0.02", True, ["A"], material_condition=condition))
    assert root.findtext("MaterialCondition/" + node) == "true"


@pytest.mark.parametrize("kind,diameter,datums,condition", [
    ("flatness", False, ["A"], None), ("circularity", True, [], None),
    ("position", True, [], None), ("parallelism", False, ["A"], "M"),
    ("position", True, ["A"], "<M>"),
])
def test_semantically_conflicting_options_are_rejected(kind, diameter, datums, condition):
    with pytest.raises(ValueError):
        build_frame_xml(kind, "0.02", diameter, datums, material_condition=condition)
