"""生成 CAD Studio 桌面包内嵌的运行时 Skill 快照。"""
from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUNDLED_SKILL = ROOT / "apps/workbench-ui/src-tauri/resources/skill"

TOP_LEVEL_FILES = (
    "README.md",
    "SKILL.md",
    "SUBSKILLS.md",
    "capabilities.yaml",
    "golden-workflows.yaml",
    "requirements.txt",
    "requirements-mesh.txt",
    "requirements-occt.txt",
)
RUNTIME_ROOTS = (
    "agents",
    "examples",
    "mcp-server",
    "references",
    "scripts",
    "subskills",
    "apps/desktop/cad_workbench",
)
RUNTIME_FILES = ("apps/desktop/__init__.py",)
SKIPPED_DIRECTORIES = {
    ".git",
    ".pytest_cache",
    "__pycache__",
    "bin",
    "build",
    "dist",
    "node_modules",
    "obj",
    "output",
    "release-output",
}
SKIPPED_SUFFIXES = {".pyc", ".pyo"}


def _validate_target(root: Path, target: Path) -> None:
    """@brief 限制同步目标只能是仓库内的 Tauri resources/skill。"""
    expected_parent = (root / "apps/workbench-ui/src-tauri/resources").resolve()
    resolved_target = target.resolve()
    if resolved_target.parent != expected_parent or resolved_target.name != "skill":
        raise ValueError(f"拒绝写入非预期内嵌 Skill 目录: {resolved_target}")


def _is_runtime_file(path: Path, source_root: Path) -> bool:
    """@brief 排除缓存、构建产物和字节码，只保留可发布源文件。"""
    relative = path.relative_to(source_root)
    return not any(part in SKIPPED_DIRECTORIES for part in relative.parts) and path.suffix.casefold() not in SKIPPED_SUFFIXES


def collect_runtime_files(root: Path) -> dict[Path, Path]:
    """@brief 收集内嵌 Skill 所需的源文件，键为相对仓库路径。"""
    files: dict[Path, Path] = {}
    for relative_name in (*TOP_LEVEL_FILES, *RUNTIME_FILES):
        source = root / relative_name
        if not source.is_file():
            raise FileNotFoundError(f"内嵌 Skill 源文件缺失: {source}")
        files[Path(relative_name)] = source
    for relative_root in RUNTIME_ROOTS:
        source_root = root / relative_root
        if not source_root.is_dir():
            raise FileNotFoundError(f"内嵌 Skill 源目录缺失: {source_root}")
        for source in source_root.rglob("*"):
            if source.is_file() and _is_runtime_file(source, source_root):
                files[source.relative_to(root)] = source
    return files


def sync_bundled_skill(root: Path = ROOT, target: Path = BUNDLED_SKILL) -> dict[str, object]:
    """@brief 同步运行时文件并清理目标中已无源文件的陈旧副本。"""
    root = root.resolve()
    target = target.resolve()
    _validate_target(root, target)
    source_files = collect_runtime_files(root)
    target.mkdir(parents=True, exist_ok=True)
    for relative_path, source in source_files.items():
        destination = target / relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)

    pruned: list[str] = []
    expected = set(source_files)
    for bundled_file in sorted(path for path in target.rglob("*") if path.is_file()):
        relative_path = bundled_file.relative_to(target)
        if relative_path not in expected:
            bundled_file.unlink()
            pruned.append(relative_path.as_posix())
    for directory in sorted((path for path in target.rglob("*") if path.is_dir()), reverse=True):
        try:
            directory.rmdir()
        except OSError:
            pass
    return {
        "status": "pass",
        "target": str(target),
        "files": len(source_files),
        "pruned": pruned,
    }


def main() -> int:
    """@brief 命令行入口。"""
    parser = argparse.ArgumentParser(description="同步 CAD Studio 内嵌 Skill")
    parser.parse_args()
    print(json.dumps(sync_bundled_skill(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
