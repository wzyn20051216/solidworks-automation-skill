"""@brief MCP 只读产物适配：复用 Artifact Ledger，使用不透明 ID 与目录边界。"""
import hashlib
import json
import mimetypes
from pathlib import Path
import re
from uuid import uuid4

from apps.desktop.cad_workbench.artifact_ledger import ledger_path_for, write_artifact_ledger

_ID = re.compile(r"^(mcp-[0-9a-f]{32})-([0-9]{1,5})$")
MAX_INLINE = 8 * 1024 * 1024


class ArtifactAccess:
    """@brief 产物 ID 关联既有交付事实；不建立第二份文件账本。"""
    def __init__(self, root, queue_dir):
        self.root = Path(root).expanduser().resolve()
        self.queue_dir = Path(queue_dir).expanduser().resolve()

    def _inside(self, path):
        """@brief 拒绝绝对路径、链接或 ledger 内容造成的越界读取。"""
        resolved = Path(path).expanduser().resolve()
        if not resolved.is_relative_to(self.root) or not resolved.is_file():
            raise ValueError("产物不在允许的输出目录或文件不存在")
        return resolved

    def publish(self, payload):
        """@brief 仅从明确输出字段登记现有文件，不读取输入文档或任意字符串。"""
        candidates = []
        def walk(value, output=False):
            if isinstance(value, dict):
                for key, item in value.items():
                    is_output = key in {"output_path", "outputPath", "report_path", "reportPath", "pdf_path", "drawing_path"}
                    if is_output or (output and key == "path"):
                        if isinstance(item, str):
                            candidates.append(item)
                    else:
                        walk(item, output or key in {"outputs", "artifacts", "previews", "preview_paths"})
            elif isinstance(value, list):
                for item in value:
                    walk(item, output)
            elif output and isinstance(value, str):
                candidates.append(value)
        walk(payload)
        paths = []
        for candidate in candidates:
            try:
                path = self._inside(candidate)
                if path not in paths:
                    paths.append(path)
            except (OSError, ValueError):
                continue
        if not paths:
            return []
        run = "mcp-" + uuid4().hex
        ledger = write_artifact_ledger(self.queue_dir, {"id": run, "runId": run, "kind": "mcp_tool", "executor": "mcp"},
            {"outputs": [{"path": str(path)} for path in paths]})
        refs = []
        for index, item in enumerate(ledger["artifacts"]):
            artifact_id = f"{run}-{index}"
            refs.append({"artifact_id": artifact_id, "uri": "cad-artifact://delivery/" + artifact_id,
                "name": Path(item["path"]).name, "size_bytes": item["sizeBytes"], "sha256": item["sha256"],
                "mime_type": mimetypes.guess_type(item["path"])[0] or "application/octet-stream"})
        return refs

    def read(self, artifact_id, offset=0, max_bytes=MAX_INLINE):
        """@brief 有界读取并核对内容 hash；客户端不能用 path 参数读取任意文件。"""
        match = _ID.fullmatch(str(artifact_id))
        if not match or offset < 0 or not 1 <= max_bytes <= MAX_INLINE:
            raise ValueError("产物 ID 或读取范围无效")
        ledger = json.loads(ledger_path_for(self.queue_dir, match[1]).read_text(encoding="utf-8"))
        items = ledger["artifacts"]
        index = int(match[2])
        if index >= len(items):
            raise ValueError("产物 ID 不存在")
        record = items[index]
        path = self._inside(record["path"])
        # 用同一只读文件句柄计算 hash 和读取块，避免验证后另开文件的路径竞态。
        with path.open("rb") as stream:
            digest = hashlib.sha256()
            size = 0
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                size += len(chunk)
                digest.update(chunk)
            if digest.hexdigest() != record["sha256"] or size != record["sizeBytes"]:
                raise ValueError("产物内容已变化，请重新执行交付复核")
            if offset > size:
                raise ValueError("读取偏移超过文件大小")
            stream.seek(offset)
            data = stream.read(max_bytes)
        return path, data, {"sha256": record["sha256"], "total_bytes": size, "offset": offset,
            "next_offset": offset + len(data) if offset + len(data) < size else None}
