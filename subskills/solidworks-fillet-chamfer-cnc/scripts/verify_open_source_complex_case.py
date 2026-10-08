"""开源复杂 CNC 支架的来源锁定与 SolidWorks 往返回归。"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import urllib.request
from pathlib import Path
from typing import Any
import re
from urllib.parse import unquote


SCRIPT_DIR = Path(__file__).resolve().parent
SUBSKILL_ROOT = SCRIPT_DIR.parent
SKILL_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(SKILL_ROOT / "scripts"))

from sw_connect import get_com_member, mm  # noqa: E402
from sw_export import export_to_step  # noqa: E402
from sw_review import run_review  # noqa: E402
from sw_session import SolidWorksSession  # noqa: E402
from http_boundary import validate_https_url, read_https_response  # noqa: E402


DEFAULT_CASE = SUBSKILL_ROOT / "examples" / "open_source_corner_bracket_case.json"
ALLOWED_DOWNLOAD_HOSTS = frozenset({"raw.githubusercontent.com"})
MAX_SOURCE_BYTES = 64 * 1024 * 1024
SW_SOLID_BODY = 0
SW_DISPLAY_ORIGINS = 6
SW_DISPLAY_REFERENCE_TRIAD = 205
SW_CHAMFER_DISTANCE_DISTANCE = 2
SW_CHAMFER_TANGENT_PROPAGATION = 4


def _validate_download_url(url: str) -> None:
    """@brief 下载源仅允许 https 且主机在白名单内，阻断案例清单被篡改后的任意源请求。"""
    validate_https_url(url, "raw.githubusercontent.com")


def load_case(path: Path) -> dict[str, Any]:
    """@brief 读取并校验固定来源案例清单。"""
    payload = json.loads(path.read_text(encoding="utf-8"))
    return _validate_case_payload(payload)


def _validate_case_payload(payload):
    """@brief 固定提交必须位于 URL 的 revision 段，查询字符串不能充当提交锁定。"""
    required = ("download_url", "sha256", "commit", "license", "attribution")
    missing = [name for name in required if not payload.get(name)]
    if missing:
        raise ValueError(f"案例清单缺少字段: {missing}")
    digest = str(payload["sha256"]).lower()
    if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
        raise ValueError("案例 sha256 必须为 64 位十六进制")
    _validate_download_url(str(payload["download_url"]))
    parts = validate_https_url(str(payload["download_url"]), "raw.githubusercontent.com")
    segments = unquote(parts.path).split("/")
    commit = str(payload["commit"])
    if not re.fullmatch(r"[0-9a-fA-F]{40}", commit) or len(segments) < 5 or segments[3].lower() != commit.lower():
        raise ValueError("案例下载 URL 的 revision 段必须是声明的完整 commit SHA")
    if any(segment in {"", ".", ".."} or "\\" in segment for segment in segments[1:]):
        raise ValueError("案例路径包含不允许的分段")
    if payload.get("source_path") and "/".join(segments[4:]) != payload["source_path"]:
        raise ValueError("案例下载路径与 source_path 声明不一致")
    return payload


def fetch_pinned_source(case: dict[str, Any], destination: Path) -> dict[str, Any]:
    """@brief 下载固定提交版本并在落盘后验证 SHA-256。"""
    _validate_case_payload(case)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        with destination.open("rb") as stream:
            content = stream.read(MAX_SOURCE_BYTES + 1)
        if len(content) > MAX_SOURCE_BYTES:
            raise ValueError("缓存案例超过读取上限")
        source = "cache"
    else:
        request = urllib.request.Request(
            str(case["download_url"]),
            headers={"User-Agent": "CAD-Studio-open-source-regression/1.0"},
        )
        content = read_https_response(request, allowed_host="raw.githubusercontent.com", max_bytes=MAX_SOURCE_BYTES)
        source = "network"
    digest = hashlib.sha256(content).hexdigest()
    expected = str(case["sha256"]).lower()
    if digest != expected:
        raise RuntimeError(f"开源案例哈希不匹配: expected={expected}, actual={digest}")
    if source == "network":
        # 核对后才落盘，且不能覆盖并发出现的已有文件。
        with destination.open("xb") as stream:
            stream.write(content)
    return {"path": str(destination.resolve()), "bytes": len(content), "sha256": digest, "source": source}


def topology_counts(model) -> dict[str, int]:
    """@brief 从 SolidWorks 实体回读面、边和唯一顶点数量。"""
    bodies = tuple(get_com_member(model, "GetBodies2", SW_SOLID_BODY, False) or ())
    faces = []
    edges = []
    vertices: set[tuple[float, float, float]] = set()
    for body in bodies:
        faces.extend(tuple(get_com_member(body, "GetFaces") or ()))
        body_edges = tuple(get_com_member(body, "GetEdges") or ())
        edges.extend(body_edges)
        for edge in body_edges:
            for member in ("GetStartVertex", "GetEndVertex"):
                vertex = get_com_member(edge, member)
                if vertex is None:
                    continue
                point = tuple(round(float(value), 9) for value in get_com_member(vertex, "GetPoint"))
                vertices.add(point)
    return {
        "solids": len(bodies),
        "faces": len(faces),
        "edges": len(edges),
        "vertices": len(vertices),
    }


def topology_is_complex(counts: dict[str, int]) -> bool:
    """@brief 拒绝被错误导入为空件或过度简化件的案例。"""
    return (
        counts.get("solids") == 1
        and counts.get("faces", 0) >= 35
        and counts.get("edges", 0) >= 85
        and counts.get("vertices", 0) >= 40
    )


def assert_expected_source_topology(case: dict[str, Any], counts: dict[str, int]) -> None:
    """@brief 固定案例必须匹配清单中的精确源拓扑。"""
    expected = case.get("expected_source_topology") or {}
    mismatches = {
        name: {"expected": int(value), "actual": int(counts.get(name, -1))}
        for name, value in expected.items()
        if int(counts.get(name, -1)) != int(value)
    }
    if mismatches:
        raise RuntimeError(f"固定开源案例源拓扑漂移: {mismatches}")


def edge_signature(edge) -> dict[str, Any] | None:
    """@brief 返回复杂件直边的端点、长度和可锁定签名。"""
    curve = get_com_member(edge, "GetCurve")
    if curve is None or not bool(get_com_member(curve, "IsLine")):
        return None
    start = get_com_member(edge, "GetStartVertex")
    end = get_com_member(edge, "GetEndVertex")
    if start is None or end is None:
        return None
    raw_points = [
        tuple(float(value) for value in get_com_member(vertex, "GetPoint"))
        for vertex in (start, end)
    ]
    length_mm = sum(
        (raw_points[1][index] - raw_points[0][index]) ** 2 for index in range(3)
    ) ** 0.5 * 1000.0
    points_mm = sorted(
        [round(value * 1000.0, 6) for value in point]
        for point in raw_points
    )
    return {
        "curve": "line",
        "length_mm": round(length_mm, 6),
        "endpoints_mm": points_mm,
    }


def apply_complex_width_width_chamfer(model, case: dict[str, Any]) -> dict[str, Any]:
    """@brief 按清单中的唯一边签名创建并验证距离-距离倒角。"""
    bodies = tuple(get_com_member(model, "GetBodies2", SW_SOLID_BODY, False) or ())
    if len(bodies) != 1:
        raise RuntimeError("复杂倒角回归要求唯一实体")
    operation = case.get("advanced_operation") or {}
    expected_signature = operation.get("edge_signature")
    widths = operation.get("widths_mm") or []
    if operation.get("kind") != "width_width_chamfer" or len(widths) != 2 or not expected_signature:
        raise ValueError("复杂案例清单缺少完整 width_width_chamfer 操作定义")
    width1, width2 = (float(value) for value in widths)
    if width1 <= 0.0 or width2 <= 0.0:
        raise ValueError("复杂案例倒角宽度必须为正数")
    matches = []
    for edge in tuple(get_com_member(bodies[0], "GetEdges") or ()):
        signature = edge_signature(edge)
        if signature == expected_signature:
            matches.append((edge, signature))
    if len(matches) != 1:
        raise RuntimeError(f"复杂案例倒角边签名匹配不唯一: expected=1, actual={len(matches)}")
    edge, signature = matches[0]
    model.ClearSelection2(True)
    if not edge.Select2(False, 0):
        raise RuntimeError("复杂案例倒角边选择失败")
    feature = model.FeatureManager.InsertFeatureChamfer(
        SW_CHAMFER_TANGENT_PROPAGATION,
        SW_CHAMFER_DISTANCE_DISTANCE,
        mm(width1),
        0.0,
        mm(width2),
        0.0,
        0.0,
        0.0,
    )
    if feature is None:
        raise RuntimeError("固定复杂案例宽度-宽度倒角创建失败")
    feature.Name = "OpenSource_WidthWidth_C0p2_C0p4"
    if not model.ForceRebuild3(False):
        raise RuntimeError("开源复杂件宽度-宽度倒角重建失败")
    data = get_com_member(feature, "GetDefinition")
    feature_type = int(get_com_member(data, "Type")) if data is not None else -1
    distances = (
        [round(float(data.GetEdgeChamferDistance(side)) * 1000.0, 6) for side in (0, 1)]
        if data is not None
        else []
    )
    if feature_type != SW_CHAMFER_DISTANCE_DISTANCE or sorted(distances) != sorted([width1, width2]):
        raise RuntimeError(
            f"复杂件倒角 FeatureData 不匹配: type={feature_type}, distances={distances}"
        )
    return {
        "status": "verified",
        "feature_name": str(feature.Name),
        "feature_type": feature_type,
        "distances_mm": distances,
        "selected_edge": signature,
    }


def hide_review_helpers(model) -> None:
    """@brief 隐藏原点和参考三轴，保持复杂案例预览干净。"""
    for preference in (SW_DISPLAY_ORIGINS, SW_DISPLAY_REFERENCE_TRIAD):
        try:
            model.SetUserPreferenceToggle(preference, False)
        except Exception:
            continue
    model.ClearSelection2(True)


def run_solidworks_case(case: dict[str, Any], source: Path, output_dir: Path, version: int) -> dict[str, Any]:
    """@brief 执行 STEP 导入、另存、导出、审查和重开拓扑闭环。"""
    output_dir.mkdir(parents=True, exist_ok=True)
    part_path = output_dir / "OpenSource_2020_Corner_Bracket.SLDPRT"
    step_path = output_dir / "OpenSource_2020_Corner_Bracket_roundtrip.step"
    model = None
    reopened = None
    session = SolidWorksSession(version=version, visible=False)
    try:
        model = session.open(source, silent=True)
        imported = topology_counts(model)
        if not topology_is_complex(imported):
            raise RuntimeError(f"导入拓扑未达到复杂案例门槛: {imported}")
        assert_expected_source_topology(case, imported)
        advanced_feature = apply_complex_width_width_chamfer(model, case)
        processed = topology_counts(model)
        if not session.save(model, part_path):
            raise RuntimeError(f"原生另存失败: {part_path}")
        if not export_to_step(model, step_path):
            raise RuntimeError(f"STEP 往返导出失败: {step_path}")
        hide_review_helpers(model)
        review, review_path = run_review(
            model,
            output_dir,
            basename="OpenSource_2020_Corner_Bracket",
            expected_outputs=[str(part_path), str(step_path)],
        )
        if review["evaluation"]["status"] != "pass":
            raise RuntimeError(f"复杂件多视角审查未通过: {review['evaluation']}")
        session.close(model=model)
        model = None
        reopened = session.open(part_path, read_only=True, silent=True)
        reopened_counts = topology_counts(reopened)
        rebuild = bool(reopened.ForceRebuild3(False))
        if not rebuild or reopened_counts != processed:
            raise RuntimeError(
                f"重开拓扑或重建不一致: processed={processed}, reopened={reopened_counts}, rebuild={rebuild}"
            )
        reopened_feature = reopened.FeatureByName(advanced_feature["feature_name"])
        if reopened_feature is None or str(get_com_member(reopened_feature, "GetTypeName2")) != "Chamfer":
            raise RuntimeError("重开后复杂件宽度-宽度倒角未持久化")
        return {
            "status": "verified",
            "solidworks_revision": str(session.sw.RevisionNumber()),
            "source": case,
            "topology": {"imported": imported, "processed": processed, "reopened": reopened_counts},
            "advanced_feature": advanced_feature,
            "checks": {
                "single_solid": imported["solids"] == 1,
                "complexity_threshold": topology_is_complex(imported),
                "source_topology_exact": True,
                "width_width_chamfer": advanced_feature["status"] == "verified",
                "native_save": part_path.is_file() and part_path.stat().st_size > 0,
                "step_roundtrip": step_path.is_file() and step_path.stat().st_size > 0,
                "rebuild_after_reopen": rebuild,
                "topology_preserved_after_reopen": reopened_counts == processed,
                "review_pass": review["evaluation"]["status"] == "pass",
            },
            "artifacts": {
                "part": str(part_path.resolve()),
                "step": str(step_path.resolve()),
                "review": str(Path(review_path).resolve()),
            },
        }
    finally:
        if reopened is not None:
            session.close(model=reopened)
        elif model is not None:
            session.close(model=model)
        session.quit_owned_instance()


def parse_args() -> argparse.Namespace:
    """@brief 解析命令行参数。"""
    parser = argparse.ArgumentParser(description="验证固定开源复杂支架的 SolidWorks 往返质量")
    parser.add_argument("--case", type=Path, default=DEFAULT_CASE)
    parser.add_argument("--output-dir", type=Path, default=SKILL_ROOT / "output" / "opensource_corner_bracket")
    parser.add_argument("--version", type=int, default=2026)
    parser.add_argument("--download-only", action="store_true")
    return parser.parse_args()


def main() -> int:
    """@brief 固定来源、执行回归并输出机器可读报告。"""
    args = parse_args()
    output_dir = args.output_dir.resolve()
    case = load_case(args.case.resolve())
    source_evidence = fetch_pinned_source(case, output_dir / "source" / "2020_corner_bracket-Corner.step")
    report: dict[str, Any] = {"schema_version": 1, "source_evidence": source_evidence}
    if args.download_only:
        report["status"] = "source_verified"
    else:
        report.update(run_solidworks_case(case, Path(source_evidence["path"]), output_dir, args.version))
    report_path = output_dir / "open_source_complex_case_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status": report["status"], "report": str(report_path)}, ensure_ascii=False, indent=2))
    return 0 if report["status"] in {"source_verified", "verified"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
