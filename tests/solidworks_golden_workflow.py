"""@brief 注册式真实 Golden 入口；只分派已审核用例，不接受任意脚本或后端路径。"""
import argparse
import importlib
from golden_workflow_support import CASE_REGISTRY


def main(argv=None):
    """@brief 共用用例选择；保留具体用例的严格终态、证据和退出码规则。"""
    parser = argparse.ArgumentParser(description=__doc__, add_help=False)
    parser.add_argument("--case", choices=sorted(CASE_REGISTRY), required=True)
    args, remaining = parser.parse_known_args(argv)
    return importlib.import_module(CASE_REGISTRY[args.case]["module"]).main(remaining)


if __name__ == "__main__":
    raise SystemExit(main())
