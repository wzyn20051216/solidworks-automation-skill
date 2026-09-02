"""编译并运行保持线圆角的多语言桥接器。

@brief 为 C# PIA、SWBasic 和进程内非托管 C++ 提供统一入口与证据。
@details 已知 SolidWorks 2026 SP1.1 会在 ISetHoldLines 调用处产生服务器故障，因此默认只返回
结构化阻断证据；仅显式启用不安全探测时才执行可能令 SolidWorks 退出的原生调用。
"""

from __future__ import annotations

import ctypes
import json
import os
import shutil
import subprocess
import tempfile
import time
import winreg
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
SOURCE_PATH = SCRIPT_DIR / "native" / "HoldLineBridge.cs"
NATIVE_SOURCE_PATH = SCRIPT_DIR / "native" / "NativeHoldLineAddin.cpp"
NATIVE_DEF_PATH = SCRIPT_DIR / "native" / "NativeHoldLineAddin.def"
NATIVE_MACRO_SOURCE_PATH = SCRIPT_DIR / "native" / "NativeHoldLineMacro.swb"
UNSAFE_HOLD_LINE_ENV = "CAD_STUDIO_UNSAFE_NATIVE_HOLD_LINE"
KNOWN_BLOCKED_BUILD = "SolidWorks 2026 SP1.1 / Revision 34.1.1"
CSC_CANDIDATES = (
    Path(r"C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe"),
    Path(r"C:\Windows\Microsoft.NET\Framework\v4.0.30319\csc.exe"),
)


class HoldLineBridgeError(RuntimeError):
    """@brief 表示保持线桥接器编译、附着或保持线创建失败。"""

    def __init__(self, message: str, evidence: dict[str, Any] | None = None):
        super().__init__(message)
        self.evidence = evidence or {}


def unsafe_hold_line_probe_enabled() -> bool:
    """@brief 判断是否显式允许执行可能导致 SolidWorks 服务器故障的探测。"""
    return os.environ.get(UNSAFE_HOLD_LINE_ENV, "").strip().lower() in {
        "1", "true", "yes", "on",
    }


def known_hold_line_block_evidence(backend: str) -> dict[str, Any]:
    """@brief 返回当前真机已复现的跨语言保持线阻断证据。"""
    return {
        "status": "blocked",
        "reason": "known_server_fault",
        "backend": backend,
        "tested_build": KNOWN_BLOCKED_BUILD,
        "tested_backends": [
            "Python pywin32 tuple/list/SAFEARRAY",
            "C# SolidWorks PIA object[]/IEdge[]",
            "SWBasic typed array and FeatureFillet3",
            "native C++ in-process ISetHoldLines",
        ],
        "failure_boundary": "ISimpleFilletFeatureData2::ISetHoldLines",
        "unsafe_opt_in": f"{UNSAFE_HOLD_LINE_ENV}=1",
    }


def _require_unsafe_probe(
    backend: str,
    allow_unsafe: bool,
    solidworks_revision: str | None = None,
) -> None:
    """@brief 在已知故障构建上阻止未授权危险后端，其它构建允许首次验证。"""
    if allow_unsafe or unsafe_hold_line_probe_enabled():
        return
    if solidworks_revision and not solidworks_revision.startswith("34.1.1"):
        return
    raise HoldLineBridgeError(
        "当前 SolidWorks 构建已在 Python、C#、SWBasic 和进程内 C++ 中复现保持线故障；"
        "默认停止在安全阻断状态。若要在隔离实例中复测，请显式启用不安全探测。",
        known_hold_line_block_evidence(backend),
    )


def _solidworks_revision(sw: Any) -> str | None:
    """@brief 兼容 pywin32 方法/属性两种形态读取 SolidWorks 修订号。"""
    try:
        member = getattr(sw, "RevisionNumber")
        return str(member() if callable(member) else member)
    except Exception:
        return None


def _long_path(path: str) -> Path:
    """@brief 展开注册表中 SolidWorks 可执行文件的 8.3 短路径。"""
    buffer = ctypes.create_unicode_buffer(32768)
    length = ctypes.windll.kernel32.GetLongPathNameW(path, buffer, len(buffer))
    return Path(buffer.value if length else path)


def _short_path(path: Path) -> str:
    """@brief 返回可安全交给 cmd 调用批处理文件的 8.3 路径。"""
    buffer = ctypes.create_unicode_buffer(32768)
    length = ctypes.windll.kernel32.GetShortPathNameW(str(path), buffer, len(buffer))
    return buffer.value if length else str(path)


def _solidworks_install_dir() -> Path:
    """@brief 从默认 ProgID 注册信息定位当前 SolidWorks 安装目录。"""
    with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, r"SldWorks.Application\CLSID") as key:
        clsid, _ = winreg.QueryValueEx(key, "")
    with winreg.OpenKey(
        winreg.HKEY_CLASSES_ROOT,
        rf"CLSID\{clsid}\LocalServer32",
    ) as key:
        command, _ = winreg.QueryValueEx(key, "")
    executable = command.strip().strip('"').split('"')[0]
    return _long_path(executable).resolve().parent


def discover_bridge_toolchain() -> dict[str, Path]:
    """@brief 返回 C# 编译器和 SolidWorks PIA 路径，并严格检查存在性。"""
    csc = next((candidate for candidate in CSC_CANDIDATES if candidate.is_file()), None)
    if csc is None:
        raise HoldLineBridgeError("未找到 .NET Framework C# 编译器 csc.exe")
    install_dir = _solidworks_install_dir()
    paths = {
        "csc": csc,
        "sldworks": install_dir / "SolidWorks.Interop.sldworks.dll",
        "swconst": install_dir / "SolidWorks.Interop.swconst.dll",
    }
    missing = [str(path) for path in paths.values() if not path.is_file()]
    if missing:
        raise HoldLineBridgeError(f"保持线桥接工具链缺少文件: {missing}")
    return paths


def discover_native_toolchain() -> dict[str, Path]:
    """@brief 定位 MSVC x64 和 SolidWorks 原生类型库。"""
    install_dir = _solidworks_install_dir()
    vcvars_candidates = (
        Path(r"C:\BuildTools\VC\Auxiliary\Build\vcvars64.bat"),
        Path(r"C:\Program Files\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat"),
        Path(r"C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvars64.bat"),
    )
    vcvars = next((candidate for candidate in vcvars_candidates if candidate.is_file()), None)
    if vcvars is None:
        raise HoldLineBridgeError("原生保持线 Add-in 需要 MSVC x64 Build Tools")
    paths = {
        "vcvars64": vcvars,
        "sldworks_tlb": install_dir / "sldworks.tlb",
        "swpublished_tlb": install_dir / "swpublished.tlb",
    }
    missing = [str(path) for path in paths.values() if not path.is_file()]
    if missing:
        raise HoldLineBridgeError(f"原生保持线工具链缺少文件: {missing}")
    return paths


def build_native_hold_line_addin(build_dir: Path | None = None) -> tuple[Path, dict[str, str]]:
    """@brief 使用 MSVC 编译 SolidWorks 进程内原生 C++ 桥接 DLL。"""
    toolchain = discover_native_toolchain()
    target_dir = (
        build_dir or Path(tempfile.gettempdir()) / "cad-studio-native-hold-line-addin"
    ).resolve()
    target_dir.mkdir(parents=True, exist_ok=True)
    dll_path = target_dir / "CadStudio.NativeHoldLineBridge.dll"
    install_dir = toolchain["sldworks_tlb"].parent
    compile_command = (
        f'call {_short_path(toolchain["vcvars64"])} >nul && '
        f'cl.exe /nologo /utf-8 /EHsc /std:c++17 /LD /MD '
        f'/I{_short_path(install_dir)} {_short_path(NATIVE_SOURCE_PATH)} '
        f'/link /DEF:{_short_path(NATIVE_DEF_PATH)} /OUT:{_short_path(dll_path)} '
        "ole32.lib oleaut32.lib advapi32.lib"
    )
    completed = subprocess.run(
        ["cmd.exe", "/d", "/s", "/c", compile_command],
        cwd=str(target_dir),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
        check=False,
    )
    if completed.returncode != 0 or not dll_path.is_file():
        raise HoldLineBridgeError(
            "原生 C++ 保持线桥接 DLL 编译失败",
            {
                "returncode": completed.returncode,
                "stdout": completed.stdout,
                "stderr": completed.stderr,
                "command": compile_command,
            },
        )
    evidence = {
        "backend": "native-cpp-bridge",
        "vcvars64": str(toolchain["vcvars64"]),
        "sldworks_tlb": str(toolchain["sldworks_tlb"]),
        "swpublished_tlb": str(toolchain["swpublished_tlb"]),
        "source": str(NATIVE_SOURCE_PATH),
        "module_definition": str(NATIVE_DEF_PATH),
        "dll": str(dll_path),
    }
    return dll_path, evidence


def build_native_hold_line_macro(
    build_dir: Path | None = None,
) -> tuple[Path, dict[str, str]]:
    """@brief 生成 SWBasic 主线程调度宏和同目录原生 C++ 桥接 DLL。"""
    native_path, native_evidence = build_native_hold_line_addin(build_dir)
    target_dir = native_path.parent
    macro_path = target_dir / "NativeHoldLineMacro.swb"
    macro_source = NATIVE_MACRO_SOURCE_PATH.read_text(encoding="utf-8")
    dll_literal = str(native_path).replace('"', '""')
    macro_path.write_text(
        macro_source.replace("__NATIVE_DLL__", dll_literal),
        encoding="ascii",
    )
    return macro_path, {
        "backend": "native-cpp-swb",
        "macro": str(macro_path),
        "macro_source": str(NATIVE_MACRO_SOURCE_PATH),
        "native": native_evidence,
    }


def create_hold_line_via_native_addin(
    sw: Any,
    expected_title: str,
    *,
    build_dir: Path | None = None,
    allow_unsafe: bool = False,
) -> dict[str, Any]:
    """@brief 通过 SWBasic 主线程调用原生 C++ ISetHoldLines 桥接器。"""
    _require_unsafe_probe(
        "native-cpp-swb",
        allow_unsafe,
        solidworks_revision=_solidworks_revision(sw),
    )
    macro_path, toolchain = build_native_hold_line_macro(build_dir)
    result_path = Path(tempfile.gettempdir()) / "cad-studio-hold-line-result.json"
    job_path = Path(tempfile.gettempdir()) / "cad-studio-hold-line-job.txt"
    result_path.unlink(missing_ok=True)
    job_path.write_text(f"{result_path}\n{expected_title}\n", encoding="utf-8")
    try:
        import pythoncom
        from win32com.client import VARIANT

        macro_error = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
        run_macro_result = sw.RunMacro2(
            str(macro_path), "NativeHoldLineMacro1", "main", 0, macro_error
        )
        direct_feature = sw.ActiveDoc.FeatureByName("Advanced_Hold_Line_Fillet")
        if direct_feature is not None:
            return {
                "status": "verified",
                "backend": "swbasic-featurefillet3",
                "featureName": "Advanced_Hold_Line_Fillet",
                "runMacroResult": run_macro_result,
                "runMacroError": int(macro_error.value),
                "toolchain": toolchain,
            }
        deadline = time.monotonic() + 5.0
        result: dict[str, Any] | None = None
        while time.monotonic() < deadline:
            if result_path.is_file():
                try:
                    candidate = json.loads(result_path.read_text(encoding="utf-8"))
                    if candidate.get("status") in {"verified", "blocked"}:
                        result = candidate
                        break
                except (json.JSONDecodeError, OSError):
                    pass
            time.sleep(0.1)
        if result is None:
            stage = None
            if result_path.is_file():
                try:
                    stage = json.loads(result_path.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, OSError):
                    stage = None
            raise HoldLineBridgeError(
                "SolidWorks 已调用 RunMacro2，但 SWBasic/原生桥接未写出结果",
                {
                    "runMacroResult": run_macro_result,
                    "runMacroError": int(macro_error.value),
                    "stage": stage,
                    "toolchain": toolchain,
                },
            )
        result.update({
            "toolchain": toolchain,
            "runMacroResult": run_macro_result,
            "runMacroError": int(macro_error.value),
        })
        feature = sw.ActiveDoc.FeatureByName("Advanced_Hold_Line_Fillet")
        persisted_count = 0
        if feature is not None:
            definition = feature.GetDefinition()
            if definition is not None and definition.AccessSelections(sw.ActiveDoc, None):
                try:
                    persisted_count = int(definition.GetHoldLineCount())
                finally:
                    definition.ReleaseSelectionAccess()
        result.update({
            "featureName": "Advanced_Hold_Line_Fillet",
            "persistedHoldLineCount": persisted_count,
        })
        if (
            result.get("status") != "verified"
            or int(result.get("holdLineCount") or 0) != 1
            or persisted_count != 1
        ):
            raise HoldLineBridgeError(
                str(result.get("error") or "原生 C++/SWBasic 未创建可持久化回读的保持线圆角"),
                result,
            )
        return result
    finally:
        result_path.unlink(missing_ok=True)
        job_path.unlink(missing_ok=True)


def build_hold_line_bridge(build_dir: Path | None = None) -> tuple[Path, dict[str, str]]:
    """@brief 编译 C# PIA 桥接器，返回可执行文件及工具链证据。"""
    toolchain = discover_bridge_toolchain()
    target_dir = (build_dir or Path(tempfile.gettempdir()) / "cad-studio-hold-line-bridge").resolve()
    target_dir.mkdir(parents=True, exist_ok=True)
    executable = target_dir / "CadStudio.HoldLineBridge.exe"
    command = [
        str(toolchain["csc"]),
        "/nologo",
        "/utf8output",
        "/target:exe",
        "/platform:x64",
        f"/out:{executable}",
        f"/reference:{toolchain['sldworks']}",
        f"/reference:{toolchain['swconst']}",
        str(SOURCE_PATH),
    ]
    completed = subprocess.run(
        command,
        cwd=str(target_dir),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
        check=False,
    )
    if completed.returncode != 0 or not executable.is_file():
        raise HoldLineBridgeError(
            "C# PIA 保持线桥接器编译失败",
            {
                "command": command,
                "returncode": completed.returncode,
                "stdout": completed.stdout,
                "stderr": completed.stderr,
            },
        )
    for name in ("sldworks", "swconst"):
        shutil.copy2(toolchain[name], target_dir / toolchain[name].name)
    evidence = {
        "compiler": str(toolchain["csc"]),
        "sldworks_pia": str(toolchain["sldworks"]),
        "swconst_pia": str(toolchain["swconst"]),
        "source": str(SOURCE_PATH),
        "executable": str(executable),
    }
    return executable, evidence


def create_hold_line_via_csharp(
    expected_title: str,
    *,
    build_dir: Path | None = None,
    allow_unsafe: bool = False,
    solidworks_revision: str | None = None,
) -> dict[str, Any]:
    """@brief 在当前活动零件中通过 C# PIA 创建保持线面圆角并返回结构化证据。"""
    _require_unsafe_probe("csharp-pia", allow_unsafe, solidworks_revision)
    executable, toolchain = build_hold_line_bridge(build_dir)
    completed = subprocess.run(
        [str(executable), str(expected_title)],
        cwd=str(executable.parent),
        capture_output=True,
        text=True,
        encoding="utf-8-sig",
        errors="replace",
        timeout=90,
        check=False,
        env={**os.environ},
    )
    lines = [line.strip() for line in completed.stdout.splitlines() if line.strip()]
    try:
        result = json.loads(lines[-1]) if lines else {}
    except json.JSONDecodeError as exc:
        raise HoldLineBridgeError(
            "C# PIA 保持线桥接器没有返回有效 JSON",
            {
                "returncode": completed.returncode,
                "stdout": completed.stdout,
                "stderr": completed.stderr,
                "toolchain": toolchain,
            },
        ) from exc
    result["toolchain"] = toolchain
    result["returncode"] = completed.returncode
    result["stderr"] = completed.stderr
    if completed.returncode != 0 or result.get("status") != "verified":
        raise HoldLineBridgeError(
            str(result.get("error") or "C# PIA 保持线圆角创建失败"),
            result,
        )
    return result


__all__ = [
    "HoldLineBridgeError",
    "build_native_hold_line_addin",
    "build_native_hold_line_macro",
    "build_hold_line_bridge",
    "create_hold_line_via_native_addin",
    "create_hold_line_via_csharp",
    "discover_bridge_toolchain",
    "discover_native_toolchain",
    "known_hold_line_block_evidence",
    "unsafe_hold_line_probe_enabled",
]
