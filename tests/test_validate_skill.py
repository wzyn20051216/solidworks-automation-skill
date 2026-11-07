"""validate_skill.py 的回归测试。

重点覆盖 2026-10-27 修复的缺陷：`check_json_files()` 曾把黄金工作流数量写死为 10，
新增 Golden 用例后 `skill-mcp-release.yml` 的 "Validate Skill" 步骤必然失败，
而该步骤属于必需检查 `test-and-build` 的一部分。

修复后改为：结构不变量（非空、id 唯一）+ 与 `tests/evals/baseline.json.workflow_count` 交叉一致。
本文件锁定这一行为，防止再次退化为魔法数字。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import validate_skill  # noqa: E402


def test_check_json_files_passes_on_current_tree():
    """@brief 当前工作树必须通过静态校验，且返回被检查的 Schema 数量。"""
    count = validate_skill.check_json_files()
    assert isinstance(count, int)
    assert count > 0


def test_golden_workflow_count_matches_eval_baseline():
    """@brief 黄金工作流数量必须与评估基线声明一致（不允许单边改动）。"""
    manifest = json.loads((ROOT / "golden-workflows.yaml").read_text(encoding="utf-8"))
    baseline = json.loads((ROOT / "tests/evals/baseline.json").read_text(encoding="utf-8"))
    assert len(manifest["workflows"]) == baseline["workflow_count"]


def test_check_json_files_rejects_baseline_count_mismatch(monkeypatch):
    """@brief 基线计数被单独改动时必须报错，而不是静默通过。"""
    real_read_text = Path.read_text

    def fake_read_text(self, *args, **kwargs):
        text = real_read_text(self, *args, **kwargs)
        if self.name == "baseline.json":
            payload = json.loads(text)
            payload["workflow_count"] = payload.get("workflow_count", 0) + 1
            return json.dumps(payload)
        return text

    monkeypatch.setattr(Path, "read_text", fake_read_text)

    with pytest.raises(AssertionError, match="workflow_count"):
        validate_skill.check_json_files()


def test_check_json_files_rejects_duplicate_workflow_id(monkeypatch):
    """@brief 重复的 workflow id 必须被拒绝。"""
    real_read_text = Path.read_text

    def fake_read_text(self, *args, **kwargs):
        text = real_read_text(self, *args, **kwargs)
        if self.name == "golden-workflows.yaml":
            payload = json.loads(text)
            payload["workflows"][1]["id"] = payload["workflows"][0]["id"]
            return json.dumps(payload)
        return text

    monkeypatch.setattr(Path, "read_text", fake_read_text)

    with pytest.raises(AssertionError, match="唯一"):
        validate_skill.check_json_files()
