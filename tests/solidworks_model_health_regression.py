"""@brief SW2026 真实文档、结构和损坏文件诊断，使用独立空实例。"""
import argparse
import json
from pathlib import Path
import sys
import faulthandler

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import pythoncom
from scripts.sw_connect import connect_solidworks, new_document, get_com_member, open_document, SolidWorksDocumentOpenError
from scripts.sw_review import run_review
from scripts.sw_process import solidworks_processes


def main(output, source):
    """@brief 保存真实审查报告，不能用假预览替代 SDK 结果。"""
    if solidworks_processes() != {}:
        raise RuntimeError("健康度真机验收需要空闲的测试实例")
    output.mkdir(parents=True, exist_ok=False)
    result = {"status":"failed", "cases":[]}
    sw = None
    owned = []
    pythoncom.CoInitialize()
    faulthandler.dump_traceback_later(60, repeat=True)
    try:
        print("PHASE connect", flush=True)
        sw, _, metadata = connect_solidworks(version=2026, wait_seconds=60, visible=True, return_metadata=True)
        if not metadata["started_by_cad_studio"]:
            raise RuntimeError("测试实例归属未确认")
        model = open_document(sw, str(source.resolve()), read_only=True, silent=True, raise_on_error=True)
        owned.append(model)
        print("PHASE review_healthy_part", flush=True)
        report, path = run_review(model, str(output / "part"), basename="healthy", expected_outputs=[str(source)])
        if report["model"].get("faulty_features") or not report["checks"]["rebuild_succeeded"]:
            raise RuntimeError("健康零件被误判为特征故障")
        result["cases"].append({"name":"healthy_part", "status":"pass", "report":path,
            "feature_health": report["model"]["features"], "evaluation":report["evaluation"]["status"]})
        drawing = new_document(sw, "drawing")
        owned.append(drawing)
        print("PHASE review_empty_drawing", flush=True)
        report, path = run_review(drawing, str(output / "drawing"), basename="empty")
        codes = {item["code"] for item in report["evaluation"]["issues"]}
        if "drawing_views_missing" not in codes or report["evaluation"]["status"] != "fail":
            raise RuntimeError(f"空工程图未被识别: {report['drawing_structure']}")
        result["cases"].append({"name":"empty_drawing", "status":"pass", "report":path})
        corrupted = output / "corrupted.sldprt"
        corrupted.write_bytes(b"not-a-solidworks-document")
        print("PHASE open_corrupted_file", flush=True)
        try:
            open_document(sw, str(corrupted), silent=True, raise_on_error=True)
        except SolidWorksDocumentOpenError as error:
            result["cases"].append({"name":"corrupt_file", "status":"pass", "code":error.code,
                "raw_errors":error.error_code,"raw_warnings":error.warnings,"message":str(error)})
        else:
            raise RuntimeError("损坏文件未阻断")
        result.update(status="pass",year=metadata["actual_version"],revision=metadata["actual_revision"])
    except Exception as error:
        result["error"] = f"{type(error).__name__}: {error}"
    finally:
        if sw is not None:
            try:
                for model in reversed(owned):
                    sw.CloseDoc(str(get_com_member(model,"GetTitle")))
                remaining = list(get_com_member(sw,"GetDocuments") or [])
                result["remaining_documents"] = len(remaining)
                if not remaining:
                    sw.ExitApp()
            except Exception as error:
                result.update(status="failed",cleanup_error=str(error))
        pythoncom.CoUninitialize()
        faulthandler.cancel_dump_traceback_later()
        (output / "report.json").write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(result,ensure_ascii=True,indent=2))
    return 0 if result["status"]=="pass" else 1


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--source",type=Path,required=True)
    args=parser.parse_args()
    raise SystemExit(main(args.output.resolve(),args.source))
