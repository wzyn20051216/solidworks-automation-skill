"""SolidWorks 2026 真机交付门禁回归，仅操作本轮临时模型和文件。"""
import json
import os
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from apps.desktop.cad_workbench.artifact_ledger import build_artifact_ledger, sha256_file
from apps.desktop.cad_workbench.queue_worker import _snapshot_cad_artifacts
from apps.desktop.cad_workbench.reviewer_gate import evaluate_ledger
from scripts.sw_connect import get_com_member
from scripts.sw_part import sketch, sketch_circle, extrude_boss
from scripts.sw_review import run_review
from scripts.sw_session import SolidWorksSession
from scripts.sw_sketch_quality import fully_define_sketch


def main():
    folder = Path(tempfile.mkdtemp(prefix="sw_artifact_gate_"))
    print("OUTPUT", folder, flush=True)
    cases = []
    def check(path, baseline, executor, expected, source="artifacts"):
        job = {"id": "live-freshness", "executor": executor, "expectedOutput": "STEP",
               "uiConfig": {"cadRuntime": {"localCadAutomation": True}}}
        result = {"artifactBaseline": baseline, "verification": [{"command": "SolidWorks 2026 native reopen", "status": "passed"}]}
        holder = job if source == "job" else result
        holder["artifacts" if source == "job" else source] = [{"kind": "step", "path": str(path)}]
        ledger = build_artifact_ledger(folder, job, result)
        review = evaluate_ledger(ledger)
        assert review["status"] == expected, review
        cases.append({"executor": executor, "source": source, "expected": expected,
                      "status": review["status"], "producedThisRun": ledger["artifacts"][0]["producedThisRun"]})

    with SolidWorksSession(version=2026, visible=True) as session:
        before = {get_com_member(doc, "GetTitle") for doc in session._documents()}
        baseline = _snapshot_cad_artifacts([folder])
        model = session.new_part()
        with sketch(model, "Front Plane") as ref:
            sketch_circle(model, 0, 0, .01)
            assert fully_define_sketch(model)["status"] == "pass"
        assert extrude_boss(model, ref, .01)
        native, step = folder / "cylinder.sldprt", folder / "cylinder.step"
        assert session.save(model, str(native))
        assert session.export(model, str(step))
        digest = sha256_file(native)
        review, report_path = run_review(model, folder / "preview", basename="cylinder", expected_outputs=[native, step])
        assert review["evaluation"]["status"] == "pass", report_path
        session.close(model)
        reopened = session.open(str(native), read_only=True, silent=True)
        assert len(list(get_com_member(reopened, "GetBodies2", 0, False) or [])) == 1
        session.close(reopened)
        assert sha256_file(native) == digest
        for executor in ("agent", "codex", "solidworks-com-pywin32"):
            check(step, baseline, executor, "pass")
            old = _snapshot_cad_artifacts([folder])
            os.utime(step, None)
            check(step, old, executor, "fail")
            check(step, None, executor, "warning")
            check(step, _snapshot_cad_artifacts([folder], limit=0), executor, "warning")
            outside = folder / "empty-scan"
            outside.mkdir(exist_ok=True)
            for source in ("job", "outputs", "artifacts"):
                check(step, _snapshot_cad_artifacts([outside]), executor, "warning", source)
        assert {get_com_member(doc, "GetTitle") for doc in session._documents()} == before
        version = str(get_com_member(session.sw, "RevisionNumber"))
        assert version.startswith("34."), version
    evidence = {"status": "pass", "solidworksRevision": version, "nativeReopen": "pass",
                "sourceUnchanged": True, "userDocumentsPreserved": True, "cases": cases}
    (folder / "freshness-evidence.json").write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
    print("PASS", len(cases), "cases", folder, flush=True)


if __name__ == "__main__":
    main()
