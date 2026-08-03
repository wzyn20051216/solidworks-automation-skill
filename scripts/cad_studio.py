"""CAD Studio 统一 CLI：doctor/run/status/retry/cancel/export-diagnostics。"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
DESKTOP = ROOT / "apps" / "desktop"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
if str(DESKTOP) not in sys.path:
    sys.path.insert(0, str(DESKTOP))

from cad_workbench.queue_worker import cancel_marker_path, default_tauri_queue_dir, process_queue, read_job, write_job  # noqa: E402
from cad_doctor import run_doctor  # noqa: E402
from cad_diagnostics import create_diagnostic_bundle  # noqa: E402


def _queue_jobs(queue_dir: Path) -> list[dict[str, Any]]:
    jobs = []
    for path in sorted(Path(queue_dir).glob("*.json")):
        if path.name in {"worker_health.json", "provider_verifications.json"}:
            continue
        try:
            job = read_job(path)
            job["_path"] = path.name
            jobs.append(job)
        except (OSError, ValueError, json.JSONDecodeError):
            continue
    return jobs


def _job_path(queue_dir: Path, job_id: str) -> Path:
    path = Path(queue_dir) / f"{job_id}.json"
    if path.is_file():
        return path
    for candidate in Path(queue_dir).glob("*.json"):
        try:
            if read_job(candidate).get("id") == job_id:
                return candidate
        except Exception:
            continue
    raise FileNotFoundError(f"未找到任务: {job_id}")


def _retry_from_stage(job: dict[str, Any]) -> str:
    """根据领域证据推断局部重试的最早阶段。"""
    phases = (((job.get("result") or {}).get("engineeringPlan") or {}).get("phases") or [])
    for phase in phases:
        if phase.get("status") in {"blocked", "failed", "review_required"} and phase.get("id"):
            return str(phase["id"])
    for key in ("drawingEvidence", "bomEvidence"):
        if (job.get(key) or {}).get("status") in {"blocked", "failed", "fail", "warning"}:
            return "drawing-bom"
    if (job.get("dfmEvidence") or {}).get("status") in {"blocked", "failed", "fail", "warning"}:
        return "dfm-review"
    if job.get("status") in {"failed", "review_required"}:
        return "final-review"
    return "requirements"


def _run_history_snapshot(job: dict[str, Any]) -> dict[str, Any]:
    """保存不包含 Prompt、凭据和递归历史的只读任务快照。"""
    fields = (
        "runId", "status", "stage", "createdAt", "updatedAt", "lastMessage", "error", "result",
        "artifacts", "artifactLedgerPath", "reviewGatePath", "reviewGate", "drawingEvidence",
        "bomEvidence", "dfmEvidence", "reviewFindings", "artifactRelations", "blockedReasons",
    )
    return {field: job[field] for field in fields if field in job}


def prepare_job_for_retry(job: dict[str, Any], updated_at: str) -> dict[str, Any]:
    """将终态任务重置为新一轮执行，同时保留旧产物和失败证据。"""
    if job.get("status") not in {"failed", "cancelled", "blocked", "review_required"}:
        raise ValueError(f"任务当前状态不可重试: {job.get('status')}")
    previous_run_id = job.get("runId")
    history = [*(job.get("runHistory") or []), _run_history_snapshot(job)][-20:]
    retry_stage = _retry_from_stage(job)
    job.update({
        "runHistory": history,
        "retryPolicy": {
            "previousRunId": previous_run_id,
            "retryFromStage": retry_stage,
            "scope": "failed_stage_and_downstream",
            "preservePreviousArtifacts": True,
            "overwrite": False,
            "requestedAt": updated_at,
        },
        "runId": f"retry-{uuid4().hex}",
        "status": "queued",
        "progress": 0,
        "updatedAt": updated_at,
        "lastMessage": "已重新排队，将从失败阶段及其后继阶段执行。",
        "artifacts": [],
    })
    for field in (
        "error", "result", "artifactLedgerPath", "reviewGatePath", "reviewGate", "reviewedAt",
        "reviewedBy", "reviewDecision", "reviewNote", "runnerId", "workerPid", "heartbeatAt",
        "leaseUntil", "cancelRequested", "workerLog", "drawingEvidence", "bomEvidence",
        "dfmEvidence", "reviewFindings", "artifactRelations", "blockedReasons",
    ):
        job.pop(field, None)
    return job


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="cad-studio", description="CAD Studio 本地任务与环境 CLI")
    parser.add_argument("--queue-dir", type=Path, default=default_tauri_queue_dir())
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("doctor")
    run = sub.add_parser("run")
    run.add_argument("--limit", type=int, default=None)
    run.add_argument("--enable-mock", action="store_true")
    status = sub.add_parser("status")
    status.add_argument("job_id", nargs="?")
    retry = sub.add_parser("retry")
    retry.add_argument("job_id")
    cancel = sub.add_parser("cancel")
    cancel.add_argument("job_id")
    diagnostics = sub.add_parser("export-diagnostics")
    diagnostics.add_argument("--output", type=Path, default=Path.cwd() / "cad-studio-diagnostics.zip")
    write_open = sub.add_parser("write-open-format")
    write_open.add_argument("--input", type=Path, required=True, help="NeutralCadDocument .cadstudio.json")
    write_open.add_argument("--out-dir", type=Path, required=True)
    write_open.add_argument("--formats", nargs="+", default=["cadstudio", "step", "iges", "brep", "stl", "obj", "glb", "dxf", "svg", "pdf", "png"])
    preview_dxf = sub.add_parser("preview-dxf")
    preview_dxf.add_argument("--input", type=Path, required=True, help="只读 DXF 输入")
    preview_dxf.add_argument("--output", type=Path, required=True, help="不覆盖的 .scene.json 输出")
    dfm = sub.add_parser("check-dfm")
    dfm.add_argument("--input", type=Path, required=True, help="NeutralCadDocument .cadstudio.json")
    dfm.add_argument("--output", type=Path, required=True, help="不覆盖旧文件的 DFM report JSON 输出")
    dfm.add_argument("--process", default="auto", help="machining/sheet_metal/laser_cutting/3d_printing；auto 时读取文档 metadata")
    dfm.add_argument("--profile", action="append", default=[], help="可重复指定 DFM Profile JSON，按供应商能力交集合并")
    dfm.add_argument("--brep-evidence", type=Path, help="可选 SolidWorks/OCCT B-Rep 证据 JSON")
    routing = sub.add_parser("check-routing")
    routing.add_argument("--input", type=Path, required=True, help="Routing 中性 JSON 输入")
    routing.add_argument("--output", type=Path, required=True, help="不覆盖旧文件的 Routing report JSON 输出")
    sub.add_parser("routing-preflight")
    fea_preflight = sub.add_parser("fea-preflight")
    fea_preflight.add_argument("--solver", choices=("auto", "calculix", "elmer"), default="auto")
    fea_prepare = sub.add_parser("prepare-fea")
    fea_prepare.add_argument("--input", type=Path, required=True, help="FEA 1.0 请求 JSON")
    fea_prepare.add_argument("--out-dir", type=Path, required=True, help="CalculiX 输入文件输出目录")
    fea_prepare.add_argument("--solver", choices=("auto", "calculix", "elmer"), default="auto")
    fea_run = sub.add_parser("run-fea")
    fea_run.add_argument("--input", type=Path, required=True, help="FEA 1.0 请求 JSON")
    fea_run.add_argument("--out-dir", type=Path, required=True, help="版本化求解目录")
    fea_run.add_argument("--timeout", type=int, default=600, help="求解超时秒数，范围 1-86400")
    fea_convergence = sub.add_parser("run-fea-convergence")
    fea_convergence.add_argument("--input", type=Path, required=True, help="FEA 网格收敛 1.0 请求 JSON")
    fea_convergence.add_argument("--out-dir", type=Path, required=True, help="版本化收敛序列目录")
    fea_convergence.add_argument("--timeout-per-case", type=int, default=600, help="每档网格求解超时秒数，范围 1-86400")
    advanced = sub.add_parser("review-advanced-geometry")
    advanced.add_argument("--input", type=Path, required=True, help="复杂曲面/模具中性计划 JSON")
    advanced.add_argument("--output", type=Path, required=True, help="不覆盖旧文件的前置报告 JSON 输出")
    loft = sub.add_parser("create-ocp-loft")
    loft.add_argument("--input", type=Path, required=True, help="OCP Loft 1.0 参数 JSON")
    loft.add_argument("--out-dir", type=Path, required=True, help="STEP/BREP/STL 版本化输出目录")
    args = parser.parse_args(argv)

    if args.command == "doctor":
        result = run_doctor()
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1 if result["summary"]["status"] == "error" else 0
    if args.command == "status":
        jobs = _queue_jobs(args.queue_dir)
        if args.job_id:
            jobs = [job for job in jobs if job.get("id") == args.job_id]
        print(json.dumps({"queueDir": args.queue_dir.name, "jobs": jobs}, ensure_ascii=False, indent=2))
        return 0 if jobs or not args.job_id else 1
    if args.command == "run":
        from cad_workbench.queue_worker import build_handlers

        processed = process_queue(args.queue_dir, limit=args.limit, handlers=build_handlers(enable_mock=args.enable_mock))
        print(json.dumps({"processed": processed}, ensure_ascii=False, indent=2))
        return 0
    if args.command in {"retry", "cancel"}:
        path = _job_path(args.queue_dir, args.job_id)
        job = read_job(path)
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        if args.command == "retry":
            try:
                prepare_job_for_retry(job, now)
            except ValueError as exc:
                raise SystemExit(str(exc)) from exc
            cancel_marker_path(path).unlink(missing_ok=True)
        else:
            job.update({"status": "cancelled", "cancelRequested": True, "updatedAt": now, "lastMessage": "已请求取消任务。"})
            cancel_marker_path(path).touch()
        write_job(path, job)
        print(json.dumps(job, ensure_ascii=False, indent=2))
        return 0
    if args.command == "export-diagnostics":
        path = create_diagnostic_bundle(args.output)
        print(json.dumps({"status": "created", "path": path.name}, ensure_ascii=False))
        return 0
    if args.command == "write-open-format":
        from headless_cad_writer import export_headless

        result = export_headless(args.input, args.out_dir, args.formats)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result.get("status") in {"pass", "pilot"} else 1
    if args.command == "preview-dxf":
        from dxf_preview_scene import dxf_to_preview_scene

        scene = dxf_to_preview_scene(args.input, args.output)
        print(json.dumps({
            "status": "pass",
            "backend": "ezdxf-preview-scene",
            "input": args.input.name,
            "output": str(args.output.resolve()),
            "entityCount": len(scene["entities"]),
            "layerCount": len(scene["layers"]),
            "limitations": scene["limitations"],
        }, ensure_ascii=False, indent=2))
        return 0
    if args.command == "check-dfm":
        from dfm_review import write_dfm_report

        result = write_dfm_report(args.input, args.output, process=args.process, profiles=args.profile, brep_evidence=args.brep_evidence)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1 if result.get("status") in {"blocked", "failed"} else 0
    if args.command == "check-routing":
        from routing_review import review_routing_file

        result = review_routing_file(args.input, args.output)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1 if result.get("status") in {"blocked", "failed"} else 0
    if args.command == "routing-preflight":
        from routing_review import probe_solidworks_routing

        result = probe_solidworks_routing()
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1 if result.get("status") in {"blocked", "failed"} else 0
    if args.command == "fea-preflight":
        from fea_analysis import discover_solver

        result = discover_solver(args.solver)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1 if result.get("status") in {"blocked", "failed"} else 0
    if args.command == "prepare-fea":
        from fea_analysis import build_calculix_input, validate_analysis

        request = validate_analysis(args.input)
        if args.solver != "auto":
            request["solver"] = args.solver
        if request["solver"] == "elmer":
            result = {
                "schemaVersion": "1.0",
                "status": "blocked",
                "stage": "generate_input",
                "checks": [],
                "artifacts": [],
                "manual_review_required": True,
                "retryable": False,
                "error_code": "fea_elmer_adapter_not_implemented",
                "message": "Elmer 安全输入适配器尚未实现；当前 prepare-fea 只生成 CalculiX .inp。",
            }
        else:
            args.out_dir.mkdir(parents=True, exist_ok=True)
            result = build_calculix_input(request, args.out_dir / f"{request['analysisId']}.inp")
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1 if result.get("status") in {"blocked", "failed"} else 0
    if args.command == "run-fea":
        from fea_analysis import run_analysis

        result = run_analysis(args.input, args.out_dir, timeout_seconds=args.timeout)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1 if result.get("status") in {"blocked", "failed"} else 0
    if args.command == "run-fea-convergence":
        from fea_convergence import run_convergence_study

        result = run_convergence_study(args.input, args.out_dir, timeout_seconds_per_case=max(1, min(args.timeout_per_case, 86400)))
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1 if result.get("status") in {"blocked", "failed"} else 0
    if args.command == "review-advanced-geometry":
        from advanced_geometry import write_preflight_report

        result = write_preflight_report(args.input, args.output)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1 if result.get("status") in {"blocked", "failed"} else 0
    if args.command == "create-ocp-loft":
        from advanced_geometry_ocp import execute_ocp_loft

        result = execute_ocp_loft(args.input, args.out_dir)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1 if result.get("status") in {"blocked", "failed"} else 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
