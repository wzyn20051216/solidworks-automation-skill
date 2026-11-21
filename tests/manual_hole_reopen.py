"""对照新建、重开及独立 MCP 服务的通孔创建；仅使用本轮测试零件。"""
import argparse
import asyncio
from datetime import timedelta
import hashlib
import json
import math
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.sw_connect import get_com_member as get, get_sw_version
from scripts.sw_hole_features import create_through_hole, HoleFeatureCreationError
from scripts.sw_part import (sketch, sketch_rectangle, sketch_circle, extrude_boss,
                             extrude_cut, clear_sketch_selection_cache)
from scripts.sw_process import solidworks_processes
from scripts.sw_review import save_preview, collect_model_summary
from scripts.sw_session import SolidWorksSession
from scripts.sw_sketch_quality import fully_define_sketch


def volume(model):
    """回读单实体体积，单位立方毫米。"""
    bodies = list(get(model, "GetBodies2", 0, False) or [])
    assert len(bodies) == 1
    return float(get(bodies[0], "GetMassProperties", 1.)[3]) * 1e9


def plate(session):
    """创建 80×60×20 mm 板，材料位于前视基准面正侧。"""
    model = session.new_part()
    with sketch(model) as ref:
        assert sketch_rectangle(model, 0, 0, .080, .060) is not None
        assert fully_define_sketch(model)["status"] == "pass"
    assert extrude_boss(model, ref, .020, direction=False) is not None
    assert math.isclose(volume(model), 96000., abs_tol=1e-4)
    return model


async def mcp_hole(path, center, expected_pid, version, expect_failure=False):
    """在独立 MCP 进程中重开测试件并调用真实孔工具。"""
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    params = StdioServerParameters(command=sys.executable,
        args=[str(ROOT / "mcp-server/server.py")], cwd=str(ROOT),
        env={**os.environ, "SW_MCP_DISCOVERY": "full", "SW_MCP_APPROVAL": "client"})
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write, read_timeout_seconds=timedelta(seconds=90)) as client:
            await client.initialize()
            async def call(name, arguments, expected_status="ok"):
                result = await client.call_tool(name, {"params": arguments})
                assert not result.isError, result
                payload = json.loads(next(c.text for c in result.content if c.type == "text"))
                assert payload["status"] == expected_status, payload
                return payload
            connected = await call("solidworks_connect", {"version": version, "wait_seconds": 1})
            assert connected["process_id"] == expected_pid
            await call("solidworks_open_document", {"path": str(path), "silent": True})
            payload = await call("solidworks_create_hole_feature", {
                "feature_kind": "through", "center_x_mm": center[0] * 1000,
                "center_y_mm": center[1] * 1000, "diameter_mm": 6,
                "feature_name": "H_MCP_Reopened"}, "error" if expect_failure else "ok")
    if expect_failure:
        assert payload["error_code"] == "SW_HOLE_NOT_CREATED" and payload["retryable"] is False
        return payload["diagnostics"]
    return payload["feature_evidence"]


def run(version, output):
    """执行原生 COM 及 MCP 回归，保存测试件与失败诊断。"""
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    before = solidworks_processes()
    assert before is not None and len(before) <= 1
    report = {"status": "failed", "cases": [], "sources": {
        name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
        for name in ["scripts/sw_part.py", "scripts/sw_hole_features.py"]}}
    removed_expected = math.pi * 3 ** 2 * 20
    try:
        with SolidWorksSession(version=version, wait_seconds=60) as session:
            assert get(session.sw, "GetDocumentCount") == 0, "需空白会话"
            report["environment"] = get_sw_version(session.sw)
            original_processes = solidworks_processes()
            for seeded in [False, True]:
                model = plate(session)
                if seeded:
                    create_through_hole(model, (-.020, 0), .006, name="H_Fresh")
                    assert math.isclose(volume(model), 96000 - removed_expected, abs_tol=1e-4)
                baseline = output / f"baseline-{seeded}.SLDPRT"
                assert session.save(model, str(baseline))
                for case in ["fresh_helper", "reopened_helper", "reopened_cold_cache", "reopened_bare", "reopened_mcp"]:
                    if case != "fresh_helper":
                        session.close(model)
                        if case == "reopened_mcp":
                            evidence = asyncio.run(mcp_hole(baseline, (.020, 0),
                                int(get(session.sw, "GetProcessID")), version))
                            model = session.open(str(baseline), silent=True)
                            previous = 96000 - (removed_expected if seeded else 0)
                        else:
                            model = session.open(str(baseline), silent=True)
                    if case != "reopened_mcp":
                        if case == "reopened_cold_cache":
                            clear_sketch_selection_cache()
                        previous = volume(model)
                        if case == "reopened_bare":
                            with sketch(model) as ref:
                                assert sketch_circle(model, .020, 0, .003) is not None
                            assert extrude_cut(model, ref, 0) is not None
                        else:
                            evidence = create_through_hole(model, (.020, 0), .006, name="H_Test")
                    removed_actual = previous - volume(model)
                    assert math.isclose(removed_actual, removed_expected, abs_tol=1e-4)
                    assert get(model, "ForceRebuild3", False)
                    summary = collect_model_summary(model)
                    assert not summary["faulty_features"]
                    assert not summary["warning_features"]
                    assert not summary["unknown_feature_health"] and not summary.get("feature_error")
                    if case == "reopened_mcp":
                        target = output / f"result-{seeded}.SLDPRT"
                        assert session.save(model, str(target))
                        save_preview(model, str(output / f"result-{seeded}.bmp"))
                        session.close(model)
                        model = session.open(str(target), silent=True)
                        expected_total = 96000 - removed_expected * (2 if seeded else 1)
                        assert math.isclose(volume(model), expected_total, abs_tol=1e-4)
                    row = {"case": case, "seeded": seeded,
                           "removed_mm3": removed_actual, "expected_removed_mm3": removed_expected,
                           "geometry_matches": True}
                    report["cases"].append(row)
                    print(json.dumps(row), flush=True)
                session.close(model)
            model = plate(session)
            previous = volume(model)
            failure_baseline = output / "failure-baseline.SLDPRT"
            assert session.save(model, str(failure_baseline))
            try:
                create_through_hole(model, (.200, 0), .006, name="H_Outside")
            except HoleFeatureCreationError as error:
                report["non_intersecting_diagnostics"] = error.diagnostics
            else:
                raise AssertionError("不相交孔不应报告成功")
            assert math.isclose(volume(model), previous, abs_tol=1e-4)
            session.close(model)
            report["mcp_non_intersecting_diagnostics"] = asyncio.run(mcp_hole(
                failure_baseline, (.200, 0), int(get(session.sw, "GetProcessID")), version, True))
            model = session.open(str(failure_baseline), silent=True)
            assert math.isclose(volume(model), previous, abs_tol=1e-4)
            session.close(model)
            assert solidworks_processes() == original_processes
            assert get(session.sw, "GetDocumentCount") == 0
        report["status"] = "passed"
        report["created_documents_closed"] = True
        # ExitApp 为异步退出，不能把调用后瞬时清单当作残留进程。
        deadline = time.monotonic() + 20
        while solidworks_processes() != before and time.monotonic() < deadline:
            time.sleep(.2)
        report["processes_restored"] = solidworks_processes() == before
        assert report["processes_restored"], "本轮自启实例未在限定时间内退出"
    except Exception as error:
        report["error"] = repr(error)
        raise
    finally:
        (output / "native-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.version, args.output), ensure_ascii=False, indent=2))
