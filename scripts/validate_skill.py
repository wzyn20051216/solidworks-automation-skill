"""
验证 SolidWorks Automation Skill 的基础完整性。

该脚本不连接 SolidWorks，也不要求安装 pywin32；它只做静态检查，适合在提交前或
CI 中快速发现语法错误、关键文件缺失、SKILL.md 元数据异常等问题。
"""
import ast
import json
import pathlib
import sys


def _configure_stdio_utf8():
    """在 Windows 旧代码页下尽量使用 UTF-8 输出中文提示。"""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


_configure_stdio_utf8()

ROOT = pathlib.Path(__file__).resolve().parents[1]
REQUIRED_FILES = [
    "SKILL.md",
    "README.md",
    "agents/openai.yaml",
    "scripts/sw_preflight.py",
    "scripts/sw_macro_guard.py",
    "scripts/sw_connect.py",
    "scripts/__init__.py",
    "scripts/sw_appearance.py",
    "scripts/sw_part.py",
    "scripts/sw_assembly.py",
    "scripts/sw_drawing.py",
    "scripts/sw_export.py",
    "scripts/sw_review.py",
    "scripts/sw_hole_features.py",
    "scripts/sw_motion.py",
    "scripts/sw_capability_probe.py",
    "scripts/sw_session.py",
    "scripts/validate_mcp.py",
    "mcp-server/server.py",
    "mcp-server/README.md",
    "mcp-server/requirements.txt",
    "mcp-server/register_all_ai_mcp.js",
    "mcp-server/register_all_ai_mcp.ps1",
    "examples/08_mini_fan_motion_assembly.py",
    "references/part-modeling.md",
    "references/assembly.md",
    "references/mcp-server.md",
    "references/drawing.md",
    "references/export.md",
    "references/review.md",
    "references/complex-hole-features.md",
    "references/motion-study.md",
    "references/agent-provider-architecture.md",
    "references/complex-mechanical-routing.md",
    "references/enterprise-agent-rag.md",
    "references/api-lookup.md",
    "references/troubleshooting.md",
]


def check_required_files():
    """检查必需文件是否存在。"""
    missing = [path for path in REQUIRED_FILES if not (ROOT / path).exists()]
    if missing:
        raise AssertionError("缺少必需文件: " + ", ".join(missing))


def check_skill_frontmatter():
    """检查 SKILL.md 的基础 frontmatter。"""
    text = (ROOT / "SKILL.md").read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        raise AssertionError("SKILL.md 必须以 YAML frontmatter 开头")
    if "name: solidworks-automation" not in text:
        raise AssertionError("SKILL.md 缺少正确的 name")
    if "description:" not in text:
        raise AssertionError("SKILL.md 缺少 description")


def check_python_syntax():
    """检查主脚本、桌面后端、MCP、测试和全部子技能 Python 语法。"""
    roots = ["scripts", "examples", "tests", "apps/desktop", "mcp-server", "subskills"]
    targets = sorted(
        path
        for relative in roots
        for path in (ROOT / relative).rglob("*.py")
        if not {"__pycache__", "node_modules", "target", "ai_team"}.intersection(path.parts)
    )
    for path in targets:
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return len(targets)


def check_json_files():
    """检查任务契约、输出契约和设计计划 Schema 是否为有效 JSON。"""
    targets = [
        ROOT / "apps/desktop/cad_workbench/schemas/automation_job.schema.json",
        ROOT / "apps/desktop/cad_workbench/schemas/codex_final_response.schema.json",
        ROOT / "subskills/solidworks-vibecad/schemas/design_plan.schema.json",
    ]
    for path in targets:
        json.loads(path.read_text(encoding="utf-8"))
    return len(targets)


def main():
    """执行全部静态检查。"""
    check_required_files()
    check_skill_frontmatter()
    python_count = check_python_syntax()
    json_count = check_json_files()
    print(f"验证通过: skill 文件完整，{python_count} 个 Python 文件和 {json_count} 个 JSON Schema 正常。")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"验证失败: {exc}", file=sys.stderr)
        sys.exit(1)
