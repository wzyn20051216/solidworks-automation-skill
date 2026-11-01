"""对自建四孔板验证自动落图的真实缺失目标/错误尺寸失败隔离。"""
import argparse
from copy import deepcopy
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from solidworks_gdt_generation_live import specification
from scripts.sw_connect import get_com_member
from scripts.sw_drawing_package import generate_package
from scripts.sw_rename_copy import _open_checked, _sha256
from scripts.sw_session import SolidWorksSession


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True, type=Path, help="仅使用 generation_live 自建四孔板")
    source = parser.parse_args().source.resolve(strict=True)
    root = Path(tempfile.mkdtemp(prefix="sw_drawing_failures_"))
    digest = _sha256(source)
    with SolidWorksSession(version=2026, visible=True) as session:
        _open_checked(session, source)
        def documents():
            return sorted((str(get_com_member(doc, "GetPathName")), str(get_com_member(doc, "GetTitle"))) for doc in session._documents())
        baseline = documents()
        for name in ("missing_target", "wrong_value"):
            spec = deepcopy(specification(source))
            if name == "missing_target":
                spec["requiredDimensions"][2]["target"]["radiusMm"] = 7
            else:
                spec["requiredDimensions"][0]["valueMm"] = 81
            result = generate_package(spec, root / name)
            assert result["status"] == "blocked" and not result["outputs"], result
            assert "目标不能唯一确认" in result["message"] if name == "missing_target" else "实际数值与要求不一致" in result["message"]
            assert documents() == baseline, "失败后遗留本轮自有文档或改变用户文档集合"
            assert _sha256(source) == digest
            print("PASS", name, result["message"], flush=True)
    print("failure isolation PASS", root, flush=True)


if __name__ == "__main__":
    main()
