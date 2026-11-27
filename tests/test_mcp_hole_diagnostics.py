"""孔创建失败的 MCP 诊断契约，不启动 CAD。"""
import json
from pathlib import Path
import sys
from types import SimpleNamespace

from pydantic import ValidationError
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "mcp-server"))
import server
from scripts.sw_connect import get_com_member, mm
from scripts.sw_hole_features import HoleFeatureCreationError


def test_hole_creation_error_remains_actionable_and_not_retryable():
    diagnostics = {"operation": "FeatureCut4", "state": "after_failed_cut",
                   "selection_count": 0, "solid_body_count": 1}
    payload = json.loads(server._tool_error(HoleFeatureCreationError("H_Reopen", diagnostics)))
    assert payload["status"] == "error"
    assert payload["error_code"] == "SW_HOLE_NOT_CREATED"
    assert payload["retryable"] is False
    assert payload["diagnostics"] == diagnostics
    assert "H_Reopen" in payload["message"]
    assert "do not automatically retry" in payload["suggestion"]


@pytest.mark.parametrize("extra, expected", [({}, {}), ({"reverse_direction": True}, {"reverse_direction": True})])
def test_mcp_through_hole_passes_an_explicit_direction_only_when_requested(monkeypatch, extra, expected):
    """省略方向仍走旧的通孔调用，显式反向转发给通孔封装。"""
    model = SimpleNamespace(ForceRebuild3=lambda _: True)
    monkeypatch.setattr(server, "mm", mm, raising=False)
    monkeypatch.setattr(server, "get_com_member", get_com_member, raising=False)
    monkeypatch.setattr(server, "_active_part_required", lambda: (None, model))
    monkeypatch.setattr(server, "_model_summary", lambda _: {})
    monkeypatch.setattr(server, "_run_locked", lambda op, _: json.dumps(op()))

    def through(_model, center, diameter, plane_name, name, **options):
        assert options == expected
        return {"feature_kind": "through"}

    monkeypatch.setattr(server, "create_through_hole", through, raising=False)
    params = server.SolidWorksHoleFeatureInput(feature_kind="through", **extra)
    result = json.loads(server.solidworks_create_hole_feature(params))
    assert result["status"] == "ok"


@pytest.mark.parametrize("kind", ["blind", "counterbore", "countersink", "semicircular_slot"])
def test_mcp_reverse_direction_rejected_for_other_feature_kinds(kind):
    """不支持反向的孔槽在解析输入时即拒绝，避免留下无效几何。"""
    with pytest.raises(ValidationError, match="reverse_direction.*through"):
        server.SolidWorksHoleFeatureInput(feature_kind=kind, reverse_direction=True)
