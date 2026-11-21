"""常规直角支架的原生筋回归；需独占空白SW会话，结果仍需目视复核。"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.sw_connect import (connect_solidworks, get_com_member as g,
                                get_sw_version, new_document, save_document,
                                open_document)
from scripts.sw_part import (sketch, sketch_corner_rectangle, sketch_line,
                             extrude_midplane, rib, _get_plane_name_candidates,
                             _select_first_candidate)
from scripts.sw_review import collect_model_summary, save_preview
from scripts.sw_sketch_quality import fully_define_sketch


def ribs(model):
    """枚举模型的原生筋特征。

    参数:
        model: 待读取的零件文档。
    返回:
        按设计树顺序排列的 Rib 特征列表。
    """
    result = []
    feature = g(model, "FirstFeature")
    while feature is not None:
        if g(feature, "GetTypeName2") == "Rib":
            result.append(feature)
        feature = g(feature, "GetNextFeature")
    return result


def volume(model):
    """读取单实体零件的体积。

    参数:
        model: 必须恰有一个实体的零件文档。
    返回:
        体积，单位为立方毫米。
    """
    bodies = g(model, "GetBodies2", 0, False)
    assert len(bodies) == 1
    return float(g(bodies[0], "GetMassProperties", 1.)[3]) * 1e9


def fixture(sw):
    """新建用于隔离验证筋封装的直角支架。

    参数:
        sw: 已连接的可见 SolidWorks 实例。
    返回:
        包含基座和立板的零件文档。
    """
    model = new_document(sw, "part")
    for name, rectangle in [("基座", (0., 0., .080, .010)),
                            ("立板", (0., .010, .010, .060))]:
        with sketch(model, "Front Plane") as ref:
            sketch_corner_rectangle(model, *rectangle)
            fully_define_sketch(model)
        feature = extrude_midplane(model, ref, .040)
        assert feature is not None
        feature.Name = name
    assert math.isclose(volume(model), 52000., abs_tol=1e-4)
    return model


def offset_plane(model, distance, name):
    """创建相对前视基准面的偏置平面。

    参数:
        model: 目标零件文档。
        distance: 偏置距离，单位为米。
        name: 新基准面的名称。
    返回:
        新基准面的名称。
    """
    model.ClearSelection2(True)
    assert _select_first_candidate(model.Extension,
        _get_plane_name_candidates("Front Plane"), "PLANE")
    assert model.FeatureManager.InsertRefPlane(8, distance, 0, 0., 0, 0.) is not None
    feature = g(model, "FirstFeature")
    last = None
    while feature is not None:
        if g(feature, "GetTypeName2") == "RefPlane":
            last = feature
        feature = g(feature, "GetNextFeature")
    assert last is not None
    last.Name = name
    return name


def add_rib(model, *, plane="Front Plane", both=True, thickness=.006):
    """通过真实草图选择路径创建测试筋。

    参数:
        model: 目标零件文档。
        plane: 草图基准面的名称。
        both: 是否采用双侧厚度。
        thickness: 筋厚度，单位为米。
    返回:
        封装返回的新增特征；创建失败时为 None。
    """
    with sketch(model, plane) as ref:
        manager = model.SketchManager
        old = manager.AddToDB
        manager.AddToDB = True
        try:
            assert sketch_line(model, .010, .040, .050, .010) is not None
        finally:
            manager.AddToDB = old
        fully_define_sketch(model)
    return rib(model, ref, thickness, direction=both)


def inspect_rib(feature, both, thickness, plane_z=0.):
    """回读筋定义和真实平面侧面并核对厚度。

    参数:
        feature: 待检查的原生筋特征。
        both: 预期的双侧厚度标志。
        thickness: 预期厚度，单位为米。
        plane_z: 草图平面的位置，单位为米。
    返回:
        包含特征名称、厚度与侧面位置的证据字典。
    """
    definition = g(feature, "GetDefinition")
    assert bool(g(definition, "IsTwoSided")) == both
    assert math.isclose(float(g(definition, "Thickness")), thickness, abs_tol=1e-9)
    planes = set()
    for face in g(feature, "GetFaces"):
        surface = g(face, "GetSurface")
        if g(surface, "IsPlane"):
            p = g(surface, "PlaneParams")
            if abs(abs(p[2]) - 1.) < 1e-8:
                planes.add(round(p[5] * 1000., 7))
    assert len(planes) == 2, planes
    values = sorted(planes)
    assert math.isclose(values[1] - values[0], thickness * 1000., abs_tol=1e-6)
    if both:
        assert math.isclose(sum(values), plane_z * 2000., abs_tol=1e-6)
    else:
        assert any(abs(value - plane_z * 1000.) < 1e-6 for value in values)
    return {"name": str(feature.Name), "both_sides": both,
            "thickness_mm": thickness * 1000., "side_planes_z_mm": values}


def healthy(model):
    """重建并核对模型无错误、警告或未知特征状态。

    参数:
        model: 待检查的零件文档。
    返回:
        无；不符合条件时触发断言。
    """
    assert model.ForceRebuild3(False)
    health = collect_model_summary(model)
    assert not health["faulty_features"] and not health["warning_features"]
    assert not health["unknown_feature_health"] and not health.get("feature_error")


def run(sw, output):
    """执行单双侧、第二筋、持久化与失败路径原生回归。

    参数:
        sw: 本轮独占且没有打开文档的可见 SolidWorks 实例。
        output: 尚不存在的输出目录。
    返回:
        原生检查报告；预览仍需人工目视复核。
    """
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    assert g(sw, "GetFirstDocument") is None, "需空白会话，不关闭用户文档"
    assert bool(g(sw, "Visible"))
    timer = time.perf_counter()
    report = {"status": "running", "environment": get_sw_version(sw), "cases": [],
              "source_sha256": hashlib.sha256((ROOT / "scripts/sw_part.py").read_bytes()).hexdigest(),
              "visual_review_required": True}
    try:
        for both, label in [(True, "two-sided"), (False, "one-sided")]:
            print("验证 " + label, flush=True)
            model = fixture(sw)
            before = volume(model)
            feature = add_rib(model, both=both)
            assert feature is not None and len(ribs(model)) == 1
            row = inspect_rib(feature, both, .006)
            assert math.isclose(volume(model) - before, 3600., abs_tol=1e-4)
            healthy(model)
            row["rib_volume_mm3"] = volume(model) - before
            path = output / (label + ".SLDPRT")
            assert save_document(model, str(path)) and not g(model, "GetSaveFlag")
            save_preview(model, str(output / (label + ".bmp")), "isometric")
            sw.CloseDoc(g(model, "GetTitle"))
            model = open_document(sw, str(path), silent=True, raise_on_error=True)
            healthy(model)
            assert len(ribs(model)) == 1
            assert inspect_rib(ribs(model)[0], both, .006) == {k: row[k] for k in row if k != "rib_volume_mm3"}
            if both:
                old_name = str(ribs(model)[0].Name)
                plane = offset_plane(model, .012, "第二筋平面")
                before_second = volume(model)
                second = add_rib(model, plane=plane, thickness=.004)
                assert second is not None and str(second.Name) != old_name
                assert len(ribs(model)) == 2 and model.FeatureByName(old_name) is not None
                row["second_rib"] = inspect_rib(second, True, .004, plane_z=.012)
                assert math.isclose(volume(model) - before_second, 2400., abs_tol=1e-4)
                healthy(model)
                row["second_rib_returned_new_feature"] = True
                assert save_document(model, str(path))
                save_preview(model, str(output / "two-ribs.bmp"), "isometric")
                sw.CloseDoc(g(model, "GetTitle"))
                model = open_document(sw, str(path), silent=True, raise_on_error=True)
                healthy(model)
                assert len(ribs(model)) == 2
                assert math.isclose(volume(model), 58000., abs_tol=1e-4)
                second = model.FeatureByName(row["second_rib"]["name"])
                assert inspect_rib(second, True, .004, plane_z=.012) == row["second_rib"]
                row["second_rib_persisted_after_reopen"] = True
            sw.CloseDoc(g(model, "GetTitle"))
            report["cases"].append({"case": label, "status": "pass", **row})

        print("验证不相交筋的失败返回", flush=True)
        model = fixture(sw)
        assert add_rib(model) is not None
        before = volume(model)
        old_names = [str(f.Name) for f in ribs(model)]
        plane = offset_plane(model, .100, "不相交筋平面")
        failed = add_rib(model, plane=plane)
        assert failed is None, "不相交筋不得返回成功特征"
        assert [str(f.Name) for f in ribs(model)] == old_names
        assert math.isclose(volume(model), before, abs_tol=1e-4)
        assert save_document(model, str(output / "expected-failure.SLDPRT"))
        sw.CloseDoc(g(model, "GetTitle"))
        report["cases"].append({"case": "non-intersecting", "status": "pass",
                                "returned_none": True, "old_rib_not_returned": True,
                                "solid_volume_unchanged": True})
        report["status"] = "native_checks_passed"
    finally:
        report["elapsed_seconds"] = time.perf_counter() - timer
        report["remaining_document_count"] = int(g(sw, "GetDocumentCount"))
        (output / "native-report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False), flush=True)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    from scripts.sw_process import solidworks_processes
    assert not args.output.exists(), "输出目录已存在，不覆盖既有证据"
    assert solidworks_processes() == {}, "已有CAD进程；请在空白隔离会话执行"
    app, _, _ = connect_solidworks(version=args.version, wait_seconds=60,
                                    visible=True, return_metadata=True)
    run(app, args.output)
