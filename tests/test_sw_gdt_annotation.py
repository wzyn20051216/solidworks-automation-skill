"""GTol 输入必须明确且不会被误当成任意 XML。"""
import xml.etree.ElementTree as ET

import pytest

from scripts.sw_gdt_annotation import build_frame_xml, build_gtol_xmls, referenced_datums, _check_position, _confirm_attachment, _set_position


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


def test_composite_frames_keep_order_values_and_individual_datum_modifiers():
    upper = {"characteristic": "position", "tolerance": "0.2", "diameter": True,
             "datums": [{"label": "A", "materialCondition": "M"}, {"label": "B", "materialCondition": "L"}]}
    lower = {**upper, "tolerance": "0.1", "datums": [upper["datums"][0]], "composite": True}
    request = {"frames": [upper, lower]}
    xmls = [ET.fromstring(xml) for xml in build_gtol_xmls(request)]
    assert [frame.findtext("ToleranceSymbol") for frame in xmls] == ["IGTOL-POSI", ""]
    assert [frame.findtext("ToleranceRangeInfo/PrimaryToleranceValue") for frame in xmls] == ["0.2", "0.1"]
    assert [node.text for node in xmls[0].findall(".//DatumMaterialCondition")] == ["MaximumMaterialCondition", "LeastMaterialCondition"]
    assert referenced_datums(request) == {"A", "B"}


@pytest.mark.parametrize("change", ["first_composite", "looser", "different_symbol", "datum_reorder", "duplicate", "unknown_modifier", "mixed"])
def test_invalid_multi_frame_relationships_are_blocked(change):
    first = {"characteristic": "position", "tolerance": "0.2", "diameter": True, "datums": ["A", "B"]}
    second = {**first, "tolerance": "0.1", "composite": True}
    request = {"frames": [first, second]}
    if change == "first_composite":
        first["composite"] = True
    elif change == "looser":
        second["tolerance"] = "0.3"
    elif change == "different_symbol":
        second["characteristic"] = "parallelism"
    elif change == "datum_reorder":
        second["datums"] = ["B", "A"]
    elif change == "duplicate":
        first["datums"] = ["A", {"label": "A"}]
    elif change == "unknown_modifier":
        first["datums"] = [{"label": "A", "materialCondition": "Z"}]
    else:
        request["tolerance"] = "0.2"
    with pytest.raises(ValueError):
        build_gtol_xmls(request)
