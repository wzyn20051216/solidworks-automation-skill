from scripts.release_check import find_bundled_skill_drift, run_release_check


def test_release_check_passes_current_tree():
    result = run_release_check()
    assert result["status"] == "pass"
    assert result["capabilities"] >= 10
    assert result["bundled_skill_files"] >= 1


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
