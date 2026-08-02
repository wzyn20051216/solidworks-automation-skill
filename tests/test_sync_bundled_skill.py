from pathlib import Path

from scripts.sync_bundled_skill import collect_runtime_files, sync_bundled_skill


def _create_minimal_source(root: Path) -> None:
    """@brief 创建满足同步器清单的最小测试仓库。"""
    from scripts.sync_bundled_skill import RUNTIME_FILES, RUNTIME_ROOTS, TOP_LEVEL_FILES

    for relative_name in (*TOP_LEVEL_FILES, *RUNTIME_FILES):
        path = root / relative_name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(relative_name, encoding="utf-8")
    for relative_root in RUNTIME_ROOTS:
        path = root / relative_root / "runtime.txt"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(relative_root, encoding="utf-8")


def test_collect_runtime_files_excludes_generated_files(tmp_path):
    """@brief 缓存和构建目录不得进入桌面安装包。"""
    root = tmp_path / "repo"
    _create_minimal_source(root)
    generated = root / "scripts" / "__pycache__" / "module.pyc"
    generated.parent.mkdir(parents=True)
    generated.write_bytes(b"bytecode")

    files = collect_runtime_files(root)

    assert Path("scripts/runtime.txt") in files
    assert Path("scripts/__pycache__/module.pyc") not in files


def test_sync_bundled_skill_copies_sources_and_prunes_stale_file(tmp_path):
    """@brief 同步结果必须可复现，陈旧副本不能继续进入发布包。"""
    root = tmp_path / "repo"
    _create_minimal_source(root)
    target = root / "apps/workbench-ui/src-tauri/resources/skill"
    stale = target / "scripts" / "stale.py"
    stale.parent.mkdir(parents=True, exist_ok=True)
    stale.write_text("stale", encoding="utf-8")

    result = sync_bundled_skill(root, target)

    assert result["status"] == "pass"
    assert "scripts/stale.py" in result["pruned"]
    assert not stale.exists()
    assert (target / "SKILL.md").read_text(encoding="utf-8") == "SKILL.md"
