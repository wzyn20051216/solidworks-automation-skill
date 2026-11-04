"""构建可独立导入的技能 ZIP，并验证版本、来源提交及逐文件哈希。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
import zipfile

try:
    from .sync_bundled_skill import ROOT, collect_runtime_files
except ImportError:
    from sync_bundled_skill import ROOT, collect_runtime_files

PREFIX = "solidworks-automation/"
MANIFEST = "RELEASE-MANIFEST.json"
EXTRA_FILES = ("LICENSE", "install.js", "package.json", "docs/CAD_STUDIO_USER_MANUAL.md")


def release_version(root: Path) -> str:
    """技能包和桌面程序使用同一个发布版本。"""
    skill = json.loads((root / "package.json").read_text(encoding="utf-8"))["version"]
    desktop = json.loads((root / "apps/workbench-ui/src-tauri/tauri.conf.json").read_text(encoding="utf-8"))["version"]
    if skill != desktop or not re.fullmatch(r"\d+\.\d+\.\d+", skill):
        raise ValueError("技能包与桌面程序版本不一致或无效")
    return skill


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _entry_name(relative: str) -> str:
    path = PurePosixPath(relative)
    if path.is_absolute() or not path.parts or any(part.casefold() in {"..", ".git"} for part in path.parts) or ":" in relative or "\\" in relative:
        raise ValueError(f"不安全的技能包路径: {relative}")
    return PREFIX + relative


def build_skill_archive(root: Path, output: Path, *, source_commit: str | None = None) -> dict:
    root = root.resolve()
    version = release_version(root)
    if source_commit is None:
        source_commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    if not re.fullmatch(r"[0-9a-f]{40}", source_commit):
        raise ValueError("发布来源必须是完整 Git 提交 SHA")
    files = collect_runtime_files(root)
    files.update({Path(name): root / name for name in EXTRA_FILES})
    payload = {}
    for relative, source in sorted(files.items()):
        _entry_name(relative.as_posix())
        if not source.resolve(strict=True).is_relative_to(root):
            raise ValueError(f"技能包源文件越出仓库: {relative}")
        payload[relative.as_posix()] = source.read_bytes()
    manifest = {"schemaVersion": "1.0", "version": version, "sourceCommit": source_commit,
                "files": {name: {"sha256": _digest(data), "sizeBytes": len(data)} for name, data in payload.items()}}
    payload[MANIFEST] = (json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    # 独占创建，禁止覆盖既有交付物；固定 ZIP 元数据便于同一源文件集复现。
    with zipfile.ZipFile(output, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, data in sorted(payload.items()):
            info = zipfile.ZipInfo(_entry_name(name), date_time=(2020, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            archive.writestr(info, data)
    return verify_skill_archive(output, expected_version=version, expected_commit=source_commit)


def verify_skill_archive(path: Path, *, expected_version: str | None = None, expected_commit: str | None = None) -> dict:
    """只在 ZIP 内回读，不向文件系统提取不可信归档路径。"""
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)):
            raise ValueError("技能包包含重复文件")
        manifest = json.loads(archive.read(PREFIX + MANIFEST))
        version, commit = manifest["version"], manifest["sourceCommit"]
        if manifest.get("schemaVersion") != "1.0" or not re.fullmatch(r"\d+\.\d+\.\d+", version) or not re.fullmatch(r"[0-9a-f]{40}", commit):
            raise ValueError("技能包清单格式无效")
        if expected_version is not None and version != expected_version:
            raise ValueError("技能包版本不匹配")
        if expected_commit is not None and commit != expected_commit:
            raise ValueError("技能包来源提交不匹配")
        expected_names = {_entry_name(name) for name in manifest["files"]} | {PREFIX + MANIFEST}
        if set(names) != expected_names:
            raise ValueError("技能包文件清单不完整或包含额外文件")
        for name, record in manifest["files"].items():
            data = archive.read(_entry_name(name))
            if _digest(data) != record["sha256"] or len(data) != record["sizeBytes"]:
                raise ValueError(f"技能包文件校验失败: {name}")
        package = json.loads(archive.read(PREFIX + "package.json"))
        if package["version"] != version:
            raise ValueError("技能包入口版本与清单不一致")
    return {"status": "pass", "version": version, "sourceCommit": commit, "files": len(manifest["files"])}


def verify_desktop_skill(skill_archive: Path, desktop_archive: Path, root: Path = ROOT) -> dict:
    """逐文件核对桌面内嵌技能，防止二次复制漏目录或保留旧脚本。"""
    runtime = collect_runtime_files(root)
    with zipfile.ZipFile(skill_archive) as skill, zipfile.ZipFile(desktop_archive) as desktop:
        files = [name for name in desktop.namelist() if not name.endswith(("/", "\\"))]
        paths = {name.replace("\\", "/"): name for name in files}
        if len(paths) != len(files):
            raise ValueError("桌面包包含重复文件")
        for name in paths:
            _entry_name(name)
        embedded = {name for name in paths if name.startswith("skill/")}
        expected = {"skill/" + path.as_posix() for path in runtime}
        if embedded != expected:
            raise ValueError("桌面内嵌技能文件集与发布源不一致")
        for path, source in runtime.items():
            relative = path.as_posix()
            data = desktop.read(paths["skill/" + relative])
            if data != skill.read(PREFIX + relative) or data != source.read_bytes():
                raise ValueError(f"桌面内嵌技能内容不一致: {relative}")
    return {"status": "pass", "desktopRuntimeFiles": len(runtime)}


def verify_installed_skill(skill_archive: Path, installed: Path, root: Path = ROOT) -> dict:
    """核对实际安装目录，避免安装器漏装或混入旧版技能文件。"""
    runtime = collect_runtime_files(root)
    installed = installed.resolve(strict=True)
    actual = {path.relative_to(installed).as_posix(): path for path in installed.rglob("*") if path.is_file()}
    if set(actual) != {path.as_posix() for path in runtime}:
        raise ValueError("安装后的技能文件集不一致")
    with zipfile.ZipFile(skill_archive) as skill:
        for relative, source in runtime.items():
            path = actual[relative.as_posix()]
            if not path.resolve().is_relative_to(installed):
                raise ValueError("安装后的技能文件越出目标目录")
            if path.read_bytes() != skill.read(PREFIX + relative.as_posix()) or path.read_bytes() != source.read_bytes():
                raise ValueError(f"安装后的技能内容不一致: {relative}")
    return {"status": "pass", "installedRuntimeFiles": len(runtime)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--verify", type=Path)
    parser.add_argument("--version")
    parser.add_argument("--expected-commit")
    parser.add_argument("--desktop-archive", type=Path)
    parser.add_argument("--installed-skill", type=Path)
    args = parser.parse_args()
    if args.verify:
        result = verify_skill_archive(args.verify, expected_version=args.version, expected_commit=args.expected_commit)
        if args.desktop_archive:
            result.update(verify_desktop_skill(args.verify, args.desktop_archive))
        if args.installed_skill:
            result.update(verify_installed_skill(args.verify, args.installed_skill))
    else:
        version = release_version(ROOT)
        if args.version is not None and args.version != version:
            raise ValueError("请求版本与项目版本不一致")
        output = args.output or ROOT / "release-output" / f"SolidWorks-Automation-Skill-{version}.zip"
        result = build_skill_archive(ROOT, output)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
