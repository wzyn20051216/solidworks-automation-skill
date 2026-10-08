"""@brief 实际下载入口、提交锁定与缓存写入失败分支。"""
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "subskills/solidworks-fillet-chamfer-cnc/scripts/verify_open_source_complex_case.py"
spec = importlib.util.spec_from_file_location("pinned_case_boundary", SCRIPT)
case_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(case_module)


def fixture():
    """@brief 小型内容声明，不当作真实 STEP。"""
    return {"download_url":"https://raw.githubusercontent.com/owner/repo/" + "a"*40 + "/case.step",
        "commit":"a"*40,"sha256":hashlib.sha256(b"fixture").hexdigest(),"license":"fixture","attribution":"fixture"}


@pytest.mark.parametrize("url", ["https://raw.githubusercontent.com/owner/repo/main/case.step?commit=" + "a"*40,
    "https://raw.githubusercontent.com/owner/repo/main/" + "a"*40 + ".step",
    "https://raw.githubusercontent.com/owner/repo/" + "a"*40 + "/%2e%2e/case.step",
    "https://127.0.0.1/" + "a"*40])
def test_request_cannot_bypass_manifest_validation(monkeypatch, tmp_path, url):
    payload = {**fixture(), "download_url":url}
    called = []
    monkeypatch.setattr(case_module, "read_https_response", lambda *_args, **_kwargs: called.append(True))
    with pytest.raises(ValueError):
        case_module.fetch_pinned_source(payload, tmp_path / "source.step")
    assert called == []


def test_invalid_content_is_not_cached(monkeypatch, tmp_path):
    monkeypatch.setattr(case_module, "read_https_response", lambda *_args, **_kwargs: b"tampered")
    target = tmp_path / "source.step"
    with pytest.raises(RuntimeError, match="哈希不匹配"):
        case_module.fetch_pinned_source(fixture(), target)
    assert not target.exists()


def test_correct_content_and_existing_cache_use_same_hash_boundary(monkeypatch, tmp_path):
    monkeypatch.setattr(case_module, "read_https_response", lambda *_args, **_kwargs: b"fixture")
    target = tmp_path / "source.step"
    assert case_module.fetch_pinned_source(fixture(), target)["source"] == "network"
    assert case_module.fetch_pinned_source(fixture(), target)["source"] == "cache"
    assert target.read_bytes() == b"fixture"


def test_existing_real_case_is_still_valid():
    payload = case_module.load_case(SCRIPT.parents[1] / "examples/open_source_corner_bracket_case.json")
    assert payload["commit"] == "b342740f9b9ecc63dab5855bab3b9fdf3e3e3488"
