"""发布工作流合同测试：Skill/MCP 是主产品，桌面端只做可选构建。"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CORE_WORKFLOW = ROOT / ".github" / "workflows" / "skill-mcp-release.yml"
DESKTOP_WORKFLOW = ROOT / ".github" / "workflows" / "windows-release.yml"
CORE_BUILD_SCRIPT = ROOT / "scripts" / "build_core_release.ps1"
DESKTOP_BUILD_SCRIPT = ROOT / "scripts" / "build_windows_release.ps1"
JOB_LINE = re.compile(r"^  ([A-Za-z0-9_-]+):\s*$")
NEEDS_EXPR = re.compile(r"needs\.([A-Za-z0-9_-]+)\.result")

CORE_JOBS = {
    "governance",
    "python_tests",
    "core_package",
    "test_and_build",
    "publish_release",
}
DESKTOP_JOBS = {
    "governance",
    "python_tests",
    "frontend_tests",
    "rust_tests",
    "package_build",
    "desktop_build",
}


def _block(lines: list[str], start: int) -> list[str]:
    indent = len(lines[start]) - len(lines[start].lstrip())
    block = [lines[start]]
    for line in lines[start + 1:]:
        if not line.strip():
            block.append(line)
            continue
        current = len(line) - len(line.lstrip())
        if current <= indent and not line.startswith(" " * (indent + 1)):
            break
        block.append(line)
    return block


def _top_level_block(path: Path, key: str) -> list[str]:
    lines = path.read_text(encoding="utf-8").splitlines()
    for index, line in enumerate(lines):
        if line.rstrip() == f"{key}:":
            return _block(lines, index)
    raise AssertionError(f"{path.name} 缺少顶层键 {key}:")


def _jobs(path: Path) -> dict[str, list[str]]:
    lines = path.read_text(encoding="utf-8").splitlines()
    for index, line in enumerate(lines):
        if line.rstrip() != "jobs:":
            continue
        jobs: dict[str, list[str]] = {}
        for offset in range(index + 1, len(lines)):
            match = JOB_LINE.match(lines[offset])
            if match:
                jobs[match.group(1)] = _block(lines, offset)
            elif lines[offset].strip() and not lines[offset].startswith(" "):
                break
        return jobs
    raise AssertionError(f"{path.name} 缺少顶层键 jobs:")


def _joined(block: list[str]) -> str:
    return "\n".join(block)


def _required_job(path: Path) -> tuple[str, list[str]]:
    for job_id, block in _jobs(path).items():
        if "name: test-and-build" in _joined(block):
            return job_id, block
    raise AssertionError("核心发布工作流缺少必需检查 test-and-build")


def test_core_workflow_runs_for_pr_merge_queue_and_tags():
    block = _joined(_top_level_block(CORE_WORKFLOW, "on"))
    assert "pull_request:" in block
    assert "merge_group:" in block
    assert 'tags: ["v*"]' in block


def test_core_workflow_has_required_check_and_expected_jobs():
    assert set(_jobs(CORE_WORKFLOW)) == CORE_JOBS
    job_id, _ = _required_job(CORE_WORKFLOW)
    assert job_id == "test_and_build"


def test_core_required_check_depends_on_all_core_validation():
    job_id, block = _required_job(CORE_WORKFLOW)
    match = re.search(r"needs:\s*\[([^\]]*)\]", _joined(block))
    assert match
    needs = {item.strip() for item in match.group(1).split(",") if item.strip()}
    assert needs == CORE_JOBS - {job_id, "publish_release"}
    assert "if: always()" in _joined(block)


def test_core_required_check_reads_every_prerequisite_result():
    referenced = set(NEEDS_EXPR.findall(CORE_WORKFLOW.read_text(encoding="utf-8")))
    for job_id in CORE_JOBS - {"test_and_build", "publish_release"}:
        assert job_id in referenced


def test_core_workflow_publishes_only_skill_and_mcp_assets():
    publisher = _joined(_jobs(CORE_WORKFLOW)["publish_release"])
    assert "needs: [test_and_build]" in publisher
    assert "needs.test_and_build.result == 'success'" in publisher
    assert "startsWith(github.ref, 'refs/tags/v')" in publisher
    assert "SolidWorks-Automation-Skill-*.zip" in publisher
    assert "release-output/*.mcpb" in publisher
    assert "SHA256SUMS.txt" in publisher
    assert "CAD-Studio" not in publisher
    assert "contents: write" in publisher


def test_core_package_has_no_desktop_build_dependency():
    package = _joined(_jobs(CORE_WORKFLOW)["core_package"])
    assert "build_core_release.ps1" in package
    for forbidden in ("cargo", "tauri", "npm ci", "playwright", "verify_updater_release"):
        assert forbidden not in package.casefold()
    script = CORE_BUILD_SCRIPT.read_text(encoding="utf-8")
    assert "release_check.py" in script
    assert "--core-only" in script
    assert "build_skill_release.py" in script
    assert "build_mcpb.ps1" in script
    assert "CAD-Studio" not in script


def test_desktop_workflow_is_manual_and_does_not_publish_releases():
    trigger = _joined(_top_level_block(DESKTOP_WORKFLOW, "on"))
    assert "workflow_dispatch:" in trigger
    for forbidden in ("push:", "pull_request:", "merge_group:", "tags:"):
        assert forbidden not in trigger
    jobs = _jobs(DESKTOP_WORKFLOW)
    assert set(jobs) == DESKTOP_JOBS
    assert "publish_release" not in jobs
    assert "contents: write" not in DESKTOP_WORKFLOW.read_text(encoding="utf-8")
    assert "action-gh-release" not in DESKTOP_WORKFLOW.read_text(encoding="utf-8")


def test_desktop_aggregator_depends_on_all_optional_build_jobs():
    block = _joined(_jobs(DESKTOP_WORKFLOW)["desktop_build"])
    assert "name: desktop-build" in block
    match = re.search(r"needs:\s*\[([^\]]*)\]", block)
    assert match
    needs = {item.strip() for item in match.group(1).split(",") if item.strip()}
    assert needs == DESKTOP_JOBS - {"desktop_build"}
    assert "if: always()" in block
    package = _joined(_jobs(DESKTOP_WORKFLOW)["package_build"])
    assert "build_windows_release.ps1" in package
    assert DESKTOP_BUILD_SCRIPT.is_file()


def test_every_job_has_timeout():
    for workflow in (CORE_WORKFLOW, DESKTOP_WORKFLOW):
        missing = [
            name
            for name, block in _jobs(workflow).items()
            if "timeout-minutes:" not in _joined(block)
        ]
        assert not missing, f"{workflow.name} 缺少 timeout-minutes: {missing}"


def test_pull_requests_cancel_superseded_core_runs():
    block = _joined(_top_level_block(CORE_WORKFLOW, "concurrency"))
    assert "cancel-in-progress:" in block
    assert "pull_request" in block
