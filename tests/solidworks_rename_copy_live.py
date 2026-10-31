"""手动真机回归：属性预览、独立零件复制、哈希与文档归属。"""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.sw_connect import get_com_member
from scripts.sw_document_data import set_custom_properties
from scripts.sw_file_rename import collect_entries, plan_renames
from scripts.sw_part import extrude_boss, sketch, sketch_rectangle
from scripts.sw_rename_copy import _sha256, copy_batch
from scripts.sw_session import SolidWorksSession


def main():
    root = Path(tempfile.mkdtemp(prefix="sw_pr36_copy_live_"))
    source = root / "source"
    source.mkdir()
    target = root / "copies"
    with SolidWorksSession(version=2026, visible=True) as session:
        before = [str(get_com_member(doc, "GetTitle") or "") for doc in session._documents()]
        paths = []
        held = []
        for index in range(2):
            model = session.new_part()
            with sketch(model, "Front Plane") as ref:
                sketch_rectangle(model, 0, 0, .02 + index * .004, .012)
            if extrude_boss(model, ref, .006) is None:
                raise RuntimeError("测试零件拉伸失败")
            if not set_custom_properties(model, {"part_no": f"COPY{index}"})["success"]:
                raise RuntimeError("测试属性写入失败")
            path = source / f"part{index}.sldprt"
            if not session.save(model, str(path)):
                raise RuntimeError("测试零件保存失败")
            paths.append(path)
            held.append(model)
        hashes = {_sha256(path) for path in paths}
        print("测试目录条目:", sorted(path.name for path in source.iterdir()), flush=True)
        with SolidWorksSession(version=2026, visible=True) as reader:
            entries = collect_entries(reader, source, ["part_no"])
        plans = plan_renames(entries, "{part_no}")
        if len(plans) != 2 or any(plan["status"] != "planned" for plan in plans):
            raise AssertionError(f"属性预览不符: {plans}")
        plan_path = root / "plan.json"
        plan_path.write_text(json.dumps({"plans": plans}, ensure_ascii=False), encoding="utf-8")
        held_paths = [str(get_com_member(doc, "GetPathName")) for doc in held]
        if not all(path in [str(get_com_member(doc, "GetPathName") or "") for doc in session._documents()] for path in held_paths):
            raise AssertionError("预览关闭了已打开的测试文档")
        result = subprocess.run([sys.executable, str(ROOT / "scripts/sw_rename_copy.py"), "--plan", str(plan_path),
                                 "--output-dir", str(target)], capture_output=True, text=True, encoding="utf-8",
                                errors="replace", timeout=120)
        if result.returncode != 2:
            raise RuntimeError(f"复制命令失败: {result.returncode}, {result.stdout}, {result.stderr}")
        manifest = json.loads((target / "copy-manifest.json").read_text(encoding="utf-8"))
        if manifest["status"] != "review_required" or len(manifest["outputs"]) != 2:
            raise AssertionError(f"清单异常: {manifest}")
        for item in manifest["outputs"]:
            if _sha256(Path(item["source"])) != _sha256(Path(item["path"])):
                raise AssertionError("单个副本与对应源文件不一致")
        if {_sha256(path) for path in paths} != hashes or {_sha256(target / f"COPY{i}.sldprt") for i in range(2)} != hashes:
            raise AssertionError("原文件或副本的字节内容不符")
        if not all(path in [str(get_com_member(doc, "GetPathName") or "") for doc in session._documents()] for path in held_paths):
            raise AssertionError("复制关闭了已打开的测试文档")
        # 派生零件保留源零件引用；必须在复制前被阻断。
        configuration = get_com_member(held[0], "GetConfigurationNames")[0]
        derived = session.new_part()
        if derived.InsertPart3(str(paths[0]), 1, str(configuration)) is None:  # swInsertPartImportSolids
            raise RuntimeError("无法创建带外部引用的测试零件")
        derived_path = source / "derived.sldprt"
        if not session.save(derived, str(derived_path)):
            raise RuntimeError("派生测试零件保存失败")
        derived_hash = _sha256(derived_path)
        blocked = copy_batch([{"source": str(derived_path), "new_name": "derived-copy.sldprt", "status": "planned"}], root / "blocked")
        if blocked["status"] != "blocked" or "外部引用" not in str(blocked["error"]) or blocked["outputs"]:
            raise AssertionError(f"带外部引用的零件未正确阻断: {blocked}")
        if _sha256(derived_path) != derived_hash:
            raise AssertionError("被阻断零件发生变化")
        session.close(model=derived)
        for model in held:
            session.close(model=model)
        after = [str(get_com_member(doc, "GetTitle") or "") for doc in session._documents()]
        if any(title not in after for title in before):
            raise AssertionError("用户已有文档消失")
    print(json.dumps({"status": "review_required", "geometry_verification": "pass", "directory": str(root),
                      "outputs": len(manifest["outputs"]), "source_hashes_preserved": True,
                      "external_reference_blocked": True, "opened_test_document_preserved": True,
                      "existing_documents_preserved": len(before)}, ensure_ascii=True))


if __name__ == "__main__":
    main()
