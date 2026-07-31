"""生成不包含 Prompt、密钥和完整私人路径的 CAD Studio 诊断包。"""
from __future__ import annotations

import argparse
import json
import re
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cad_doctor import run_doctor

SENSITIVE_KEYS = re.compile(r"prompt|api.?key|token|secret|password|credential|content|cwd|projectpath|sourcepath|endpoint", re.I)


def _redact(value: Any, key: str = "") -> Any:
    if SENSITIVE_KEYS.search(key):
        return "[redacted]"
    if isinstance(value, dict):
        return {str(k): _redact(v, str(k)) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact(item, key) for item in value[:100]]
    if isinstance(value, str):
        # 保留文件名和错误文本，不泄漏盘符下的完整用户目录。
        if re.match(r"^(?:[A-Za-z]:\\|/|\\\\)", value):
            return Path(value).name or "[path]"
        return value[:1000]
    return value


def create_diagnostic_bundle(output: Path, *, events: Any = None) -> Path:
    """创建 zip 诊断包并返回实际路径。"""
    output = Path(output)
    if output.suffix.lower() != ".zip":
        output = output.with_suffix(".zip")
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schemaVersion": "1.0",
        "createdAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "doctor": run_doctor(probe_cad=False),
        "events": _redact(events or []),
        "privacy": {"telemetry": "off", "redacted": ["prompt", "API key", "token", "完整私人路径"]},
    }
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("diagnostic.json", json.dumps(payload, ensure_ascii=False, indent=2))
    return output


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="导出脱敏 CAD Studio 诊断包")
    parser.add_argument("--output", type=Path, default=Path.cwd() / "cad-studio-diagnostics.zip")
    parser.add_argument("--events", type=Path, help="可选的本地事件 JSON，不会包含敏感字段")
    args = parser.parse_args(argv)
    events = None
    if args.events and args.events.is_file():
        events = json.loads(args.events.read_text(encoding="utf-8"))
    path = create_diagnostic_bundle(args.output, events=events)
    print(json.dumps({"path": path.name, "status": "created"}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
