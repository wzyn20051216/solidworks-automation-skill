"""2026 原生符号写入/重开矩阵；仅验证 API 表达，不证明测试公差的设计合理性。"""
from pathlib import Path
import argparse
import shutil
import sys
import tempfile
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.sw_connect import get_com_member
from scripts.sw_gdt_annotation import _SYMBOLS, _FORM, build_frame_xml, insert_gtol
from scripts.sw_session import SolidWorksSession
from scripts.sw_rename_copy import _sha256


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("drawing", type=Path, help="已有测试图纸（须包含 A 基准和圆孔）")
    args = parser.parse_args()
    source = args.drawing.resolve(strict=True)
    original_hash = _sha256(source)
    root = Path(tempfile.mkdtemp(prefix="sw_gdt_symbol_matrix_"))
    cases = [(name, None) for name in _SYMBOLS] + [("position", condition) for condition in ("M", "L", "S")]
    with SolidWorksSession(version=2026, visible=True) as session:
        for index, (name, condition) in enumerate(cases):
            copy = root / f"{root.name}_{index}_{name}.slddrw"
            shutil.copyfile(source, copy)
            drawing = session.open(str(copy), read_only=False, silent=True)
            views = get_com_member(get_com_member(drawing, "GetCurrentSheet"), "GetViews")
            view = next(view for view in views if get_com_member(view, "GetVisibleComponents"))
            component = get_com_member(view, "GetVisibleComponents")[0]
            edges = get_com_member(view, "GetVisibleEntities2", component, 1)
            edge = next(edge for edge in edges if get_com_member(get_com_member(edge, "GetCurve"), "IsCircle"))
            datums = [] if name in _FORM else ["A"]
            diameter = name in ("position", "straightness")
            expected = build_frame_xml(name, "0.2", diameter, datums, material_condition=condition)
            symbol = insert_gtol(drawing, view, edge, session.sw, characteristic=name,
                                 tolerance="0.2", diameter=diameter, datums=datums,
                                 material_condition=condition, position=(.12, .1))
            assert get_com_member(symbol, "GetFrameCount") == 1
            assert session.save(drawing, str(copy))
            session.close(model=drawing)
            drawing = session.open(str(copy), read_only=True, silent=True)
            found = []
            for view in get_com_member(get_com_member(drawing, "GetCurrentSheet"), "GetViews"):
                for symbol in get_com_member(view, "GetGTols") or ():
                    if get_com_member(symbol, "GetFrameCount") == 1:
                        xml = get_com_member(get_com_member(symbol, "GetFrame", 1), "GetSymbolXml")
                        if xml and ET.tostring(ET.fromstring(xml)) == ET.tostring(ET.fromstring(expected)):
                            found.append(symbol)
            assert len(found) == 1, (name, condition, len(found))
            ann = get_com_member(found[0], "GetAnnotation")
            attached = get_com_member(ann, "GetAttachedEntities3")
            assert get_com_member(ann, "GetAttachedEntityCount3") == 1 and len(attached) == 1 and attached[0] is not None
            session.close(model=drawing)
            print("PASS", name, condition, flush=True)
    assert _sha256(source) == original_hash
    print("matrix output", root, flush=True)


if __name__ == "__main__":
    main()
