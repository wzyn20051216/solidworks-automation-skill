"""真实 OCP 参数化 Loft 后端回归。"""
from __future__ import annotations

from pathlib import Path

import pytest

from scripts.advanced_geometry_ocp import _suppress_native_stdout, execute_ocp_loft, validate_ocp_loft_request


def _request(outputs: list[str] | None = None) -> dict:
    """@brief 返回圆/椭圆过渡的封闭 Loft 黄金样件。"""
    return {
        "schemaVersion": "1.0",
        "modelId": "adapter_loft",
        "units": "mm",
        "operation": "loft",
        "solid": True,
        "ruled": True,
        "toleranceMm": 0.01,
        "sections": [
            {"id": "base", "type": "circle", "z": 0, "center": [0, 0], "radius": 20},
            {"id": "middle", "type": "ellipse", "z": 30, "center": [2, 0], "majorRadius": 16, "minorRadius": 12, "rotationDeg": 15},
            {"id": "top", "type": "circle", "z": 60, "center": [0, 0], "radius": 10},
        ],
        "outputs": outputs or ["step", "brep", "stl"],
    }


def test_validate_ocp_loft_request_accepts_closed_parametric_sections() -> None:
    """@brief 圆和椭圆的严格白名单请求应通过。"""
    assert validate_ocp_loft_request(_request())["modelId"] == "adapter_loft"


def test_native_stdout_guard_allows_gui_process_without_console(monkeypatch) -> None:
    """@brief Windows GUI 无控制台时，原生日志抑制不得阻断几何执行。"""
    def no_console(_fd: int) -> int:
        raise OSError("stdout is not attached")

    monkeypatch.setattr("scripts.advanced_geometry_ocp.os.dup", no_console)
    reached = False
    with _suppress_native_stdout():
        reached = True
    assert reached is True


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda request: request.update({"command": "cmd.exe"}), "未允许字段"),
        (lambda request: request.update({"modelId": "bad/../name"}), "modelId"),
        (lambda request: request["sections"][1].update({"z": 0}), "严格递增"),
        (lambda request: request["sections"][0].update({"radius": 0}), "radius"),
        (lambda request: request.update({"outputs": ["step", "exe"]}), "outputs"),
        (lambda request: request.update({"outputs": ["stl"]}), "至少包含 step 或 brep"),
        (lambda request: request.update({"ruled": False}), "ruled=true"),
        (lambda request: request["sections"].__setitem__(1, {"id": "middle", "type": "polygon", "z": 30, "points": [[-5, -5], [5, -5], [5, 5], [-5, 5]]}), "不能与多边形"),
    ],
)
def test_validate_ocp_loft_request_rejects_unsafe_or_degenerate_input(change, message: str) -> None:
    """@brief 命令注入、路径字符、退化截面和非白名单格式必须拒绝。"""
    request = _request()
    change(request)
    with pytest.raises(ValueError, match=message):
        validate_ocp_loft_request(request)


def test_polygon_section_rejects_zero_area() -> None:
    """@brief 共线多边形不能进入 OCP 构造。"""
    request = _request(["brep"])
    request["sections"] = [
        {"id": "bottom", "type": "polygon", "z": 0, "points": [[0, 0], [1, 0], [2, 0]]},
        {"id": "top", "type": "polygon", "z": 20, "points": [[0, 0], [1, 0], [2, 0]]},
    ]
    with pytest.raises(ValueError, match="退化多边形"):
        validate_ocp_loft_request(request)


def test_polygon_section_rejects_self_intersection() -> None:
    """@brief 非零代数面积的自交多边形也必须拒绝。"""
    request = _request(["brep"])
    request["sections"] = [
        {"id": "bottom", "type": "polygon", "z": 0, "points": [[0, 0], [4, 4], [0, 3], [4, 0]]},
        {"id": "top", "type": "polygon", "z": 20, "points": [[0, 0], [4, 4], [0, 3], [4, 0]]},
    ]
    with pytest.raises(ValueError, match="自交"):
        validate_ocp_loft_request(request)


def test_execute_ocp_loft_writes_and_reopens_real_brep_artifacts(tmp_path: Path) -> None:
    """@brief STEP/BREP 必须重开为有效实体，STL 必须是本轮非空产物。"""
    pytest.importorskip("OCP")
    report = execute_ocp_loft(_request(), tmp_path)

    assert report["status"] == "review_required"
    assert report["geometryProduced"] is True
    assert report["producedThisRun"] is True
    assert report["error_code"] is None
    original = report["geometryEvidence"]["original"]
    assert original["valid"] is True
    assert original["topology"]["solids"] >= 1
    assert original["volumeMm3"] > 0
    assert original["surfaceAreaMm2"] > 0
    assert original["sectionEnvelopeCheck"]["pass"] is True
    for fmt in ("step", "brep"):
        evidence = report["geometryEvidence"]["reopened"][fmt]
        assert evidence["valid"] is True
        assert evidence["topology"]["solids"] >= 1
        assert evidence["volumeMm3"] > 0
        assert evidence["surfaceAreaMm2"] > 0
        assert evidence["comparisonToOriginal"]["withinTolerance"] is True
        assert evidence["comparisonToOriginal"]["volumeRelativeDelta"] <= 1e-6
        assert evidence["comparisonToOriginal"]["maximumBoundDeltaMm"] <= 1e-5
    artifacts = {item["format"]: item for item in report["artifacts"]}
    assert set(artifacts) == {"step", "brep", "stl"}
    for artifact in artifacts.values():
        path = Path(artifact["path"])
        assert path.is_file() and path.stat().st_size > 0
        assert artifact["sha256"]
        assert artifact["producedThisRun"] is True
    assert artifacts["step"]["reopened"] is True
    assert artifacts["brep"]["reopened"] is True
    assert artifacts["stl"]["reopened"] is False


def test_execute_ocp_loft_versions_entire_artifact_set(tmp_path: Path) -> None:
    """@brief 任一同名产物存在时，整组产物必须使用统一新版本名。"""
    pytest.importorskip("OCP")
    first = execute_ocp_loft(_request(["step", "brep"]), tmp_path)
    second = execute_ocp_loft(_request(["step", "brep"]), tmp_path)

    assert first["status"] == "review_required"
    assert second["status"] == "review_required"
    first_names = {Path(item["path"]).name for item in first["artifacts"]}
    second_names = {Path(item["path"]).name for item in second["artifacts"]}
    assert first_names == {"adapter_loft.step", "adapter_loft.brep"}
    assert second_names == {"adapter_loft_v2.step", "adapter_loft_v2.brep"}


def test_execute_polygon_loft_with_matching_topology(tmp_path: Path) -> None:
    """@brief 同顶点数、同绕向的多边形截面应生成并重开真实实体。"""
    pytest.importorskip("OCP")
    request = _request(["brep"])
    request["sections"] = [
        {"id": "bottom", "type": "polygon", "z": 0, "points": [[-12, -8], [12, -8], [12, 8], [-12, 8]]},
        {"id": "middle", "type": "polygon", "z": 25, "center": [2, 0], "points": [[-10, -7], [10, -7], [10, 7], [-10, 7]]},
        {"id": "top", "type": "polygon", "z": 50, "points": [[-7, -5], [7, -5], [7, 5], [-7, 5]]},
    ]
    report = execute_ocp_loft(request, tmp_path)
    assert report["status"] == "review_required"
    assert report["geometryEvidence"]["reopened"]["brep"]["topology"]["solids"] >= 1


def test_invalid_request_returns_blocked_without_artifact(tmp_path: Path) -> None:
    """@brief 输入校验失败时不得创建输出目录或几何产物。"""
    request = _request()
    request["sections"][0]["radius"] = -1
    output = tmp_path / "output"
    report = execute_ocp_loft(request, output)
    assert report["status"] == "blocked"
    assert report["stage"] == "validate"
    assert report["geometryProduced"] is False
    assert report["artifacts"] == []
    assert not output.exists()
