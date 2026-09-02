"""@brief 查询 CAD Studio 技能矩阵并选择最合适的语言执行后端。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

try:
    from .capabilities import (
        backend_route_snapshot,
        load_capabilities,
        operation_route_index,
        resolve_operation_backend,
    )
except ImportError:
    from capabilities import (
        backend_route_snapshot,
        load_capabilities,
        operation_route_index,
        resolve_operation_backend,
    )


def build_parser() -> argparse.ArgumentParser:
    """@brief 构造命令行参数解析器。"""
    parser = argparse.ArgumentParser(description="按 CAD 原子操作选择 Python、C#、C++ 或无头后端。")
    parser.add_argument("--operation", help="operation_routes 中的原子操作 ID。")
    parser.add_argument("--list", action="store_true", help="列出全部操作路由及后端摘要。")
    parser.add_argument("--available", action="append", default=[], help="本机可用后端 ID，可重复指定。")
    parser.add_argument("--requirement", action="append", default=[], help="已满足的加载项/许可证条件，可重复指定。")
    parser.add_argument("--solidworks-revision", help="SolidWorks Revision，例如 34.1.1。")
    parser.add_argument("--exact-api", action="store_true", help="要求原始 I* 接口语义，不接受 Automation 等价方法。")
    parser.add_argument("--manifest", type=Path, help="可选能力清单路径。")
    return parser


def route_report(args: argparse.Namespace) -> dict:
    """@brief 返回只读矩阵摘要或单个操作的后端决策。"""
    payload = load_capabilities(args.manifest)
    if args.list:
        return {
            "status": "ready",
            "summary": backend_route_snapshot(payload),
            "routes": [
                {
                    "id": route_id,
                    "label": route.get("label", route_id),
                    "candidate_backends": [item["backend"] for item in route.get("candidates", [])],
                    "blocked_reason": route.get("blocked_reason"),
                    "requires": route.get("requires", []),
                }
                for route_id, route in operation_route_index(payload).items()
            ],
        }
    if not args.operation:
        return {
            "status": "blocked",
            "error_code": "OPERATION_REQUIRED",
            "reason": "请指定 --operation，或使用 --list 查看可用路由",
        }
    return resolve_operation_backend(
        args.operation,
        available_backends=args.available or None,
        available_requirements=args.requirement,
        solidworks_revision=args.solidworks_revision,
        exact_api=args.exact_api,
        payload=payload,
    )


def main() -> int:
    """@brief 命令行入口。"""
    args = build_parser().parse_args()
    report = route_report(args)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report.get("status") == "ready" else 2


if __name__ == "__main__":
    raise SystemExit(main())
