"""@brief 发布工作流的合同测试：锁定合并门禁与 merge queue 依赖的结构性不变量。

这些不变量一旦被无意改掉，后果都是"静默失效"而不是显式报错：
- 缺少 `merge_group` 触发器 → merge queue 条目等不到必需检查，队列超时；
- `test-and-build` 显示名被改 → ruleset 要求的必需检查上下文消失，门禁失效；
- `test-and-build` 不再 `needs` 全部作业 → 某个子作业失败也能拿到绿灯；
- 作业缺 `timeout-minutes` → 悬挂运行占用额度直到 6 小时默认上限；
- 用 `needs.some-job.result` 取结论 → 连字符被解析成减法，取到空值，
  聚合判定必然误判失败（2026-10-28 真实踩过这个坑）。

因此这里用结构化断言把它们固定下来，而不是靠评审时的记忆。
为避免引入新依赖（仓库未声明 PyYAML），本文件只做缩进感知的行级解析，不做通用 YAML 解析。
"""
from __future__ import annotations

import re
from pathlib import Path

WORKFLOW = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "windows-release.yml"
JOB_LINE = re.compile(r"^  ([A-Za-z0-9_-]+):\s*$")
NEEDS_EXPR = re.compile(r"needs\.([A-Za-z0-9_-]+)\.result")
REQUIRED_CHECK = "test-and-build"
EXPECTED_JOBS = {
    "governance",
    "python_tests",
    "frontend_tests",
    "rust_tests",
    "package_build",
    "test_and_build",
    "publish_release",
}


def _lines() -> list[str]:
    return WORKFLOW.read_text(encoding="utf-8").splitlines()


def _block(lines: list[str], start: int) -> list[str]:
    """@brief 取从 start 开始、到下一个同级或更高层级键之前的所有行。"""
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


def _top_level_block(lines: list[str], key: str) -> list[str]:
    for index, line in enumerate(lines):
        if line.rstrip() == f"{key}:":
            return _block(lines, index)
    raise AssertionError(f"工作流缺少顶层键 {key}:")


def _jobs(lines: list[str]) -> dict[str, list[str]]:
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
    raise AssertionError("工作流缺少顶层键 jobs:")


def _joined(block: list[str]) -> str:
    return "\n".join(block)


def _required_job() -> tuple[str, list[str]]:
    """@brief 按显示名定位必需检查作业：门禁认的是显示名，不是作业 id。"""
    for job_id, block in _jobs(_lines()).items():
        if f"name: {REQUIRED_CHECK}" in _joined(block):
            return job_id, block
    raise AssertionError(f"没有显示名为 {REQUIRED_CHECK} 的作业：ruleset 的必需检查将永久 pending")


def test_workflow_declares_merge_group_trigger():
    """merge queue 依赖 merge_group 事件；缺失会让队列条目永远等不到必需检查。"""
    block = _joined(_top_level_block(_lines(), "on"))
    assert "merge_group:" in block, "缺少 merge_group 触发器，merge queue 将无法获得必需检查"


def test_required_check_job_exists_with_expected_display_name():
    """ruleset 要求的上下文是 test-and-build，改名或删除都会让门禁静默失效。"""
    _required_job()


def test_job_ids_are_the_expected_simple_identifiers():
    """表达式里只能安全引用不含连字符的作业 id。"""
    assert set(_jobs(_lines())) == EXPECTED_JOBS


def test_needs_expressions_reference_identifier_safe_jobs():
    """`needs.some-job.result` 会被解析成减法而取到空值，必须用下划线 id。"""
    jobs = _jobs(_lines())
    # 注释里可以出现反例说明，只检查实际生效的表达式行。
    code_lines = [line for line in WORKFLOW.read_text(encoding="utf-8").splitlines()
                  if not line.lstrip().startswith("#")]
    found = 0
    for line in code_lines:
        for match in NEEDS_EXPR.finditer(line):
            found += 1
            referenced = match.group(1)
            assert "-" not in referenced, f"needs 表达式使用了含连字符的作业 id: {referenced}"
            assert referenced in jobs, f"needs 表达式引用了不存在的作业: {referenced}"
    assert found >= len(jobs) - 1, "验证汇总和下游发布必须读取其前置作业结论"


def test_required_check_job_depends_on_every_other_job():
    """任一子作业失败时，必需检查必须随之失败，而不是拿到独立绿灯。"""
    job_id, block = _required_job()
    needs_match = re.search(r"needs:\s*\[([^\]]*)\]", _joined(block))
    assert needs_match, "必需检查作业必须以行内列表声明 needs"
    needs = {item.strip() for item in needs_match.group(1).split(",") if item.strip()}
    # 发布作业在汇总成功后运行，不能反向成为汇总的前置，形成依赖环。
    expected = set(_jobs(_lines())) - {job_id, "publish_release"}
    assert needs == expected, f"needs 与作业集合不一致：缺少 {expected - needs}，多出 {needs - expected}"


def test_required_check_job_reports_failure_instead_of_being_skipped():
    """上游失败时若本作业被 skipped，会被误读为"未运行"；必须显式判定并报 failure。"""
    _, block = _required_job()
    joined = _joined(block)
    assert "if: always()" in joined, "必需检查作业必须使用 if: always() 保证始终给出结论"
    referenced = set(NEEDS_EXPR.findall(WORKFLOW.read_text(encoding="utf-8")))
    for job_id in _jobs(_lines()):
        if job_id in {_required_job()[0], "publish_release"}:
            continue
        assert job_id in referenced, f"必需检查未读取 {job_id} 的结论"


def test_every_job_has_timeout():
    """缺少 timeout 会让悬挂运行占满默认 6 小时上限。"""
    jobs = _jobs(_lines())
    missing = [name for name, block in jobs.items() if "timeout-minutes:" not in _joined(block)]
    assert not missing, f"以下作业缺少 timeout-minutes: {missing}"


def test_end_to_end_steps_retry_once_and_keep_first_diagnostics():
    """端到端允许重试 1 次以吸收启动竞态，但必须保留第 1 次诊断，不能掩盖稳定失败。"""
    package = _joined(_jobs(_lines())["package_build"])
    assert "e2e-diagnostics.attempt1" in package, "重试前必须保留第 1 次诊断文件"
    assert "重试 1 次" in package, "重试行为必须在日志中显式说明"
    assert "throw" in package, "重试后仍失败必须抛出错误"


def test_package_diagnostics_upload_is_unconditional():
    """失败时恰好最需要现场：诊断上传不能只在成功路径执行。"""
    package = _joined(_jobs(_lines())["package_build"])
    assert "Upload package startup diagnostics" in package
    assert "if: always()" in package


def test_aggregator_step_has_no_unquoted_hyphenated_ps_keys():
    """PowerShell 哈希表键含连字符且未加引号会直接解析失败（2026-10-28 真实踩过）。

    这里只锁定"不要写出未加引号的连字符赋值"这一条，避免门禁因为脚本语法错误变红。
    """
    _, block = _required_job()
    joined = _joined(block)
    offenders = [line.strip() for line in joined.splitlines()
                 if re.match(r"^\s*[A-Za-z0-9_]+-[A-Za-z0-9-]+\s*=(?!=)", line)]
    assert not offenders, f"聚合作业脚本含未加引号的连字符键赋值（PowerShell 解析会失败）: {offenders}"


def test_pull_request_runs_cancel_superseded_commits():
    """同一 PR 的旧运行应被取消，避免排队等待已过期提交。"""
    block = _joined(_top_level_block(_lines(), "concurrency"))
    assert "cancel-in-progress:" in block
    assert "pull_request" in block


def test_release_publication_is_downstream_of_all_validation():
    jobs = _jobs(_lines())
    publisher = _joined(jobs["publish_release"])
    assert "needs: [test_and_build]" in publisher
    assert "needs.test_and_build.result == 'success'" in publisher
    assert "startsWith(github.ref, 'refs/tags/v')" in publisher
    assert "draft: true" in publisher
    assert "SolidWorks-Automation-Skill-*.zip" in publisher
    assert "action-gh-release" not in _joined(jobs["package_build"])
    assert "contents: write" not in _joined(jobs["package_build"])
    assert "contents: write" in publisher
