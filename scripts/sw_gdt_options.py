"""SW2026 GTol XML 的受限结构化选项；只表达明确输入，不求解制造公差。"""
from __future__ import annotations

from decimal import Decimal
import re
import xml.etree.ElementTree as ET

MATERIAL_NAMES = {"M": "MaximumMaterialCondition", "L": "LeastMaterialCondition", "S": "RegardlessToFeatureSize"}
RANGE_SYMBOLS = {"none": "", "diameter": "phi", "sphericalDiameter": "sPhi", "square": "sqr", "angle": "deg"}
SITUATIONS = {"plane": "PlaneSituationFeature", "straightLine": "StraightLineSituationFeature", "point": "PointSituationFeature"}
SECTIONS = {"cross": "AnyCrossSection", "longitudinal": "AnyLongitudinalSection"}
COMPARTMENT_FLAGS = {
    "translationX": "TranslationConstraintAlongXAxis", "translationY": "TranslationConstraintAlongYAxis", "translationZ": "TranslationConstraintAlongZAxis",
    "rotationX": "RotationalConstraintAlongXAxis", "rotationY": "RotationalConstraintAlongYAxis", "rotationZ": "RotationalConstraintAlongZAxis",
    "contactFeature": "ContactFeature", "orientationOnly": "OrientationDegreesOfFreedomOnly", "variableDistance": "VariableLinearDistanceWithinACollectionOfFeatures",
}
PROFILE_CONSTRAINTS = {"offset": "OffsetToleranceZone", "angularOffset": "UnspecifiedAngularToleranceZoneOffset", "orientationOnly": "OrientationOnly"}
FILTER_SYMBOLS = ("G", "S", "SW", "CW", "RG", "RS", "OB", "OH", "OD", "CB", "CH", "CD", "AB", "AH", "AD", "F", "H")
ASSOCIATED_FEATURES = ("Minimax", "LeastSquares", "MinimumCircumscribed", "Tangent", "MaximumInscribed")
OPTION_FIELDS = {"symbolLibrary", "zoneShape", "unitZone", "maxTolerance", "profileZone", "projectedZone", "associatedFeature",
                 "derivedFeature", "filters", "associatedCharacteristic", "parametricCharacteristic", "reciprocity", "freeState", "statistical"}


def object_fields(value, allowed, required=()):
    if not isinstance(value, dict) or set(value) - set(allowed) or not set(required) <= set(value):
        raise ValueError("GD&T 选项字段缺失、类型错误或包含未知字段")
    return value


def decimal_text(value, *, positive=False, signed=False):
    pattern = r"-?\d+(?:\.\d+)?" if signed else r"\d+(?:\.\d+)?"
    if not isinstance(value, str) or len(value) > 32 or not re.fullmatch(pattern, value):
        raise ValueError("GD&T 数值必须是显式、有限、非指数十进制字符串")
    if positive and Decimal(value) <= 0:
        raise ValueError("GD&T 数值必须大于零")
    return value


def boolean(value):
    if not isinstance(value, bool):
        raise ValueError("GD&T 开关必须为布尔值")
    return "true" if value else "false"


def enum(value, choices):
    if not isinstance(value, str) or value not in choices:
        raise ValueError("GD&T 选项枚举无效")
    return value


def append_flag(parent, name, value):
    # SW2026 会在回读中省略 false 缺省项；创建时直接生成同一规范形式。
    boolean(value)
    if value:
        ET.SubElement(parent, name).text = "true"


def normalize_constraints(value):
    object_fields(value, {*COMPARTMENT_FLAGS, "translation"})
    for key, item in value.items():
        if key == "translation":
            if not isinstance(item, list) or len(item) != 3:
                raise ValueError("基准平移必须提供 I/J/K 三个明确分量")
            for entry in item:
                decimal_text(entry, signed=True)
        else:
            boolean(item)
    return {key: item for key, item in value.items() if key == "translation" or item}


def normalize_detail(value, *, compartment=True):
    if isinstance(value, str):
        value = {"label": value}
    allowed = {"label", "materialCondition", "modifiers"} | ({"constraints"} if compartment else set())
    object_fields(value, allowed, {"label"})
    if not isinstance(value["label"], str) or not re.fullmatch(r"[A-Z]{1,2}", value["label"]):
        raise ValueError("基准标识无效")
    condition = value.get("materialCondition")
    if condition is not None:
        enum(condition, MATERIAL_NAMES)
    result = {"label": value["label"], "materialCondition": condition}
    if "modifiers" in value:
        modifiers = object_fields(value["modifiers"], {"situation", "section", "projection", "freeState"})
        for key, item in modifiers.items():
            if key == "situation":
                enum(item, SITUATIONS)
            elif key == "section":
                enum(item, SECTIONS)
            elif key == "projection":
                decimal_text(item, positive=True)
            else:
                boolean(item)
        modifiers = {key: item for key, item in modifiers.items() if key != "freeState" or item}
        if modifiers:
            result["modifiers"] = modifiers
    if "constraints" in value:
        constraints = normalize_constraints(value["constraints"])
        if constraints:
            result["constraints"] = constraints
    return result


def datum_references(datums):
    """最多三个顺序基准格；组内字母分别确认，不把 A-B 当作一个基准标识。"""
    if not isinstance(datums, list) or len(datums) > 3:
        raise ValueError("最多允许三个顺序基准")
    result, labels = [], []
    for value in datums:
        if isinstance(value, dict) and "common" in value:
            object_fields(value, {"common", "subDatums", "constraints"}, {"common"})
            members = value["common"]
            if not isinstance(members, list) or not 2 <= len(members) <= 8:
                raise ValueError("公共基准格必须包含 2..8 个明确基准")
            item = {"common": [normalize_detail(entry, compartment=False) for entry in members]}
            groups = value.get("subDatums", [])
            if not isinstance(groups, list) or len(groups) > 3:
                raise ValueError("子基准组数量无效")
            subgroups = []
            for group in groups:
                if not isinstance(group, list) or not 2 <= len(group) <= 8:
                    raise ValueError("子基准组必须包含 2..8 个明确基准")
                subgroups.append([normalize_detail(entry, compartment=False) for entry in group])
            if subgroups:
                item["subDatums"] = subgroups
            if "constraints" in value:
                constraints = normalize_constraints(value["constraints"])
                if constraints:
                    item["constraints"] = constraints
            labels.extend(entry["label"] for group in [item["common"], *subgroups] for entry in group)
        else:
            item = normalize_detail(value)
            labels.append(item["label"])
        result.append(item)
    if len(set(labels)) != len(labels):
        raise ValueError("同一框中的基准标识不得重复")
    return result


def datum_labels(datums):
    labels = set()
    for item in datum_references(datums):
        if "label" in item:
            labels.add(item["label"])
        else:
            labels.update(entry["label"] for group in [item["common"], *item.get("subDatums", [])] for entry in group)
    return labels


def _detail_xml(parent, item):
    detail = ET.SubElement(parent, "DatumDetail")
    ET.SubElement(detail, "DatumLetter").text = item["label"]
    modifiers = item.get("modifiers", {})
    if "situation" in modifiers:
        ET.SubElement(detail, SITUATIONS[modifiers["situation"]]).text = "true"
    if "projection" in modifiers:
        ET.SubElement(detail, "FeatureProjection").text = "true"
        ET.SubElement(detail, "Projection").text = modifiers["projection"]
    if item["materialCondition"]:
        ET.SubElement(detail, "DatumMaterialCondition").text = MATERIAL_NAMES[item["materialCondition"]]
    if "freeState" in modifiers:
        append_flag(detail, "FreeState", modifiers["freeState"])
    # 本机 SW2026 的规范回读将截面标志放在所有其他成员修饰之后。
    if "section" in modifiers:
        ET.SubElement(detail, SECTIONS[modifiers["section"]]).text = "true"


def append_datum_xml(compartment, item):
    constraints = item.get("constraints", {})
    for key, name in COMPARTMENT_FLAGS.items():
        if key in constraints:
            append_flag(compartment, name, constraints[key])
    if "translation" in constraints:
        ET.SubElement(compartment, "Translation").text = "true"
        for axis, value in zip("IJK", constraints["translation"]):
            ET.SubElement(compartment, "TranslationValue" + axis).text = value
    if "label" in item:
        _detail_xml(compartment, item)
    else:
        parent = ET.SubElement(compartment, "Datums")
        for entry in item["common"]:
            _detail_xml(parent, entry)
        for group in item.get("subDatums", []):
            sub = ET.SubElement(parent, "SubDatums")
            for entry in group:
                _detail_xml(sub, entry)


def _range_options(limits, options, tolerance, diameter):
    shape = options.get("zoneShape")
    if shape is not None:
        enum(shape, set(RANGE_SYMBOLS) - {"angle"})
        if (shape in {"diameter", "sphericalDiameter"}) != diameter:
            raise ValueError("zoneShape 与 diameter 公差带声明冲突")
        limits.find("PrimaryRangeSymbol").text = RANGE_SYMBOLS[shape]
    if "unitZone" in options:
        unit = object_fields(options["unitZone"], {"separator", "value", "symbol", "limit"}, {"separator", "value"})
        enum(unit["separator"], ("/", "-"))
        decimal_text(unit["value"], positive=True)
        ET.SubElement(limits, "ConjunctionSymbol1").text = unit["separator"]
        ET.SubElement(limits, "ToleranceZone").text = unit["value"]
        # 无符号时 SW2026 也会补出空节点，不能按公开 XSD 的 pattern 将其省略。
        ET.SubElement(limits, "ToleranceZoneSymbol").text = RANGE_SYMBOLS[enum(unit.get("symbol", "none"), RANGE_SYMBOLS)]
        if "limit" in unit:
            limit = object_fields(unit["limit"], {"separator", "value", "symbol"}, {"separator", "value"})
            ET.SubElement(limits, "ConjunctionSymbol2").text = enum(limit["separator"], ("X", "-"))
            ET.SubElement(limits, "RestrictedToleranceZoneLimit").text = decimal_text(limit["value"], positive=True)
            ET.SubElement(limits, "RestrictedToleranceZoneLimitSymbol").text = RANGE_SYMBOLS[enum(limit.get("symbol", "none"), RANGE_SYMBOLS)]
    if "maxTolerance" in options:
        maximum = object_fields(options["maxTolerance"], {"value", "diameter"}, {"value", "diameter"})
        decimal_text(maximum["value"], positive=True)
        boolean(maximum["diameter"])
        if Decimal(maximum["value"]) < Decimal(tolerance):
            raise ValueError("最大公差不能小于主公差")
        ET.SubElement(limits, "ApplyMAXTolerance").text = "true"
        ET.SubElement(limits, "MaxToleranceSymbol").text = "phi" if maximum["diameter"] else ""
        ET.SubElement(limits, "MaxToleranceValue").text = maximum["value"]


def _profile_options(root, value, characteristic, tolerance):
    value = object_fields(value, {"unequalOutside", "offsets", "dynamic", "combination", "constraints"})
    if not value or {"unequalOutside", "offsets"} <= set(value):
        raise ValueError("轮廓带选项不能为空，不等分布与偏置不能同时指定")
    if (set(value) & {"unequalOutside", "offsets"} or value.get("dynamic") is True) and characteristic not in {"line_profile", "surface_profile"}:
        raise ValueError("不等分布、轮廓偏置和动态轮廓必须使用轮廓度")
    parent = ET.SubElement(root, "OffsetZoneInfo")
    if "unequalOutside" in value:
        decimal_text(value["unequalOutside"])
        if Decimal(value["unequalOutside"]) > Decimal(tolerance):
            raise ValueError("轮廓外侧分配量不能超过整个公差带")
        profile = ET.SubElement(parent, "UnequallyDisposedProfile")
        ET.SubElement(profile, "OutsideDisposition").text = value["unequalOutside"]
    elif "offsets" in value:
        offsets = value["offsets"]
        if not isinstance(offsets, list) or not 1 <= len(offsets) <= 2:
            raise ValueError("轮廓偏置必须包含一或两个明确方向和数值")
        profile = ET.SubElement(parent, "ToleranceZoneOffset")
        for prefix, offset in zip(("First", "Second"), offsets):
            object_fields(offset, {"direction", "value"}, {"direction", "value"})
            direction = enum(offset["direction"], ("outside", "inside"))
            ET.SubElement(profile, direction.title() + prefix + "ZoneOffset").text = "true"
            ET.SubElement(profile, prefix + "Offset").text = decimal_text(offset["value"])
    if "dynamic" in value:
        append_flag(parent, "DynamicProfile", value["dynamic"])
    if "combination" in value:
        # SW2026 SP1.1 原生 UI 回读为 CombinationSymbol；公开 XSD 的 Combination 会被静默丢弃。
        ET.SubElement(parent, "CombinationSymbol").text = enum(value["combination"], ("CZ", "SZ"))
    if "constraints" in value:
        constraints = value["constraints"]
        if (not isinstance(constraints, list) or not 1 <= len(constraints) <= 3
                or any(not isinstance(item, str) or item not in PROFILE_CONSTRAINTS for item in constraints)
                or len(set(constraints)) != len(constraints)):
            raise ValueError("公差带约束必须为不重复的 1..3 项")
        for item in constraints:
            ET.SubElement(parent, "Constraint").text = PROFILE_CONSTRAINTS[enum(item, PROFILE_CONSTRAINTS)]
    if not len(parent):
        root.remove(parent)


def _filter_xml(parent, value):
    object_fields(value, {"symbol", "cutOff", "shortWave", "longWave", "separator", "second"}, {"symbol", "cutOff"})
    detail = ET.SubElement(parent, "FilterDetail")
    ET.SubElement(detail, "FilterSymbol").text = enum(value["symbol"], FILTER_SYMBOLS)
    if "shortWave" in value:
        append_flag(detail, "ShortWavePassFilter", value["shortWave"])
    ET.SubElement(detail, "CutOff").text = decimal_text(value["cutOff"], positive=True)
    if "longWave" in value:
        append_flag(detail, "LongWavePassFilter", value["longWave"])
    separator = value.get("separator", "")
    if "second" in value and separator not in ("Space", "X"):
        raise ValueError("双滤波段必须指定分隔方式")
    ET.SubElement(detail, "FilterIndicationSeparator").text = enum(separator, ("", "Space", "X"))
    if "second" in value:
        second = object_fields(value["second"], {"cutOff", "shortWave", "longWave"}, {"cutOff"})
        if "shortWave" in second:
            append_flag(detail, "ShortWavePassFilter2", second["shortWave"])
        ET.SubElement(detail, "CutOff2").text = decimal_text(second["cutOff"], positive=True)
        if "longWave" in second:
            append_flag(detail, "LongWavePassFilter2", second["longWave"])


def append_options_before_material(root, limits, options, *, characteristic, tolerance, diameter, material_condition):
    """按官方 XSD 顺序附加范围、偏置、特征及特性组；材料与状态由主构建器继续写。"""
    if options is None:
        return {}
    object_fields(options, OPTION_FIELDS)
    if "symbolLibrary" in options:
        prefix = {"iso": "IGTOL", "asme": "GTOL", "gb": "GGTOL"}[enum(options["symbolLibrary"], ("iso", "asme", "gb"))]
        symbol = root.find("ToleranceSymbol")
        if symbol.text:
            symbol.text = prefix + "-" + symbol.text.split("-", 1)[1]
    _range_options(limits, options, tolerance, diameter)
    if "profileZone" in options:
        _profile_options(root, options["profileZone"], characteristic, tolerance)
    feature_keys = {"projectedZone", "associatedFeature", "derivedFeature", "filters"}
    if feature_keys & set(options):
        feature = ET.SubElement(root, "FeatureInfo")
        if "filters" in options:
            filters = options["filters"]
            if not isinstance(filters, list) or not 1 <= len(filters) <= 8:
                raise ValueError("滤波信息必须为 1..8 项明确配置")
            parent = ET.SubElement(feature, "Filters")
            for value in filters:
                _filter_xml(parent, value)
        if "associatedFeature" in options:
            ET.SubElement(feature, "AssociatedFeatureInfo").text = enum(options["associatedFeature"], ASSOCIATED_FEATURES)
        if "projectedZone" in options:
            projection = object_fields(options["projectedZone"], {"projection", "range"}, {"projection"})
            if characteristic not in {"position", "parallelism", "perpendicularity", "angularity"} or not diameter:
                raise ValueError("投影公差带当前要求圆柱位置度或轴线方向公差")
            ET.SubElement(feature, "ProjectedToleranceZone").text = "true"
            ET.SubElement(feature, "Projection").text = decimal_text(projection["projection"], positive=True)
            if "range" in projection:
                ET.SubElement(feature, "ProjectionRange").text = decimal_text(projection["range"], positive=True)
        if "derivedFeature" in options:
            append_flag(feature, "DerivedFeatureForFeatureOfSize", options["derivedFeature"])
        if not len(feature):
            root.remove(feature)
    if "associatedCharacteristic" in options:
        ET.SubElement(root, "AssociatedCharacteristic").text = enum(options["associatedCharacteristic"], ("C", "CE", "CI", "G", "GE", "GI", "X", "N"))
    if "parametricCharacteristic" in options:
        ET.SubElement(root, "ParametricCharacteristic").text = enum(options["parametricCharacteristic"], ("P", "V", "T", "Q"))
    if "reciprocity" in options:
        boolean(options["reciprocity"])
        if options["reciprocity"] and material_condition not in {"M", "L"}:
            raise ValueError("互易要求必须与 M 或 L 材料条件一起指定")
    for key in ("freeState", "statistical"):
        if key in options:
            boolean(options[key])
    return options
