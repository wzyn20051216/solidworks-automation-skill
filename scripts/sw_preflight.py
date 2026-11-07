"""
SolidWorks 自动化技能运行前自检。

本模块专门处理两类入口风险：
1. Python COM 依赖缺失时自动执行 pip 安装；可显式禁用。
2. 未检测到 SolidWorks 时立即停止，并提示用户手动安装或修复 COM 注册。
"""
from __future__ import annotations

import argparse
import importlib
import os
import platform
import site
import subprocess
import sys
from dataclasses import dataclass
from typing import Callable, Iterable, List, Optional, Sequence

try:
    from .cad_installation import discover_installation
except ImportError:
    from cad_installation import discover_installation


PIP_REQUIREMENTS = ("pywin32>=305", "comtypes>=1.2.0")
OFFICIAL_PYPI_INDEX = "https://pypi.org/simple"
DEPENDENCY_PROMPT = "检测到当前 Python 环境缺少 comtypes / win32com 库，是否授权 AI 自动为您配置本地环境？[Y/N]"


def _configure_stdio_utf8() -> None:
    """在 Windows 旧代码页下尽量使用 UTF-8 输出中文提示。"""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


_configure_stdio_utf8()


class DependencyInstallDeclined(RuntimeError):
    """用户拒绝自动安装 Python COM 依赖。"""


class SolidWorksNotInstalledError(RuntimeError):
    """当前系统未检测到 SolidWorks。"""


@dataclass
class PreflightResult:
    """运行前自检结果。"""

    missing_packages: List[str]
    dependencies_ready: bool
    solidworks_ready: Optional[bool]


def _module_available(module_name: str) -> bool:
    """检查 Python 模块是否可导入。"""
    try:
        importlib.import_module(module_name)
        return True
    except ModuleNotFoundError as exc:
        requested_root = module_name.split(".", 1)[0]
        if exc.name in {module_name, requested_root}:
            return False
        raise


def missing_com_dependencies() -> List[str]:
    """返回缺失的 COM 依赖包名称。"""
    checks = (
        ("comtypes", "comtypes>=1.2.0"),
        ("pythoncom", "pywin32>=305"),
        ("win32com.client", "pywin32>=305"),
    )
    missing: List[str] = []
    for module_name, requirement in checks:
        if not _module_available(module_name) and requirement not in missing:
            missing.append(requirement)
    return missing


def pip_install_command(
    python_executable: Optional[str] = None,
    requirements: Sequence[str] = PIP_REQUIREMENTS,
) -> List[str]:
    """生成补齐依赖的 pip 命令。"""
    command = [python_executable or sys.executable, "-m", "pip", "install", "--no-input", "--disable-pip-version-check"]
    if python_executable is None and sys.prefix == getattr(sys, "base_prefix", sys.prefix):
        command.append("--user")
    return [*command, *requirements]


def shell_command_text(command: Sequence[str]) -> str:
    """生成适合复制到 Windows shell 的命令文本。"""
    special_chars = set(' <>&|^"')
    parts = []
    for part in command:
        text = str(part)
        if any(char in special_chars for char in text):
            parts.append('"' + text.replace('"', r'\"') + '"')
        else:
            parts.append(text)
    return " ".join(parts)


def install_com_dependencies(
    python_executable: Optional[str] = None,
    requirements: Sequence[str] = PIP_REQUIREMENTS,
) -> None:
    """执行 pip 安装，补齐 Python COM 依赖。

    企业镜像可能缺少 comtypes 等 Windows 专用包。首次安装失败时自动回退到
    官方 PyPI；仍失败则保留两次命令的错误，便于调用方定位网络或权限问题。
    """
    base_command = pip_install_command(python_executable, requirements)
    primary_index = os.environ.get("SW_PIP_INDEX_URL", "").strip()
    primary_command = list(base_command)
    if primary_index:
        primary_command.extend(["--index-url", primary_index])
    fallback_index = os.environ.get("SW_PIP_FALLBACK_INDEX_URL", OFFICIAL_PYPI_INDEX).strip()
    fallback_command = [*base_command, "--index-url", fallback_index] if fallback_index else list(base_command)

    try:
        subprocess.check_call(primary_command, timeout=180)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as first_error:
        if fallback_command == primary_command:
            raise
        try:
            subprocess.check_call(fallback_command, timeout=180)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as fallback_error:
            raise RuntimeError(
                "SolidWorks COM 依赖安装失败。\n"
                f"主索引命令: {shell_command_text(primary_command)}\n"
                f"回退命令: {shell_command_text(fallback_command)}\n"
                f"主索引错误: {first_error}\n"
                f"回退错误: {fallback_error}"
            ) from fallback_error
    importlib.invalidate_caches()
    if python_executable is None and sys.prefix == getattr(sys, "base_prefix", sys.prefix) and not sys.flags.no_user_site:
        site.addsitedir(site.getusersitepackages())


def ask_install_permission(
    input_func: Callable[[str], str] = input,
    output_func: Callable[[str], None] = print,
) -> bool:
    """向用户请求自动配置本地 Python 环境的授权。"""
    output_func(DEPENDENCY_PROMPT)
    try:
        answer = input_func("").strip().lower()
    except EOFError:
        answer = ""
    return answer in {"y", "yes"}


def ensure_com_dependencies(
    allow_install: Optional[bool] = None,
    input_func: Callable[[str], str] = input,
    output_func: Callable[[str], None] = print,
) -> List[str]:
    """
    确保 comtypes / pywin32 可用。

    参数:
        allow_install: True=直接安装，False=不安装，None=按环境设置自动安装。
        input_func: 便于测试替换的输入函数。
        output_func: 便于测试替换的输出函数。

    返回:
        初始缺失的依赖列表。
    """
    missing = missing_com_dependencies()
    if not missing:
        return []

    should_install = allow_install
    if should_install is None:
        should_install = os.environ.get("SW_AUTO_INSTALL_DEPENDENCIES", "on").strip().lower() not in {"0", "off", "false"}

    if not should_install:
        command = shell_command_text(pip_install_command())
        raise DependencyInstallDeclined(
            "当前 Python 环境缺少 SolidWorks COM 依赖。请手动执行：\n"
            f"{command}"
        )

    install_com_dependencies(requirements=tuple(missing))
    still_missing = missing_com_dependencies()
    if still_missing:
        raise ModuleNotFoundError(
            "依赖安装后仍无法导入: " + ", ".join(still_missing)
        )
    return missing


def import_com_dependencies(allow_install: Optional[bool] = None):
    """
    导入 pythoncom、win32com 和 VARIANT。

    该函数用于替代模块顶部直接 import，避免 ModuleNotFoundError 变成冷冰冰的报错。
    """
    ensure_com_dependencies(allow_install=allow_install)
    pythoncom = importlib.import_module("pythoncom")
    client = importlib.import_module("win32com.client")
    return pythoncom, client, client.VARIANT


def _is_windows() -> bool:
    """检查当前系统是否为 Windows。"""
    return os.name == "nt" or platform.system().lower().startswith("win")


def _solidworks_com_registered() -> bool:
    """检查 SolidWorks COM ProgID 是否已注册。"""
    return bool(discover_installation("solidworks")["registered"])


def _solidworks_exe_candidates() -> Iterable[str]:
    """枚举常见 SolidWorks 主程序路径。"""
    executable = discover_installation("solidworks")["executable"]
    if executable:
        yield executable


def solidworks_installed() -> bool:
    """判断本机是否能检测到 SolidWorks 安装或 COM 注册。"""
    if not _is_windows():
        return False
    installation = discover_installation("solidworks")
    if installation["registered"]:
        return True
    return bool(installation["executable"] and os.path.exists(installation["executable"]))


def ensure_solidworks_installed() -> None:
    """未检测到 SolidWorks 时立即停止并给出明确提示。"""
    if solidworks_installed():
        return
    raise SolidWorksNotInstalledError(
        "未检测到 SolidWorks。请先手动安装 SolidWorks，并至少启动一次完成 COM 注册后再使用本技能。"
    )


def run_preflight(
    allow_install: Optional[bool] = None,
    check_solidworks: bool = True,
) -> PreflightResult:
    """执行依赖和 SolidWorks 安装状态自检。"""
    solidworks_ready: Optional[bool] = None
    if check_solidworks:
        ensure_solidworks_installed()
        solidworks_ready = True
    missing = ensure_com_dependencies(allow_install=allow_install)
    return PreflightResult(
        missing_packages=missing,
        dependencies_ready=True,
        solidworks_ready=solidworks_ready,
    )


def _parse_args():
    """解析命令行参数。"""
    parser = argparse.ArgumentParser(description="SolidWorks 自动化技能运行前自检。")
    parser.add_argument("--yes", action="store_true", help="检测到缺失依赖时直接授权安装。")
    parser.add_argument("--no-install", action="store_true", help="检测到缺失依赖时不自动安装。")
    parser.add_argument("--no-solidworks-check", action="store_true", help="跳过 SolidWorks 安装检测。")
    return parser.parse_args()


def main() -> int:
    """命令行入口。"""
    args = _parse_args()
    allow_install = False if args.no_install else True if args.yes else None
    result = run_preflight(
        allow_install=allow_install,
        check_solidworks=not args.no_solidworks_check,
    )
    print("SolidWorks 自动化技能自检通过。")
    if result.missing_packages:
        print("已补齐依赖: " + ", ".join(result.missing_packages))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except DependencyInstallDeclined as exc:
        print(exc, file=sys.stderr)
        raise SystemExit(2)
    except SolidWorksNotInstalledError as exc:
        print(exc, file=sys.stderr)
        raise SystemExit(3)
