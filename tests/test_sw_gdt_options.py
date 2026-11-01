"""扩展 GD&T 的独立 XML 契约、非法组合和原生审查防回归。"""
from copy import deepcopy
import json
import xml.etree.ElementTree as ET

import pytest

from scripts.sw_gdt_annotation import build_gtol_xmls, referenced_datums
from scripts.sw_gdt_copy import SCHEMA
from scripts.sw_drawing_native import validate_native_requests


def frame(**changes):
    return {"characteristic": "position", "tolerance": "0.2", "diameter": True, "datums": ["A"], **changes}


def xml(**changes):
    return ET.fromstring(build_gtol_xmls(frame(**changes))[0])


def test_common_and_sub_datums_are_one_compartment_with_individual_members():
    datums = [{"common": ["A", {"label": "B", "materialCondition": "L"}], "subDatums": [["C", "D"]]}, "E"]
    root = xml(datums=datums)
    compartments = root.findall("DatumCompartment")
    assert len(compartments) == 3
    assert [item.text for item in compartments[0].findall("Datums/DatumDetail/DatumLetter")] == ["A", "B"]
    assert compartments[0].findtext("Datums/DatumDetail[2]/DatumMaterialCondition") == "LeastMaterialCondition"
    assert [item.text for item in compartments[0].findall("Datums/SubDatums/DatumDetail/DatumLetter")] == ["C", "D"]
    assert compartments[1].findtext("DatumDetail/DatumLetter") == "E"
    assert referenced_datums(frame(datums=datums)) == {"A", "B", "C", "D", "E"}


def test_projected_zone_and_reciprocity_keep_official_xml_order_and_values():
    root = xml(materialCondition="M", options={"projectedZone": {"projection": "12", "range": "4"}, "reciprocity": True})
    assert [item.tag for item in root][:4] == ["ToleranceSymbol", "ToleranceRangeInfo", "FeatureInfo", "MaterialCondition"]
    assert root.findtext("FeatureInfo/ProjectedToleranceZone") == "true"
    assert root.findtext("FeatureInfo/Projection") == "12"
    assert root.findtext("FeatureInfo/ProjectionRange") == "4"
    assert root.findtext("MaterialCondition/ReciprocityRequirement") == "true"


def test_profile_offsets_constraints_and_unequal_distribution_are_native_nodes():
    root = xml(characteristic="surface_profile", diameter=False, options={"profileZone": {"offsets": [
        {"direction": "outside", "value": "0.1"}, {"direction": "inside", "value": "0.05"}],
        "combination": "CZ", "dynamic": True, "constraints": ["offset", "orientationOnly"]}})
    assert root.findtext("OffsetZoneInfo/ToleranceZoneOffset/OutsideFirstZoneOffset") == "true"
    assert root.findtext("OffsetZoneInfo/ToleranceZoneOffset/FirstOffset") == "0.1"
    assert root.findtext("OffsetZoneInfo/ToleranceZoneOffset/InsideSecondZoneOffset") == "true"
    assert root.findtext("OffsetZoneInfo/ToleranceZoneOffset/SecondOffset") == "0.05"
    assert root.findtext("OffsetZoneInfo/CombinationSymbol") == "CZ"
    assert root.find("OffsetZoneInfo/Combination") is None  # 官方公开 XSD 与 SW2026 实际格式存在差异。
    assert [x.text for x in root.findall("OffsetZoneInfo/Constraint")] == ["OffsetToleranceZone", "OrientationOnly"]
    unequal = xml(characteristic="line_profile", diameter=False, options={"profileZone": {"unequalOutside": "0.05"}})
    assert unequal.findtext("OffsetZoneInfo/UnequallyDisposedProfile/OutsideDisposition") == "0.05"


def test_local_range_maximum_filter_and_state_values_do_not_fall_back_to_notes():
    root = xml(options={"zoneShape": "sphericalDiameter", "unitZone": {"separator": "/", "value": "100", "symbol": "none",
                       "limit": {"separator": "X", "value": "50", "symbol": "square"}},
                       "maxTolerance": {"value": "0.5", "diameter": True}, "associatedFeature": "LeastSquares",
                       "filters": [{"symbol": "G", "cutOff": "0.8", "shortWave": True, "separator": "X", "second": {"cutOff": "2.5", "longWave": True}}],
                       "associatedCharacteristic": "C", "parametricCharacteristic": "P", "freeState": True, "statistical": True})
    assert root.findtext("ToleranceRangeInfo/PrimaryRangeSymbol") == "sPhi"
    assert root.find("ToleranceRangeInfo/ToleranceZoneSymbol") is not None
    assert not root.findtext("ToleranceRangeInfo/ToleranceZoneSymbol")
    assert root.findtext("ToleranceRangeInfo/RestrictedToleranceZoneLimitSymbol") == "sqr"
    assert root.findtext("ToleranceRangeInfo/MaxToleranceValue") == "0.5"
    assert root.findtext("FeatureInfo/Filters/FilterDetail/CutOff2") == "2.5"
    assert root.findtext("StateSymbol") == root.findtext("StatisticalSymbol") == "true"
    assert root.find("Note") is None


def test_datum_modifiers_constraints_and_translation_vector_preserve_order():
    root = xml(datums=[{"label": "A", "materialCondition": "M", "modifiers": {"situation": "plane", "section": "cross", "projection": "5", "freeState": True},
                        "constraints": {"rotationY": True, "translation": ["1", "-2", "0"]}}])
    compartment = root.find("DatumCompartment")
    assert [x.tag for x in compartment] == ["RotationalConstraintAlongYAxis", "Translation", "TranslationValueI", "TranslationValueJ", "TranslationValueK", "DatumDetail"]
    assert compartment.findtext("TranslationValueJ") == "-2"
    assert [x.tag for x in compartment.find("DatumDetail")] == ["DatumLetter", "PlaneSituationFeature", "FeatureProjection", "Projection", "DatumMaterialCondition", "FreeState", "AnyCrossSection"]


def test_false_defaults_generate_the_same_xml_as_omitted_options():
    explicit = build_gtol_xmls(frame(datums=[{"label": "A", "modifiers": {"freeState": False}, "constraints": {"rotationX": False}}],
                                   options={"freeState": False, "statistical": False, "derivedFeature": False, "reciprocity": False, "profileZone": {"dynamic": False}}))
    assert explicit == build_gtol_xmls(frame())


@pytest.mark.parametrize("library,prefix", [("iso", "IGTOL"), ("asme", "GTOL"), ("gb", "GGTOL")])
def test_symbol_library_is_an_explicit_enum(library, prefix):
    assert xml(options={"symbolLibrary": library}).findtext("ToleranceSymbol") == prefix + "-POSI"


@pytest.mark.parametrize("changes", [
    {"datums": [{"common": ["A"]}]}, {"datums": [{"common": ["A", "A"]}]},
    {"datums": [{"common": ["A", "B"], "subDatums": [["C", "A"]]}]},
    {"datums": ["A-B"]}, {"datums": [{"common": ["A", {"label": "B", "constraints": {"rotationX": True}}]}]},
    {"datums": [{"label": "A", "constraints": {"translation": ["1", "2"]}}]},
    {"options": {"xml": "<injected/>"}}, {"options": {"zoneShape": "square"}},
    {"options": {"projectedZone": {"projection": "0"}}}, {"options": {"projectedZone": {"projection": "NaN"}}},
    {"options": {"projectedZone": {"projection": "1e2"}}}, {"options": {"reciprocity": True}},
    {"materialCondition": "S", "options": {"reciprocity": True}},
    {"options": {"maxTolerance": {"value": "0.1", "diameter": True}}},
    {"options": {"freeState": 1}}, {"options": {"profileZone": {"unequalOutside": "0.1"}}},
    {"characteristic": "line_profile", "diameter": False, "options": {"profileZone": {"unequalOutside": "0.3"}}},
    {"options": {"profileZone": {"combination": "CZ", "constraints": ["offset", "offset"]}}},
    {"options": {"filters": [{"symbol": "UNKNOWN", "cutOff": "1"}]}},
    {"options": {"filters": [{"symbol": "G", "cutOff": "1", "second": {"cutOff": "2"}}]}},
])
def test_invalid_extended_combinations_are_rejected_before_com(changes):
    with pytest.raises(ValueError):
        build_gtol_xmls(frame(**changes))


def test_common_datum_members_must_all_exist_in_native_drawing_spec():
    request = frame(id="POS", view="front", target={"kind": "dimension", "dimensionId": "HOLE"}, datums=[{"common": ["A", "B"]}])
    value = {"documentType": "part", "professionalAnnotations": {"datums": [{"id": "DAT_A", "label": "A", "view": "front", "target": {}}], "geometricTolerances": [request]}}
    assert any("未声明的基准" in item["message"] for item in validate_native_requests(value))


def test_composite_common_group_cannot_change_shape_or_drop_only_half_a_group():
    upper = frame(datums=[{"common": ["A", "B"]}], options={"zoneShape": "sphericalDiameter"})
    lower = {**deepcopy(upper), "tolerance": "0.1", "composite": True}
    lower["options"]["zoneShape"] = "diameter"
    with pytest.raises(ValueError, match="形状"):
        build_gtol_xmls({"frames": [upper, lower]})
    lower = {**deepcopy(upper), "tolerance": "0.1", "composite": True, "datums": ["A"]}
    with pytest.raises(ValueError, match="前缀"):
        build_gtol_xmls({"frames": [upper, lower]})


def test_all_shared_extended_schema_definitions_match():
    copy = json.loads(SCHEMA.read_text(encoding="utf-8"))
    drawing = json.loads(SCHEMA.with_name("drawing_spec.schema.json").read_text(encoding="utf-8"))
    for key in ("datumReference", "datumMember", "datumModifiers", "datumConstraints", "unitZone", "maxTolerance", "profileZone", "projectedZone", "gdtFilter", "gdtOptions", "gtol", "frame"):
        assert copy["$defs"][key] == drawing["$defs"][key], key


@pytest.mark.parametrize("change", ["projected_height", "member", "material", "combination"])
def test_extended_review_rejects_missing_or_changed_native_semantics(change):
    from scripts import sw_drawing_review
    request = frame(id="POS", view="front", target={"kind": "dimension", "dimensionId": "HOLE"},
                    datums=[{"common": ["A", {"label": "B", "materialCondition": "M"}]}],
                    options={"projectedZone": {"projection": "12"}, "profileZone": {"combination": "CZ"}})
    tree = ET.fromstring(build_gtol_xmls(request)[0])
    if change == "projected_height":
        tree.find("FeatureInfo/Projection").text = "11"
    elif change == "member":
        parent = tree.find("DatumCompartment/Datums")
        parent.remove(parent.findall("DatumDetail")[1])
    elif change == "material":
        tree.find("DatumCompartment/Datums/DatumDetail[2]/DatumMaterialCondition").text = "LeastMaterialCondition"
    else:
        tree.find("OffsetZoneInfo/CombinationSymbol").text = "SZ"
    record = {"id": "POS", "semantic_view": "front", "target": request["target"], "frames": [{"xml": ET.tostring(tree, encoding="unicode")}]}
    report = sw_drawing_review._MODULE._professional_annotation_report(
        {"professionalAnnotations": {"geometricTolerances": [request]}}, {"professional_annotations": {"geometric_tolerances": [record]}})
    assert "POS" in report["missing"]


@pytest.mark.parametrize("change", ["missing_member", "zero_projection", "unknown_option", "group_duplicate", "invalid_translation", "flat_frames_mix"])
def test_invalid_extended_specs_block_without_connecting_or_creating_output(change, tmp_path, monkeypatch):
    from test_sw_drawing_native import spec
    from scripts import sw_drawing_package
    value = spec()
    request = value["professionalAnnotations"]["geometricTolerances"][0]
    upper = request["frames"][0]
    if change == "missing_member":
        upper["datums"] = [{"common": ["A", "B"]}]
        request["frames"] = [upper]
    elif change == "zero_projection":
        upper["options"] = {"projectedZone": {"projection": "0"}}
    elif change == "unknown_option":
        upper["options"] = {"rawXml": "<GtolFrame/>"}
    elif change == "group_duplicate":
        upper["datums"] = [{"common": ["A", "A"]}]
    elif change == "invalid_translation":
        upper["datums"] = [{"label": "A", "constraints": {"translation": ["1", "2"]}}]
    else:
        request["options"] = {"projectedZone": {"projection": "12"}}
    def forbidden(*args, **kwargs):
        raise AssertionError("无效扩展规格不应连接 SolidWorks")
    monkeypatch.setattr(sw_drawing_package, "SolidWorksSession", forbidden)
    output = tmp_path / "uncreated"
    assert sw_drawing_package.generate_package(value, output)["status"] == "blocked"
    assert not output.exists()
