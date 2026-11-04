"""技能发布包必须可独立导入、来源明确、无垃圾文件且能检测篡改。"""
import hashlib
import json
from pathlib import Path
import zipfile
import shutil

import pytest

from scripts.build_skill_release import PREFIX, EXTRA_FILES, build_skill_archive, verify_skill_archive, verify_desktop_skill, verify_installed_skill
from scripts.sync_bundled_skill import TOP_LEVEL_FILES, RUNTIME_FILES, RUNTIME_ROOTS, collect_runtime_files


def source_tree(root):
    for name in RUNTIME_ROOTS:
        (root / name).mkdir(parents=True, exist_ok=True)
    for name in (*TOP_LEVEL_FILES, *RUNTIME_FILES, *EXTRA_FILES):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("release fixture", encoding="utf-8")
    (root / "package.json").write_text(json.dumps({"name": "solidworks-automation-skill", "version": "2.0.1"}), encoding="utf-8")
    config = root / "apps/workbench-ui/src-tauri/tauri.conf.json"
    config.parent.mkdir(parents=True)
    config.write_text(json.dumps({"version": "2.0.1"}), encoding="utf-8")
    (root / "scripts/sw_edge_select.py").write_text("# ICurve fix\n", encoding="utf-8")
    (root / "dotnet/Host.cs").write_text("// native host fixture", encoding="utf-8")
    (root / "profiles/drc/part.json").write_text("{}", encoding="utf-8")
    (root / "scripts/__pycache__").mkdir()
    (root / "scripts/__pycache__/cached.pyc").write_bytes(b"cache")
    (root / ".git").mkdir()
    (root / ".git/config").write_text("private fixture", encoding="utf-8")


def test_release_archive_contains_runtime_and_reproducible_manifest(tmp_path):
    root = tmp_path / "source"
    source_tree(root)
    first, second = tmp_path / "first.zip", tmp_path / "second.zip"
    for output in (first, second):
        assert build_skill_archive(root, output, source_commit="a"*40)["status"] == "pass"
    assert hashlib.sha256(first.read_bytes()).digest() == hashlib.sha256(second.read_bytes()).digest()
    with zipfile.ZipFile(first) as archive:
        names = archive.namelist()
        assert PREFIX + "SKILL.md" in names
        assert PREFIX + "install.js" in names
        assert PREFIX + "LICENSE" in names
        assert archive.read(PREFIX + "scripts/sw_edge_select.py") == (root / "scripts/sw_edge_select.py").read_bytes()
        assert not any(".git/" in name or "__pycache__" in name for name in names)
    with pytest.raises(FileExistsError):
        build_skill_archive(root, first, source_commit="a"*40)


@pytest.mark.parametrize("fault", ["changed", "missing", "extra", "wrong_commit", "wrong_version"])
def test_archive_verification_rejects_invalid_delivery(tmp_path, fault):
    root = tmp_path / "source"
    source_tree(root)
    original = tmp_path / "original.zip"
    build_skill_archive(root, original, source_commit="a"*40)
    with zipfile.ZipFile(original) as archive:
        payload = {name: archive.read(name) for name in archive.namelist()}
    if fault == "changed":
        payload[PREFIX + "scripts/sw_edge_select.py"] = b"old code"
    elif fault == "missing":
        del payload[PREFIX + "SKILL.md"]
    elif fault == "extra":
        payload[PREFIX + "../outside.txt"] = b"unexpected"
    tampered = tmp_path / "tampered.zip"
    with zipfile.ZipFile(tampered, "w") as archive:
        for name, data in payload.items():
            archive.writestr(name, data)
    with pytest.raises(ValueError):
        verify_skill_archive(tampered, expected_version="2.0.2" if fault == "wrong_version" else "2.0.1",
                             expected_commit="b"*40 if fault == "wrong_commit" else "a"*40)


def test_release_rejects_mixed_skill_and_desktop_versions(tmp_path):
    source_tree(tmp_path)
    (tmp_path / "package.json").write_text('{"version":"2.0.0"}', encoding="utf-8")
    with pytest.raises(ValueError, match="版本"):
        build_skill_archive(tmp_path, tmp_path / "mismatch.zip", source_commit="a"*40)


def test_archive_does_not_follow_sources_outside_repository(tmp_path, monkeypatch):
    root = tmp_path / "source"
    source_tree(root)
    outside = tmp_path / "private.py"
    outside.write_text("private fixture", encoding="utf-8")
    monkeypatch.setattr("scripts.build_skill_release.collect_runtime_files", lambda _: {Path("scripts/private.py"): outside})
    with pytest.raises(ValueError, match="越出仓库"):
        build_skill_archive(root, tmp_path / "outside.zip", source_commit="a"*40)


@pytest.mark.parametrize("fault", [None, "missing_host", "stale_script", "missing_profile"])
def test_desktop_package_must_embed_the_same_complete_runtime(tmp_path, fault):
    root = tmp_path / "source"
    source_tree(root)
    skill = tmp_path / "skill.zip"
    build_skill_archive(root, skill, source_commit="a"*40)
    desktop = tmp_path / "desktop.zip"
    with zipfile.ZipFile(desktop, "w") as archive:
        for relative, source in collect_runtime_files(root).items():
            if (fault == "missing_host" and relative.as_posix() == "dotnet/Host.cs"
                    or fault == "missing_profile" and relative.as_posix() == "profiles/drc/part.json"):
                continue
            data = b"old code" if fault == "stale_script" and relative.as_posix() == "scripts/sw_edge_select.py" else source.read_bytes()
            archive.writestr("skill/" + relative.as_posix(), data)
    if fault is None:
        assert verify_desktop_skill(skill, desktop, root)["status"] == "pass"
    else:
        with pytest.raises(ValueError, match="不一致"):
            verify_desktop_skill(skill, desktop, root)


def test_actual_installed_files_are_verified(tmp_path):
    root = tmp_path / "source"
    source_tree(root)
    skill = tmp_path / "skill.zip"
    build_skill_archive(root, skill, source_commit="a"*40)
    installed = tmp_path / "installed-skill"
    for relative, source in collect_runtime_files(root).items():
        target = installed / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    assert verify_installed_skill(skill, installed, root)["status"] == "pass"
    (installed / "scripts/sw_edge_select.py").write_text("old version", encoding="utf-8")
    with pytest.raises(ValueError, match="内容不一致"):
        verify_installed_skill(skill, installed, root)
