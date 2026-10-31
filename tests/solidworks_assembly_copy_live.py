"""对带配合的多层测试源运行装配体副本执行器；需要 SolidWorks 2026。"""
from pathlib import Path
import argparse
import json
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.sw_assembly_rename import copy_assembly
from scripts.sw_session import SolidWorksSession


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    args = parser.parse_args()
    root = Path(args.root).resolve(strict=True)
    files = sorted(root.parent.glob("*.sld*"))
    files = [p for p in files if p.suffix.casefold() in (".sldasm", ".sldprt") and not p.name.startswith("~$")]
    plans = [{"source": str(path), "new_name": "verified_" + path.name, "status": "planned"} for path in files]
    output = Path(tempfile.mkdtemp(prefix="sw_assembly_copy_test_")) / "delivery"
    # 持有同一个会话，避免正向测试退出新实例后反例立即启动时碰到进程退出竞态。
    with SolidWorksSession(version=2026, visible=True):
        result = copy_assembly(root, plans, output)
        print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
        if result["status"] != "review_required" or len(result["outputs"]) != len(files):
            raise RuntimeError("装配体副本验收未通过")
        part = next(path for path in files if path.suffix.casefold() == ".sldprt")
        incomplete = [row for row in plans if Path(row["source"]) != part]
        blocked_dir = Path(tempfile.mkdtemp(prefix="sw_assembly_block_test_")) / "delivery"
        blocked = copy_assembly(root, incomplete, blocked_dir)
        if blocked["status"] != "blocked" or "引用不在计划中" not in str(blocked["error"]) or blocked["outputs"]:
            raise AssertionError(f"缺失依赖未被阻断: {blocked}")
        if list(blocked_dir.glob("*.sld*")):
            raise AssertionError("引用闭包验证失败时不应创建模型副本")
        print("missing dependency correctly blocked", flush=True)


if __name__ == "__main__":
    main()
