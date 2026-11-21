"""孔创建失败的 MCP 诊断契约，不启动 CAD。"""
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "mcp-server"))
import server
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
