"""CAD Studio 多语言执行后端矩阵与确定性路由测试。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from capabilities import (  # noqa: E402
    backend_route_snapshot,
    load_capabilities,
    resolve_operation_backend,
)


def test_backend_matrix_is_valid_and_covers_multiple_languages() -> None:
    """@brief 真源必须包含 Python、C#、C++ 与无头开放格式路径。"""
    snapshot = backend_route_snapshot(load_capabilities())

    assert snapshot["backend_count"] >= 10
    assert snapshot["route_count"] >= 11
    assert {"Python", "C#", "C++", "SWBasic/VBA"} <= set(snapshot["languages"])
    assert "fillet_hold_lines_exact" in snapshot["operation_ids"]
    assert "solidworks_addin_ui_events" in snapshot["operation_ids"]


def test_addin_ui_route_prefers_in_process_csharp_host() -> None:
    """@brief 长期 UI/事件生命周期应优先托管进程内 Add-in。"""
    result = resolve_operation_backend(
        "solidworks_addin_ui_events",
        available_backends=["solidworks-csharp-addin", "solidworks-native-cpp"],
    )

    assert result["status"] == "ready"
    assert result["backend"] == "solidworks-csharp-addin"
    assert result["semantics"] == "exact_managed_addin"


def test_pointer_array_route_prefers_automation_equivalent_for_normal_workflow() -> None:
    """@brief 常规任务应优先非 I 方法，避免无理由升级到高风险 C++。"""
    result = resolve_operation_backend(
        "solidworks_pointer_array_api",
        available_backends=["solidworks-com-pywin32", "solidworks-native-cpp"],
    )

    assert result["status"] == "ready"
    assert result["backend"] == "solidworks-com-pywin32"
    assert result["semantics"] == "automation_equivalent"


def test_pointer_array_route_uses_native_cpp_for_exact_i_method_semantics() -> None:
    """@brief 明确要求原始指针接口时必须跳过 Python 和 C# PIA。"""
    result = resolve_operation_backend(
        "solidworks_pointer_array_api",
        available_backends=["solidworks-com-pywin32", "solidworks-csharp-pia", "solidworks-native-cpp"],
        exact_api=True,
    )

    assert result["status"] == "ready"
    assert result["backend"] == "solidworks-native-cpp"
    assert result["semantics"] == "exact_native"
    assert [item["accepted"] for item in result["considered"]] == [False, False, True]


def test_known_hold_line_host_revision_is_blocked_before_backend_selection() -> None:
    """@brief 已知宿主故障不能通过换语言伪装成可执行。"""
    result = resolve_operation_backend(
        "fillet_hold_lines_exact",
        available_backends=["solidworks-native-cpp"],
        solidworks_revision="34.1.1",
    )

    assert result["status"] == "blocked"
    assert result["error_code"] == "KNOWN_HOST_REVISION_BLOCKER"
    assert "solidworks-swbasic" in result["diagnostic_backends"]
    assert "solidworks-csharp-pia" in result["diagnostic_backends"]


def test_language_switch_cannot_replace_missing_license_or_addin() -> None:
    """@brief Routing 缺失加载项/许可证必须保持 blocked。"""
    result = resolve_operation_backend(
        "solidworks_routing_native_authoring",
        available_backends=["solidworks-com-pywin32", "solidworks-csharp-pia"],
    )

    assert result["status"] == "blocked"
    assert result["error_code"] == "MISSING_RUNTIME_REQUIREMENT"
    assert result["missing_requirements"] == ["SolidWorks Routing 加载项", "有效许可证"]


def test_missing_api_data_has_no_fake_language_fallback() -> None:
    """@brief API 不提供精确包围盒时不能假造 C# 或 C++ 后端。"""
    result = resolve_operation_backend("drawing_exact_text_bounds")

    assert result["status"] == "blocked"
    assert result["error_code"] == "NO_LANGUAGE_SUBSTITUTION"
    assert "换语言不能" in result["reason"]


def test_router_does_not_assume_catalog_backends_are_installed() -> None:
    """@brief 未提供本机探测结果时不能把清单里的候选误当作可用。"""
    result = resolve_operation_backend("solidworks_standard_automation")

    assert result["status"] == "unavailable"
    assert result["error_code"] == "NO_COMPATIBLE_BACKEND_AVAILABLE"
    assert all(item["reason"] == "运行时不可用" for item in result["considered"])


def test_invalid_backend_reference_is_rejected(tmp_path: Path) -> None:
    """@brief 清单校验必须阻止拼写错误的后端悄悄进入路由。"""
    payload = json.loads((ROOT / "capabilities.yaml").read_text(encoding="utf-8"))
    payload["operation_routes"][0]["candidates"][0]["backend"] = "missing-backend"
    manifest = tmp_path / "capabilities.yaml"
    manifest.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(ValueError, match="未知后端"):
        load_capabilities(manifest)
