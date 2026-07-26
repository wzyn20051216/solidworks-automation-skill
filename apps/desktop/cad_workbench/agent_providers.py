"""@brief CAD Studio 多 Agent CLI Provider 发现、命令构建与结果归一化。"""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Sequence


SUPPORTED_PROVIDER_IDS = ("codex", "claude", "gemini", "opencode")
REQUIRED_RESULT_FIELDS = {"summary", "changedFiles", "verification", "risks", "nextSteps"}


@dataclass(frozen=True)
class AgentProvider:
    """@brief 一个本地 Agent CLI 的静态能力描述。"""

    id: str
    name: str
    protocol: str
    supports_schema: bool
    supports_resume: bool
    command: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        """@brief 返回可写入健康检查或任务日志的字典。"""
        return asdict(self)


def _node_command(script: Path) -> tuple[str, ...] | None:
    """@brief 使用 node 直接运行 npm CLI，避免 Windows cmd/PowerShell 二次解析 prompt。"""
    if not script.is_file():
        return None
    npm_root = next((parent for parent in script.parents if parent.name.lower() == "npm"), None)
    bundled_node = npm_root / "node.exe" if npm_root else Path()
    node = str(bundled_node) if bundled_node.is_file() else (shutil.which("node.exe") or shutil.which("node"))
    return (node, str(script)) if node else None


def _first_executable(candidates: Sequence[str | Path]) -> tuple[str, ...] | None:
    """@brief 从显式路径和 PATH 名称中返回首个可执行入口。"""
    for raw in candidates:
        text = str(raw)
        path = Path(text).expanduser()
        if path.is_file() and path.suffix.lower() not in {".cmd", ".bat", ".ps1"}:
            return (str(path),)
        found = shutil.which(text)
        if found and Path(found).suffix.lower() not in {".cmd", ".bat", ".ps1"}:
            return (found,)
    return None


def resolve_provider(provider_id: str) -> AgentProvider:
    """@brief 解析本机 Agent CLI；不存在时抛出可读错误。"""
    provider_id = str(provider_id or "codex").strip().lower()
    if provider_id not in SUPPORTED_PROVIDER_IDS:
        raise ValueError(f"不支持的 Agent Provider: {provider_id}")

    appdata = Path(os.environ.get("APPDATA", "")) if os.environ.get("APPDATA") else None
    home = Path.home()
    command: tuple[str, ...] | None = None
    if provider_id == "codex":
        env_bin = os.environ.get("CODEX_BIN")
        command = _first_executable([env_bin]) if env_bin else None
        if command is None and appdata:
            command = _node_command(appdata / "npm" / "node_modules" / "@openai" / "codex" / "bin" / "codex.js")
        if command is None:
            command = _first_executable(["codex.exe", "codex"])
        metadata = ("Codex", "codex-exec-v1", True, True)
    elif provider_id == "claude":
        env_bin = os.environ.get("CLAUDE_BIN")
        command = _first_executable(
            [item for item in (env_bin, home / ".local" / "bin" / "claude.exe", "claude.exe", "claude") if item]
        )
        metadata = ("Claude Code", "claude-print-v1", True, True)
    elif provider_id == "gemini":
        env_bin = os.environ.get("GEMINI_BIN")
        command = _first_executable([item for item in (env_bin, "gemini.exe", "gemini") if item])
        if command is None and appdata:
            command = _node_command(appdata / "npm" / "node_modules" / "@google" / "gemini-cli" / "dist" / "index.js")
        metadata = ("Gemini CLI", "gemini-headless-v1", False, True)
    else:
        env_bin = os.environ.get("OPENCODE_BIN")
        npm_binary = appdata / "npm" / "node_modules" / "opencode-ai" / "bin" / "opencode.exe" if appdata else None
        command = _first_executable([item for item in (env_bin, npm_binary, "opencode.exe", "opencode") if item])
        metadata = ("OpenCode", "opencode-jsonl-v1", False, True)

    if command is None:
        env_name = f"{provider_id.upper()}_BIN"
        raise FileNotFoundError(f"没有找到 {metadata[0]} CLI。请安装后加入 PATH，或通过 {env_name} 指定入口。")
    return AgentProvider(provider_id, metadata[0], metadata[1], metadata[2], metadata[3], command)


def build_provider_command(
    provider: AgentProvider,
    prompt: str,
    cwd: Path,
    output_path: Path,
    schema_path: Path,
    sandbox: str,
    model: str | None = None,
) -> list[str]:
    """@brief 把统一任务协议编译成目标 CLI 的非交互命令。"""
    model = str(model or "").strip()
    command = list(provider.command)
    if provider.id == "codex":
        command.extend(
            [
                "exec",
                "-C",
                str(cwd),
                "-s",
                sandbox,
                "-c",
                'approval_policy="never"',
                "-o",
                str(output_path),
                "--output-schema",
                str(schema_path),
            ]
        )
        if model:
            command.extend(["--model", model])
        command.append(prompt)
    elif provider.id == "claude":
        command.extend(
            [
                "-p",
                prompt,
                "--output-format",
                "json",
                "--json-schema",
                schema_path.read_text(encoding="utf-8"),
                "--no-session-persistence",
            ]
        )
        if sandbox == "danger-full-access":
            command.append("--dangerously-skip-permissions")
        else:
            command.extend(["--permission-mode", "dontAsk"])
        if model:
            command.extend(["--model", model])
    elif provider.id == "gemini":
        command.extend(["-p", prompt, "--output-format", "json", "--approval-mode"])
        command.append("yolo" if sandbox == "danger-full-access" else "auto_edit")
        if model:
            command.extend(["--model", model])
    else:
        command.extend(["run", "--format", "json", "--dir", str(cwd)])
        if sandbox == "danger-full-access":
            command.append("--dangerously-skip-permissions")
        if model:
            command.extend(["--model", model])
        command.append(prompt)
    return command


def _result_from_value(value: Any) -> dict[str, Any] | None:
    """@brief 从不同 Provider 的 JSON 包装层递归寻找统一结果对象。"""
    if isinstance(value, dict):
        if REQUIRED_RESULT_FIELDS.issubset(value):
            return value
        for key in ("structured_output", "structuredOutput", "response", "result", "output", "content", "text"):
            if key in value:
                found = _result_from_value(value[key])
                if found is not None:
                    return found
        for child in value.values():
            found = _result_from_value(child)
            if found is not None:
                return found
    elif isinstance(value, list):
        for child in reversed(value):
            found = _result_from_value(child)
            if found is not None:
                return found
    elif isinstance(value, str):
        return _result_from_text(value)
    return None


def _result_from_text(text: str) -> dict[str, Any] | None:
    """@brief 从普通文本或 Markdown 代码块中提取首个符合协议的 JSON 对象。"""
    decoder = json.JSONDecoder()
    for index, character in enumerate(text):
        if character != "{":
            continue
        try:
            value, _end = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        found = _result_from_value(value)
        if found is not None:
            return found
    return None


def _normalise_unified_result(value: dict[str, Any]) -> dict[str, Any]:
    """@brief 归一化 Provider 常见字段别名，再交给统一契约严格校验。"""
    result = dict(value)
    verification = result.get("verification")
    if isinstance(verification, list):
        normalised_items = []
        for item in verification:
            if not isinstance(item, dict):
                normalised_items.append(item)
                continue
            status = str(item.get("status") or "").strip().lower()
            status_aliases = {
                "pass": "passed",
                "success": "passed",
                "ok": "passed",
                "fail": "failed",
                "error": "failed",
                "skip": "skipped",
            }
            normalised_items.append(
                {
                    "command": str(item.get("command") or item.get("type") or item.get("check") or "provider-verification"),
                    "status": status_aliases.get(status, status),
                    "note": str(item.get("note") or item.get("detail") or item.get("message") or ""),
                }
            )
        result["verification"] = normalised_items
    return result


def parse_provider_result(provider: AgentProvider, stdout: str, output_path: Path) -> dict[str, Any]:
    """@brief 将 Provider 原生输出归一化为统一 Agent 结果对象。"""
    if provider.id == "codex":
        if not output_path.is_file():
            raise RuntimeError(f"Codex 未生成结构化结果文件: {output_path}")
        try:
            value = json.loads(output_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"Codex 结构化结果无效: {output_path}: {exc}") from exc
        found = _result_from_value(value)
    else:
        found = None
        stripped = stdout.strip()
        if stripped:
            try:
                found = _result_from_value(json.loads(stripped))
            except json.JSONDecodeError:
                events = []
                for line in stripped.splitlines():
                    try:
                        events.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
                found = _result_from_value(events) or _result_from_text(stripped)
    if found is None:
        raise RuntimeError(f"{provider.name} 未返回符合统一 Agent 协议的结构化结果")
    found = _normalise_unified_result(found)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(found, ensure_ascii=False, indent=2), encoding="utf-8")
    return found


def probe_provider(
    provider_id: str,
    runner: Callable[[Sequence[str], Path, int], Any],
    cwd: Path,
    timeout_seconds: int = 10,
) -> dict[str, Any]:
    """@brief 低成本探测 Provider 版本，不发送模型请求。"""
    try:
        provider = resolve_provider(provider_id)
        completed = runner([*provider.command, "--version"], cwd, timeout_seconds)
        message = (completed.stdout or completed.stderr or "").strip()
        return {**provider.to_dict(), "installed": completed.returncode == 0, "version": message}
    except (FileNotFoundError, ValueError) as exc:
        return {"id": provider_id, "installed": False, "version": "", "error": str(exc)}
