"""@brief SW2026 强制 comtypes 回退、引用重开和用户文档保护真机验收。"""
import argparse
import json
from pathlib import Path
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import pythoncom
from scripts import sw_delivery
from scripts.sw_connect import connect_solidworks, get_com_member, new_document, save_document, open_document
from scripts.sw_part import sketch, sketch_rectangle, extrude_boss
from scripts.sw_sketch_quality import fully_define_sketch
from scripts.sw_assembly import add_component, get_components
from scripts.sw_process import solidworks_processes


def close_test_files(sw, root):
    """@brief 每次刷新清单，避免对已随装配体卸载的零件代理重复操作。"""
    for _ in range(12):
        candidates = []
        for doc in get_com_member(sw, "GetDocuments") or []:
            path = str(get_com_member(doc, "GetPathName") or "")
            if path and Path(path).resolve().is_relative_to(root):
                candidates.append(doc)
        if not candidates:
            return
        candidates.sort(key=lambda item: int(get_com_member(item, "GetType")) != 2)
        sw.CloseDoc(str(get_com_member(candidates[0], "GetTitle")))
    raise RuntimeError("测试文档未清理完毕")


def main(output, source=None):
    """@brief 使用私有测试实例和新输出目录，验证真实父/子进程链路。"""
    if solidworks_processes() != {}:
        raise RuntimeError("此真机测试需要没有正在使用的 CAD 实例")
    output.mkdir(parents=True, exist_ok=False)
    report = {"status": "failed"}
    sw = None
    user_title = None
    pythoncom.CoInitialize()
    try:
        sw, _, meta = connect_solidworks(version=2026, wait_seconds=60, visible=False, return_metadata=True)
        if not meta["started_by_cad_studio"]:
            raise RuntimeError("测试实例所有权未确认")
        pid = int(get_com_member(sw, "GetProcessID"))
        if source is None:
            paths = []
            for index in range(2):
                part = new_document(sw, "part")
                with sketch(part, "Front Plane") as ref:
                    sketch_rectangle(part, 0, 0, .024 + index * .002, .014)
                    fully_define_sketch(part)
                if extrude_boss(part, ref, .008) is None:
                    raise RuntimeError("测试零件创建失败")
                path = output / f"零件{index}.sldprt"
                if not save_document(part, str(path)):
                    raise RuntimeError("测试零件保存失败")
                paths.append(path)
                sw.CloseDoc(str(get_com_member(part, "GetTitle")))
            asm = new_document(sw, "assembly")
            for index, path in enumerate(paths):
                if add_component(asm, str(path), x=index * .04, sw=sw) is None:
                    raise RuntimeError("测试组件插入失败")
            source = output / "测试装配.sldasm"
            if not save_document(asm, str(source)):
                raise RuntimeError("测试装配保存失败")
        else:
            source = source.resolve()
            asm = open_document(sw, str(source), read_only=True, silent=True, raise_on_error=True)
        user = new_document(sw, "part")
        user_title = str(get_com_member(user, "GetTitle"))
        before = {str(get_com_member(item, "GetTitle")) for item in get_com_member(sw, "GetDocuments") or []}
        with patch.object(sw_delivery, "_pywin32_pack_and_go", side_effect=RuntimeError("测试强制封送回退")):
            packed = sw_delivery.pack_and_go(asm, output / "package", include_drawings=False,
                include_simulation_results=False, include_toolbox_components=False, flatten=True, fallback_policy="blocked")
        report["pack"] = packed
        if not packed["success"] or packed["backend"] != "comtypes":
            raise RuntimeError(f"实际回退未完成原生打包: {packed['status']}; {packed.get('fallback_errors')}")
        after = {str(get_com_member(item, "GetTitle")) for item in get_com_member(sw, "GetDocuments") or []}
        if before != after or int(get_com_member(sw, "GetProcessID")) != pid or str(get_com_member(user, "GetTitle")) != user_title:
            raise RuntimeError("回退改变了父实例或用户文档清单")
        close_test_files(sw, output)
        if source.parent != output:
            close_test_files(sw, source.parent)
        reopened = open_document(sw, str(output / "package" / source.name), read_only=True, silent=True, raise_on_error=True)
        components = get_components(reopened)
        component_paths = [str(item["path"]) for item in components]
        if len(component_paths) != 2 or not all(Path(path).resolve().is_relative_to(output / "package") for path in component_paths):
            raise RuntimeError(f"打包后引用仍指向源目录: {component_paths}")
        report.update(status="pass", year=meta["actual_version"], revision=meta["actual_revision"],
            parent_proxy_alive=True, user_unsaved_document_preserved=True, document_list_unchanged=True,
            reopened_component_paths=component_paths)
    except Exception as error:
        report["error"] = f"{type(error).__name__}: {error}"
    finally:
        if sw is not None:
            try:
                close_test_files(sw, output)
                if source is not None and source.parent != output:
                    close_test_files(sw, source.parent)
                if user_title:
                    sw.CloseDoc(user_title)
                remaining = list(get_com_member(sw, "GetDocuments") or [])
                report["remaining_documents"] = len(remaining)
                if not remaining:
                    sw.ExitApp()
            except Exception as error:
                report.update(status="failed", cleanup_error=str(error))
        pythoncom.CoUninitialize()
        (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key:value for key,value in report.items() if key!='pack'}, ensure_ascii=True, indent=2))
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source", type=Path)
    args = parser.parse_args()
    raise SystemExit(main(args.output.resolve(), args.source))
