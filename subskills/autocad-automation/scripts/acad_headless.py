"""@file acad_headless.py
@brief 使用 ezdxf 只读检查 DXF，并可选生成无头 PNG 预览。

该后端不读取或写入 DWG，不执行 AutoLISP，也不会修改源 DXF。最终 DWG/PDF
交付仍必须经过 AutoCAD COM 和原生打开复核。
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any


def inspect_dxf(source: str | Path) -> dict[str, Any]:
    """@brief 只读检查 DXF 的图层、实体类型、单位和包围盒。"""
    try:
        import ezdxf
        from ezdxf import bbox
    except ImportError as exc:
        raise RuntimeError("缺少可选依赖 ezdxf，请执行: python -m pip install ezdxf") from exc

    path = Path(source).expanduser().resolve()
    if path.suffix.lower() != ".dxf":
        raise ValueError("无头后端只接受 DXF；DWG 必须使用 AutoCAD COM 只读打开")
    if not path.is_file():
        raise FileNotFoundError(path)
    document = ezdxf.readfile(path)
    modelspace = document.modelspace()
    type_counts = Counter(entity.dxftype() for entity in modelspace)
    layer_counts = Counter(str(entity.dxf.layer) for entity in modelspace)
    extents = bbox.extents(modelspace, fast=True)
    bbox_value = None
    if extents.has_data:
        bbox_value = [list(extents.extmin), list(extents.extmax)]
    return {
        "schemaVersion": "1.0",
        "status": "ok",
        "backend": "ezdxf-readonly",
        "source": path.name,
        "fileSize": path.stat().st_size,
        "dxfVersion": document.dxfversion,
        "units": int(document.header.get("$INSUNITS", 0)),
        "entityCount": sum(type_counts.values()),
        "typeCounts": dict(type_counts),
        "layerCounts": dict(layer_counts),
        "layers": [layer.dxf.name for layer in document.layers],
        "bbox": bbox_value,
        "limitations": ["只读 DXF 检查", "不替代 AutoCAD 原生 DWG/PDF 复核"],
    }


def render_dxf(source: str | Path, output: str | Path) -> dict[str, Any]:
    """@brief 使用 ezdxf/matplotlib 渲染只读 PNG 预览。"""
    try:
        import ezdxf
        from ezdxf.addons.drawing import Frontend, RenderContext
        from ezdxf.addons.drawing.matplotlib import MatplotlibBackend
        import matplotlib.pyplot as plt
    except ImportError as exc:
        raise RuntimeError("生成 PNG 预览需要 ezdxf 和 matplotlib") from exc

    source_path = Path(source).expanduser().resolve()
    output_path = Path(output).expanduser().resolve()
    if source_path.suffix.lower() != ".dxf" or output_path.suffix.lower() != ".png":
        raise ValueError("预览输入必须是 DXF，输出必须是 PNG")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    document = ezdxf.readfile(source_path)
    figure = plt.figure(figsize=(12, 8), dpi=140)
    axes = figure.add_axes([0.02, 0.02, 0.96, 0.96])
    axes.set_aspect("equal")
    axes.axis("off")
    context = RenderContext(document)
    Frontend(context, MatplotlibBackend(axes)).draw_layout(document.modelspace(), finalize=True)
    figure.savefig(output_path, facecolor="white", bbox_inches="tight", pad_inches=0.05)
    plt.close(figure)
    return {"status": "ok", "backend": "ezdxf-matplotlib", "path": output_path.name, "size": output_path.stat().st_size}


def main(argv: list[str] | None = None) -> int:
    """@brief CLI 入口。"""
    parser = argparse.ArgumentParser(description="使用 ezdxf 只读检查/预览 DXF")
    parser.add_argument("source", type=Path)
    parser.add_argument("--preview", type=Path, help="可选 PNG 预览输出")
    parser.add_argument("--json", type=Path, help="可选 JSON 报告输出")
    args = parser.parse_args(argv)
    report = inspect_dxf(args.source)
    if args.preview:
        report["preview"] = render_dxf(args.source, args.preview)
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
