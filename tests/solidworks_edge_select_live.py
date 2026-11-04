"""SolidWorks 2026 语义选边真机回归：直线、整圆、偏置短圆弧及保存重开。"""
import json
import math
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.sw_connect import get_com_member
from scripts.sw_edge_select import describe_edge, iter_model_edges, select_edges
from scripts.sw_part import sketch, sketch_rectangle, sketch_circle, sketch_arc, sketch_line, extrude_boss
from scripts.sw_review import run_review
from scripts.sw_session import SolidWorksSession
from scripts.sw_sketch_quality import fully_define_sketch
from apps.desktop.cad_workbench.artifact_ledger import sha256_file


def main():
    root = Path(tempfile.mkdtemp(prefix="sw_edge_selection_"))
    print("OUTPUT", root, flush=True)
    records = []
    fallback_records = []
    with SolidWorksSession(version=2026, visible=True) as session:
        before = {get_com_member(doc, "GetTitle") for doc in session._documents()}
        version = str(get_com_member(session.sw, "RevisionNumber"))
        assert version.startswith("34."), version
        for name in ("block", "cylinder", "short_arc"):
            model = session.new_part()
            with sketch(model, "Front Plane") as ref:
                if name == "block":
                    sketch_rectangle(model, .03, .02, .1, .06)
                elif name == "cylinder":
                    sketch_circle(model, .03, .02, .01)
                else:
                    cx, cy, outer, inner, angle = .07, .03, .04, .03, math.pi/36
                    outer_end = (cx+outer*math.cos(angle), cy+outer*math.sin(angle))
                    inner_end = (cx+inner*math.cos(angle), cy+inner*math.sin(angle))
                    model.SketchManager.AddToDB = True
                    try:
                        assert sketch_arc(model, cx, cy, cx+outer, cy, *outer_end)
                        assert sketch_line(model, *outer_end, *inner_end)
                        assert sketch_arc(model, cx, cy, *inner_end, cx+inner, cy, direction=-1)
                        assert sketch_line(model, cx+inner, cy, cx+outer, cy)
                    finally:
                        model.SketchManager.AddToDB = False
                assert fully_define_sketch(model)["status"] == "pass"
            assert extrude_boss(model, ref, .006)
            path = root / (name + ".sldprt")
            assert session.save(model, str(path))
            digest = sha256_file(path)
            for phase in ("built", "reopened"):
                if phase == "reopened":
                    session.close(model)
                    model = session.open(str(path), read_only=True, silent=True)
                descriptors, errors = iter_model_edges(model)
                cleaned = [{key: value for key, value in descriptor.items() if key != "edge"} for descriptor in descriptors]
                (root / f"{name}-{phase}.json").write_text(json.dumps({"edges": cleaned, "errors": errors}, ensure_ascii=False, indent=2), encoding="utf-8")
                assert not errors, errors
                assert all(item["length_mm"] and not item["errors"] for item in descriptors), cleaned
                # 用真实 IEdge 强制进入两条兼容路径，核验运行时成员 ID 和 COM 返回值。
                original = descriptors[0]["edge"]
                try:
                    original._oleobj_.GetTypeInfo()
                    type_info_available = True
                except Exception:
                    type_info_available = False
                for type_info_only in (False, True):
                    class OleProxy:
                        def GetIDsOfNames(self, *args):
                            if type_info_only:
                                raise AttributeError("force type-info lookup")
                            return original._oleobj_.GetIDsOfNames(*args)
                        def GetTypeInfo(self): return original._oleobj_.GetTypeInfo()
                        def Invoke(self, *args): return original._oleobj_.Invoke(*args)
                    class EdgeProxy:
                        _oleobj_ = OleProxy()
                        def GetCurve(self): raise AttributeError("force compatibility call")
                        def __getattr__(self, key): return getattr(original, key)
                    fallback = describe_edge(EdgeProxy())
                    if type_info_only and not type_info_available:
                        assert fallback["errors"] and fallback["length_mm"] is None
                        outcome = "expected_error_no_type_info"
                    else:
                        assert not fallback["errors"] and fallback["length_mm"] == descriptors[0]["length_mm"], (type_info_only, fallback["errors"])
                        outcome = "pass"
                    fallback_records.append({"model": name, "phase": phase, "typeInfoOnly": type_info_only, "status": outcome})
                if name == "block":
                    assert len(descriptors) == 12
                    specs = [({"min_length_mm": 99.99, "max_length_mm": 100.01}, 4),
                             ({"min_length_mm": 59.99, "max_length_mm": 60.01}, 4),
                             ({"axis": "z", "min_length_mm": 5.99, "max_length_mm": 6.01}, 4)]
                elif name == "cylinder":
                    circular = [item for item in descriptors if item["is_circle"]]
                    assert len(circular) == 2
                    assert all(abs(item["length_mm"]-20*math.pi) < .001 for item in circular)
                    specs = [({"circular": True, "diameter_mm": 20}, 2)]
                else:
                    circular = [item for item in descriptors if item["is_circle"]]
                    assert len(circular) == 4
                    for item in circular:
                        expected_length = math.pi/36 * item["diameter_mm"]/2
                        assert abs(item["length_mm"]-expected_length) < .001, item
                    specs = [({"circular": True, "diameter_mm": 80}, 2),
                             ({"circular": True, "diameter_mm": 60}, 2),
                             ({"min_length_mm": 3.48, "max_length_mm": 3.50}, 2)]
                for spec, count in specs:
                    selected = select_edges(model, spec)
                    assert selected["status"] == "ok" and selected["selected_count"] == count, selected
                    assert get_com_member(model.SelectionManager, "GetSelectedObjectCount2", -1) == count
                    records.append({"model": name, "phase": phase, "spec": spec, "selectedCount": count})
                assert select_edges(model, {"diameter_mm": 999})["status"] == "error"
            report, report_path = run_review(model, root / "preview", basename=name, expected_outputs=[path])
            assert report["evaluation"]["status"] == "pass", report_path
            session.close(model)
            assert sha256_file(path) == digest
            print("PASS", name, flush=True)
        assert {get_com_member(doc, "GetTitle") for doc in session._documents()} == before
    (root / "edge-selection-evidence.json").write_text(json.dumps({"status": "pass", "solidworksRevision": version,
        "sourceUnchanged": True, "userDocumentsPreserved": True, "selectionCases": records, "fallbackCases": fallback_records}, ensure_ascii=False, indent=2), encoding="utf-8")
    print("PASS", len(records), "selection cases", root, flush=True)


if __name__ == "__main__":
    main()
