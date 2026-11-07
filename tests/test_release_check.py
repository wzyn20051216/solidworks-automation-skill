import json

import pytest

from scripts.release_check import BUNDLED_SKILL, find_bundled_skill_drift, run_release_check


def test_release_check_passes_current_tree():
    """@brief 发布门禁在当前工作树上必须通过。

    桌面内嵌 Skill 目录被 .gitignore 排除，由 scripts/sync_bundled_skill.py 生成。
    CI 会先执行生成步骤；本地全新克隆时该目录不存在，此时跳过，而不是把"尚未
    生成"误报成发布缺陷。漂移检测本身的逻辑由下面几个用例独立覆盖。
    """
    if not BUNDLED_SKILL.is_dir():
        pytest.skip(
            "桌面内嵌 Skill 尚未生成；先运行 python scripts/sync_bundled_skill.py"
        )

    result = run_release_check()
    assert result["status"] == "pass"
    assert result["capabilities"] >= 10
    assert result["bundled_skill_files"] >= 1


def test_release_check_still_validates_versions_without_bundle():
    """@brief 内嵌目录缺失时，版本一致性与能力清单校验仍必须执行。

    否则本地开发会误以为"跳过了发布门禁＝通过"。
    """
    from scripts.release_check import _version
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    package = json.loads((root / "package.json").read_text(encoding="utf-8"))
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    core_versions = {
        package["version"],
        manifest["version"],
        _version(root / "pyproject.toml", r'(?m)^version\s*=\s*"([^"]+)"'),
        _version(root / "setup.py", r'\bversion="([^"]+)"'),
        _version(root / "uv.lock", r'name = "solidworks-automation-skill"\s+version = "([^"]+)"'),
    }
    desktop_versions = {
        _version(root / "apps/workbench-ui/package.json", r'"version"\s*:\s*"([^"]+)"'),
        _version(root / "apps/workbench-ui/src-tauri/tauri.conf.json", r'"version"\s*:\s*"([^"]+)"'),
        _version(root / "apps/workbench-ui/src-tauri/Cargo.toml", r'(?m)^version\s*=\s*"([^"]+)"'),
        _version(root / "apps/workbench-ui/src/App.tsx", r'const APP_VERSION\s*=\s*"([^"]+)"'),
    }

    assert len(core_versions) == 1
    assert len(desktop_versions) == 1


def test_find_bundled_skill_drift_detects_changed_and_missing_sources(tmp_path):
    """@brief 内嵌文件内容漂移或没有根源文件时必须阻止发布。"""
    root = tmp_path / "root"
    bundle = tmp_path / "bundle"
    (root / "scripts").mkdir(parents=True)
    (bundle / "scripts").mkdir(parents=True)
    (root / "scripts" / "same.py").write_text("same", encoding="utf-8")
    (bundle / "scripts" / "same.py").write_text("same", encoding="utf-8")
    assert find_bundled_skill_drift(root, bundle) == []

    (bundle / "scripts" / "same.py").write_text("changed", encoding="utf-8")
    (bundle / "scripts" / "orphan.py").write_text("orphan", encoding="utf-8")

    assert find_bundled_skill_drift(root, bundle) == [
        "missing-source:scripts/orphan.py",
        "scripts/same.py",
    ]


def test_find_bundled_skill_drift_detects_expected_file_missing_from_bundle(tmp_path):
    """@brief 根 Skill 预期文件没有进入桌面快照时必须阻止发布。"""
    root = tmp_path / "root"
    bundle = tmp_path / "bundle"
    root.mkdir()
    bundle.mkdir()
    (root / "requirements-pdf.txt").write_text("PyMuPDF", encoding="utf-8")
    assert find_bundled_skill_drift(root, bundle, ["requirements-pdf.txt"]) == [
        "missing-bundle:requirements-pdf.txt",
    ]


def test_find_bundled_skill_drift_handles_file_disappearing_during_compare(tmp_path, monkeypatch):
    """@brief 打包目录重建竞态应稳定返回缺失，而不是抛 FileNotFoundError。"""
    root = tmp_path / "root"
    bundle = tmp_path / "bundle"
    root.mkdir()
    bundle.mkdir()
    (root / "README.md").write_text("root", encoding="utf-8")
    (bundle / "README.md").write_text("bundle", encoding="utf-8")

    def disappearing_compare(*_args, **_kwargs):
        raise FileNotFoundError("staging rebuilt")

    monkeypatch.setattr("scripts.release_check.cmp", disappearing_compare)
    assert find_bundled_skill_drift(root, bundle) == ["missing-bundle:README.md"]
