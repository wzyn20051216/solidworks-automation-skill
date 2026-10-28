"""
@file sw_drawing_dotnet.py
@brief .NET C# 自动出图执行器的 Python 启动器与契约层。

分工：Python 只做“非原生精度”工作——校验/生成 drawing_spec、调度、解析回写的 evidence、
交给 review 判定；真正用 SolidWorks 原生精度落图（视图/尺寸/GD&T/孔表/BOM/标题栏）由
dotnet/CadStudio.SolidWorks.Drawing 的 C# PIA 执行器完成（强类型 out/ref/枚举，封送比 Python
COM 稳）。两者通过中性 drawing_spec JSON（入）+ drawing-evidence JSON（出）解耦。

本模块可离线单测的部分：spec 校验门禁、executor 路径解析、evidence 解析与结果汇总。
真正启动 C# exe 为 pilot——需 Windows + SolidWorks + 已编译执行器；本环境（Linux 无 SW）只校验契约。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Mapping

THIS_FILE = Path(__file__).resolve()
REPO_ROOT = THIS_FILE.parents[1]
DRAWING_SUBSKILL_SCRIPTS = REPO_ROOT / "subskills" / "solidworks-engineering-drawing" / "scripts"
# C# 执行器默认产物位置（msbuild 输出）。
DEFAULT_EXE_CANDIDATES = [
    REPO_ROOT / "dotnet" / "CadStudio.SolidWorks.Drawing" / "bin" / "Release" / "net48" / "CadStudio.SolidWorks.Drawing.exe",
    REPO_ROOT / "dotnet" / "CadStudio.SolidWorks.Drawing" / "bin" / "x64" / "Release" / "net48" / "CadStudio.SolidWorks.Drawing.exe",
]

BUILD_HINT = (
    "未找到 C# 出图执行器 exe。请在 Windows 上先编译：\n"
    "  dotnet build dotnet/CadStudio.SolidWorks.Drawing/CadStudio.SolidWorks.Drawing.csproj "
    "-c Release -p:SolidWorksApiDir=\"C:\\Program Files\\SOLIDWORKS Corp\\SOLIDWORKS\\api\\redist\"\n"
    "或用 --executor / 环境变量 CADSTUDIO_DRAWING_EXE 指定 exe 路径。"
)


def resolve_executor(explicit: str | None = None) -> str | None:
    """@brief 解析 C# 执行器 exe 路径：显式 > 环境变量 > 默认产物位置。"""
    if explicit:
        return explicit if Path(explicit).is_file() else None
    env = os.environ.get("CADSTUDIO_DRAWING_EXE")
    if env and Path(env).is_file():
        return env
    for candidate in DEFAULT_EXE_CANDIDATES:
        if candidate.is_file():
            return str(candidate)
    return None


def validate_spec_file(spec_path: str | Path) -> dict[str, Any]:
    """@brief 用工程图子技能的 validate_drawing_spec 做出图前门禁（缺 jsonschema 时不阻断，记提示）。"""
    if str(DRAWING_SUBSKILL_SCRIPTS) not in sys.path:
        sys.path.insert(0, str(DRAWING_SUBSKILL_SCRIPTS))
    try:
        from drawing_spec import validate_drawing_spec  # type: ignore
    except Exception as exc:  # noqa: BLE001
        return {"status": "skipped", "reason": f"无法加载 drawing_spec 校验器: {exc}", "issues": []}
    result = validate_drawing_spec(str(spec_path))
    issues = result.get("issues", [])
    only_validator_missing = bool(issues) and all(
        str(i.get("code", "")).endswith("VALIDATOR_MISSING") for i in issues
    )
    if result.get("status") != "pass" and not only_validator_missing:
        return {"status": "blocked", "reason": "drawing_spec 未通过 schema 校验", "issues": issues}
    return {"status": "pass", "issues": issues}


def parse_evidence(text: str) -> dict[str, Any]:
    """@brief 解析 C# 执行器回写的 evidence JSON（宽松：非 JSON 返回 blocked）。"""
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return {"schema": "cadstudio.drawing-evidence", "status": "blocked", "error": "evidence 不是合法 JSON"}
    if not isinstance(data, dict):
        return {"schema": "cadstudio.drawing-evidence", "status": "blocked", "error": "evidence 不是对象"}
    return data


def summarize_result(evidence: Mapping[str, Any]) -> dict[str, Any]:
    """@brief 汇总 evidence：门禁状态、各阶段状态、落盘产物、pilot 阶段清单。"""
    stages = evidence.get("stages") if isinstance(evidence.get("stages"), Mapping) else {}
    stage_status = {name: (s.get("status") if isinstance(s, Mapping) else None) for name, s in stages.items()}
    pilot_stages = sorted(name for name, st in stage_status.items() if st == "pilot")
    failed_stages = sorted(name for name, st in stage_status.items() if st == "fail")
    artifacts = evidence.get("artifacts") if isinstance(evidence.get("artifacts"), list) else []
    produced = [a.get("path") for a in artifacts if isinstance(a, Mapping) and a.get("exists")]
    return {
        "status": evidence.get("status", "blocked"),
        "reviewRequired": True,
        "stageStatus": stage_status,
        "pilotStages": pilot_stages,
        "failedStages": failed_stages,
        "producedArtifacts": produced,
        "error": evidence.get("error"),
    }


def run_drawing_executor(
    spec_path: str | Path,
    *,
    source_model: str | None = None,
    output_dir: str | Path | None = None,
    executor_path: str | None = None,
    pdf: str | None = None,
    save: str | None = None,
    timeout: int = 600,
) -> dict[str, Any]:
    """@brief 校验 spec -> 解析执行器 -> 启动 C# 出图 -> 解析 evidence。C# 启动部分为 pilot。"""
    spec_path = Path(spec_path)
    gate = validate_spec_file(spec_path)
    if gate["status"] == "blocked":
        return {"status": "blocked", "reason": gate["reason"], "specIssues": gate["issues"]}

    exe = resolve_executor(executor_path)
    if not exe:
        return {"status": "blocked", "reason": "executor_not_found", "hint": BUILD_HINT}

    out_dir = Path(output_dir) if output_dir else spec_path.resolve().parent
    out_dir.mkdir(parents=True, exist_ok=True)
    evidence_out = out_dir / f"{spec_path.stem}_drawing_evidence.json"
    cmd = [exe, "--spec", str(spec_path.resolve()), "--evidence-out", str(evidence_out)]
    if source_model:
        cmd += ["--source-model", source_model]
    if pdf:
        cmd += ["--pdf", pdf]
    if save:
        cmd += ["--save", save]

    try:
        completed = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return {"status": "blocked", "reason": f"C# 执行器超时（{timeout}s）", "specGate": gate["status"]}
    except OSError as exc:
        return {"status": "blocked", "reason": f"启动 C# 执行器失败: {exc}"}

    if evidence_out.is_file():
        evidence = parse_evidence(evidence_out.read_text(encoding="utf-8"))
    else:
        evidence = parse_evidence(completed.stdout)
    result = summarize_result(evidence)
    result["evidencePath"] = str(evidence_out) if evidence_out.is_file() else None
    result["exitCode"] = completed.returncode
    result["specGate"] = gate["status"]
    result["evidence"] = evidence
    return result


def main(argv: list[str] | None = None) -> int:
    """@brief 命令行入口。"""
    import argparse

    parser = argparse.ArgumentParser(description="用 .NET C# 执行器把 drawing_spec 落成 SLDDRW（Python 调度）。")
    parser.add_argument("spec", help="drawing_spec JSON 路径（Python 侧生成，已 schema 校验）。")
    parser.add_argument("--source-model", help="源模型 SLDPRT 路径，缺省取 spec.sourceModel。")
    parser.add_argument("--output-dir", help="evidence/产物输出目录。")
    parser.add_argument("--executor", help="C# 执行器 exe 路径；缺省查环境变量/默认产物位置。")
    parser.add_argument("--pdf", help="PDF 导出路径。")
    parser.add_argument("--save", help="SLDDRW 保存路径。")
    parser.add_argument("--timeout", type=int, default=600)
    args = parser.parse_args(argv)

    result = run_drawing_executor(
        args.spec,
        source_model=args.source_model,
        output_dir=args.output_dir,
        executor_path=args.executor,
        pdf=args.pdf,
        save=args.save,
        timeout=args.timeout,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if result.get("status") in {"blocked", "failed"} else 0


if __name__ == "__main__":
    raise SystemExit(main())
