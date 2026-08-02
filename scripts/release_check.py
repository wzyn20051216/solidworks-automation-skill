"""发布前静态一致性门禁。"""
from __future__ import annotations

import json
import re
from filecmp import cmp
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUNDLED_SKILL = ROOT / "apps/workbench-ui/src-tauri/resources/skill"


def _version(path: Path, pattern: str) -> str:
    match = re.search(pattern, path.read_text(encoding="utf-8"))
    if not match:
        raise AssertionError(f"无法读取版本: {path}")
    return match.group(1)


def find_bundled_skill_drift(root: Path, bundled_skill: Path) -> list[str]:
    """@brief 返回桌面内嵌 Skill 中缺少源文件或内容不一致的相对路径。"""
    if not bundled_skill.is_dir():
        return ["<bundled-skill-missing>"]
    drift: list[str] = []
    for bundled_path in sorted(path for path in bundled_skill.rglob("*") if path.is_file()):
        relative_path = bundled_path.relative_to(bundled_skill)
        source_path = root / relative_path
        relative_name = relative_path.as_posix()
        if not source_path.is_file():
            drift.append(f"missing-source:{relative_name}")
        elif not cmp(source_path, bundled_path, shallow=False):
            drift.append(relative_name)
    return drift


def run_release_check() -> dict[str, object]:
    """@brief 校验应用版本、能力真源和必需发布文件。"""
    ui_version = _version(ROOT / "apps/workbench-ui/package.json", r'"version"\s*:\s*"([^"]+)"')
    tauri_version = _version(ROOT / "apps/workbench-ui/src-tauri/tauri.conf.json", r'"version"\s*:\s*"([^"]+)"')
    cargo_version = _version(ROOT / "apps/workbench-ui/src-tauri/Cargo.toml", r'(?m)^version\s*=\s*"([^"]+)"')
    if len({ui_version, tauri_version, cargo_version}) != 1:
        raise AssertionError(f"版本不一致: {ui_version}, {tauri_version}, {cargo_version}")
    manifest = json.loads((ROOT / "capabilities.yaml").read_text(encoding="utf-8"))
    capabilities = manifest.get("capabilities", [])
    ids = [item.get("id") for item in capabilities]
    if len(ids) != len(set(ids)) or len(ids) < 10:
        raise AssertionError("能力清单 ID 重复或数量不足")
    required = [
        "SKILL.md",
        "README.md",
        "capabilities.yaml",
        "scripts/stability_regression.py",
        "scripts/release_check.py",
        "scripts/dfm_review.py",
    ]
    missing = [item for item in required if not (ROOT / item).is_file()]
    if missing:
        raise AssertionError("发布文件缺失: " + ", ".join(missing))
    bundled_drift = find_bundled_skill_drift(ROOT, BUNDLED_SKILL)
    if bundled_drift:
        preview = ", ".join(bundled_drift[:10])
        suffix = " ..." if len(bundled_drift) > 10 else ""
        raise AssertionError(f"桌面内嵌 Skill 与根 Skill 不一致: {preview}{suffix}")
    bundled_file_count = sum(1 for path in BUNDLED_SKILL.rglob("*") if path.is_file())
    return {
        "status": "pass",
        "version": ui_version,
        "capabilities": len(capabilities),
        "bundled_skill_files": bundled_file_count,
        "missing": [],
    }


if __name__ == "__main__":
    print(json.dumps(run_release_check(), ensure_ascii=False, indent=2))
