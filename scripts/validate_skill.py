"""
验证 SolidWorks Automation Skill 的基础完整性。

该脚本不连接 SolidWorks，也不要求安装 pywin32；它只做静态检查，适合在提交前或
CI 中快速发现语法错误、关键文件缺失、SKILL.md 元数据异常等问题。
"""
import ast
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
    """检查 scripts 和 examples 下 Python 文件语法。"""
    targets = list((ROOT / "scripts").glob("*.py")) + list((ROOT / "examples").glob("*.py"))
    for path in targets:
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def main():
    """执行全部静态检查。"""
    check_required_files()
    check_skill_frontmatter()
    check_python_syntax()
    print("验证通过: skill 文件完整，Python 语法正常。")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"验证失败: {exc}", file=sys.stderr)
        sys.exit(1)
