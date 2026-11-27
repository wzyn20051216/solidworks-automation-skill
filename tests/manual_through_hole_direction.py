"""用前视基准面两侧的板验证 MCP 单侧通孔。仅操作本轮自建零件。"""
import argparse
import asyncio
from datetime import timedelta
import hashlib
import json
import math
import os
from pathlib import Path
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.sw_connect import get_com_member as get, get_sw_version
from scripts.sw_part import extrude_boss, sketch, sketch_rectangle
from scripts.sw_process import solidworks_processes
from scripts.sw_review import collect_model_summary, save_preview
from scripts.sw_session import SolidWorksSession
from scripts.sw_sketch_quality import fully_define_sketch


def _solid(model):
    body, = get(model, "GetBodies2", 0, False)
    return body


def _volume(model):
    return float(get(_solid(model), "GetMassProperties", 1.)[3]) * 1e9


def _hole_openings(model):
    # 同轴、半径 3 mm 且位于两端面的圆边用于确认实际孔口。
    planes = set()
    for edge in get(_solid(model), "GetEdges"):
        curve = get(edge, "GetCurve")
        if curve is None or not get(curve, "IsCircle"):
            continue
        x, y, z, _, _, nz, radius = get(curve, "CircleParams")
        if (abs(x) < 1e-7 and abs(y) < 1e-7 and abs(abs(nz) - 1.) < 1e-7
                and math.isclose(radius, .003, abs_tol=1e-8)):
            planes.add(round(z * 1000., 6))
    return sorted(planes)


def _close(session, model, identity):
    assert get(session.sw, "GetDocumentCount") == 1
    assert (get(model, "GetPathName") or get(model, "GetTitle")) == identity
    session.close(model)
    assert get(session.sw, "GetDocumentCount") == 0


def _check_success(model, expected_planes):
    assert _hole_openings(model) == expected_planes
    assert math.isclose(96000 - _volume(model), math.pi * 3 ** 2 * 20, abs_tol=1e-4)
    summary = collect_model_summary(model)
    assert not summary.get("feature_error")
    assert not summary["faulty_features"] and not summary["warning_features"]
    assert not summary["unknown_feature_health"]


async def _cases(session, version, output, baseline, report):
    pid = int(get(session.sw, "GetProcessID"))
    params = StdioServerParameters(
        command=sys.executable, args=[str(ROOT / "mcp-server/server.py")],
        cwd=str(ROOT), env={
            **os.environ, "SW_MCP_DISCOVERY": "full", "SW_MCP_APPROVAL": "client",
            "SW_ATTACH_EXISTING_DISPATCH": "1",
        },
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write, read_timeout_seconds=timedelta(seconds=90)) as client:
            await client.initialize()

            async def call(name, arguments):
                result = await client.call_tool(name, {"params": arguments})
                assert not result.isError, result
                return json.loads(next(c.text for c in result.content if c.type == "text"))

            connected = await call("solidworks_connect", {"version": version, "wait_seconds": 1})
            assert connected["status"] == "ok" and connected["process_id"] == pid
            cases = [("default", 1, None, True), ("default-opposite", -1, None, False)]
            if not baseline:
                cases += [("reverse", -1, True, True), ("reverse-wrong-side", 1, True, False)]

            for label, side, reverse, succeeds in cases:
                print("测试 " + label, flush=True)
                created = await call("solidworks_new_document", {"doc_type": "part"})
                assert created["status"] == "ok"
                model = get(session.sw, "ActiveDoc")
                title = created["document"]["title"]
                assert get(model, "GetTitle") == title and not get(model, "GetPathName")
                assert get(session.sw, "GetDocumentCount") == 1
                with sketch(model, "Front Plane") as ref:
                    assert sketch_rectangle(model, 0, 0, .080, .060) is not None
                    assert fully_define_sketch(model)["status"] == "pass"
                assert extrude_boss(model, ref, .020, direction=side < 0) is not None
                assert math.isclose(_volume(model), 96000., abs_tol=1e-4)
                assert get(model, "GetTitle") == title

                arguments = {"feature_kind": "through", "diameter_mm": 6, "feature_name": label}
                if reverse is not None:
                    arguments["reverse_direction"] = reverse
                result = await call("solidworks_create_hole_feature", arguments)
                row = {"case": label, "side": side, "status": result["status"],
                       "removed_mm3": 96000 - _volume(model)}
                if succeeds:
                    assert result["status"] == "ok", result
                    assert tuple(result["feature_evidence"]["feature_names"]) == (label,)
                    expected_planes = sorted([0., side * 20.])
                    _check_success(model, expected_planes)
                    row["hole_openings_z_mm"] = expected_planes
                    path = output / f"{label}.SLDPRT"
                    save_preview(model, str(output / f"{label}.bmp"), "isometric")
                    assert session.save(model, str(path)) and not get(model, "GetSaveFlag")
                    identity = get(model, "GetPathName")
                    assert Path(identity).resolve() == path
                    _close(session, model, identity)
                    model = session.open(str(path), read_only=True, silent=True)
                    assert Path(get(model, "GetPathName")).resolve() == path
                    assert get(model, "ForceRebuild3", False)
                    _check_success(model, expected_planes)
                    _close(session, model, get(model, "GetPathName"))
                    row["reopened_ok"] = True
                else:
                    assert result["status"] == "error" and result["error_code"] == "SW_HOLE_NOT_CREATED", result
                    assert result["retryable"] is False
                    assert result["diagnostics"]["direction_reversed"] is (reverse is not True)
                    assert math.isclose(row["removed_mm3"], 0., abs_tol=1e-4)
                    assert not _hole_openings(model)
                    row["diagnostics"] = result["diagnostics"]
                    assert not get(model, "GetPathName")
                    _close(session, model, title)
                report["cases"].append(row)
                print(json.dumps(row, ensure_ascii=False), flush=True)


def run(version, output, baseline=False):
    """执行真实 stdio MCP 的通孔方向对照。

    参数:
        version: 目标 SolidWorks 年份。
        output: 尚不存在的输出目录。
        baseline: 是否仅运行兼容未修订版本的默认方向对照。

    返回:
        各用例的脱敏几何、保存重开与失败诊断报告。
    """
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    before = solidworks_processes()
    assert before is not None and len(before) <= 1
    report = {
        "status": "failed", "cases": [], "sources": {
            path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest()
            for path in ("scripts/sw_part.py", "scripts/sw_hole_features.py", "mcp-server/server.py")
        },
    }
    try:
        with SolidWorksSession(version=version, wait_seconds=60, visible=True) as session:
            assert get(session.sw, "GetDocumentCount") == 0, "需空白会话"
            assert bool(get(session.sw, "Visible"))
            report["environment"] = get_sw_version(session.sw)
            report["started_by_test"] = bool(session.connection_info.get("started_by_cad_studio"))
            asyncio.run(_cases(session, version, output, baseline, report))
            assert get(session.sw, "GetDocumentCount") == 0
            report["remaining_documents"] = 0
        report["status"] = "passed"
    finally:
        (output / "native-report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8",
        )
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--baseline", action="store_true")
    args = parser.parse_args()
    os.environ["SW_ATTACH_EXISTING_DISPATCH"] = "1"
    run(args.version, args.output, args.baseline)
