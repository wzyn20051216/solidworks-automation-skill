"""
SolidWorks 结果自审查工具。

用途:
    生成或修改 CAD 后，导出多视角预览图并收集基础模型摘要，帮助代理通过截图
    或导出的 BMP 判断几何是否符合用户意图。
"""
import os
import json
import argparse
from pathlib import Path

try:
    from .sw_connect import connect_solidworks, get_com_member, open_document
except ImportError:
    from sw_connect import connect_solidworks, get_com_member, open_document


STANDARD_VIEWS = {
    "front": 1,
    "back": 2,
    "left": 3,
    "right": 4,
    "top": 5,
    "bottom": 6,
    "isometric": 7,
    "trimetric": 8,
    "dimetric": 9,
}


def _expand_path(path):
    """展开输出路径。"""
    return Path(os.path.expandvars(str(path))).expanduser().resolve()


def _file_info(path):
    """返回文件存在性和大小信息。"""
    path = _expand_path(path)
    return {
        "path": str(path),
        "exists": path.exists(),
        "size_bytes": path.stat().st_size if path.exists() else 0,
    }


def _read_bmp_size(path):
    """
    读取 BMP 宽高。

    返回:
        (width, height)；读取失败时返回 (None, None)
    """
    try:
        with open(path, "rb") as file:
            header = file.read(26)
        if len(header) < 26 or header[:2] != b"BM":
            return None, None
        width = int.from_bytes(header[18:22], "little", signed=True)
        height = int.from_bytes(header[22:26], "little", signed=True)
        return abs(width), abs(height)
    except Exception:
        return None, None


def inspect_bmp_preview(path, sample_limit=200000):
    """
    对 BMP 预览图做轻量检查。

    该检查不替代人工/视觉模型判断，只用于发现空白、文件过小、导出失败等明显问题。
    """
    info = _file_info(path)
    info.update({
        "width": None,
        "height": None,
        "unique_sample_values": 0,
        "likely_blank": True,
    })
    if not info["exists"] or info["size_bytes"] <= 0:
        return info

    width, height = _read_bmp_size(path)
    info["width"] = width
    info["height"] = height

    try:
        with open(path, "rb") as file:
            data = file.read()
        sample = data[54:54 + sample_limit] if len(data) > 54 else data
        info["unique_sample_values"] = len(set(sample))
        info["likely_blank"] = info["unique_sample_values"] < 8
    except Exception as exc:
        info["error"] = str(exc)
    return info


def zoom_to_fit(model):
    """缩放到适合窗口并刷新图形。"""
    get_com_member(model, "ViewZoomtofit2")
    get_com_member(model, "GraphicsRedraw2")


def set_standard_view(model, view_name="isometric"):
    """
    设置标准视图方向。

    参数:
        view_name: "isometric"、"front"、"top"、"right"，也可传 SolidWorks 视图名。
    """
    view_id = STANDARD_VIEWS.get(str(view_name).lower())
    if view_id is None:
        model.ShowNamedView2(str(view_name), -1)
    else:
        model.ShowNamedView2("", view_id)
    zoom_to_fit(model)


def save_preview(model, output_path, view_name="isometric", width=1600, height=1000):
    """
    导出当前模型预览图。

    参数:
        model: IModelDoc2 对象
        output_path: BMP 输出路径
        view_name: 标准视图方向
        width: 导出图片宽度
        height: 导出图片高度

    返回:
        输出路径字符串
    """
    output_path = _expand_path(output_path)
    if output_path.suffix.lower() != ".bmp":
        output_path = output_path.with_suffix(".bmp")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    set_standard_view(model, view_name)
    ok = model.SaveBMP(str(output_path), int(width), int(height))
    if not ok or not output_path.exists():
        raise RuntimeError(f"预览图导出失败: {output_path}")
    return str(output_path)


def save_review_previews(model, output_dir, basename="review", views=None):
    """
    导出多视角预览图。

    参数:
        model: IModelDoc2 对象
        output_dir: 输出目录
        basename: 文件名前缀
        views: 视图列表，默认导出等轴测、前视、俯视、右视

    返回:
        预览图路径列表
    """
    views = views or ("isometric", "front", "top", "right")
    output_dir = _expand_path(output_dir)
    return [
        save_preview(model, output_dir / f"{basename}_{view}.bmp", view)
        for view in views
    ]


def collect_model_summary(model):
    """
    收集基础模型摘要。

    返回:
        dict，包含标题、类型、特征数量、保存路径等信息。
    """
    features = []
    feature_error = None
    try:
        feature = get_com_member(model, "FirstFeature")
        while feature:
            features.append({
                "name": get_com_member(feature, "Name"),
                "type": get_com_member(feature, "GetTypeName2"),
            })
            feature = get_com_member(feature, "GetNextFeature")
    except Exception as exc:
        feature_error = str(exc)

    summary = {
        "title": get_com_member(model, "GetTitle"),
        "path": get_com_member(model, "GetPathName"),
        "type": get_com_member(model, "GetType"),
        "feature_count": len(features),
        "features": features,
    }
    if feature_error:
        summary["feature_error"] = feature_error
    return summary


def build_review_report(model, output_dir, basename="review", views=None, expected_outputs=None):
    """
    生成结构化审查报告数据。

    参数:
        model: IModelDoc2 对象
        output_dir: 预览图和报告输出目录
        basename: 输出文件名前缀
        views: 需要导出的视图列表
        expected_outputs: 期望存在的输出文件列表，如 sldprt、step、stl

    返回:
        dict 审查报告
    """
    output_dir = _expand_path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    get_com_member(model, "ForceRebuild3", False)
    zoom_to_fit(model)

    views = views or ("isometric", "front", "top", "right")
    preview_paths = save_review_previews(model, output_dir, basename=basename, views=views)
    previews = [inspect_bmp_preview(path) for path in preview_paths]
    expected = [_file_info(path) for path in (expected_outputs or [])]
    summary = collect_model_summary(model)

    checks = {
        "model_available": model is not None,
        "previews_created": all(item["exists"] and item["size_bytes"] > 0 for item in previews),
        "previews_not_blank": all(not item["likely_blank"] for item in previews),
        "expected_outputs_exist": all(item["exists"] and item["size_bytes"] > 0 for item in expected) if expected else None,
        "feature_summary_available": "feature_error" not in summary,
    }

    review_notes = [
        "人工或视觉模型仍需检查预览图中的主体、比例、方向、关键部件、重叠/悬空问题。",
        "若 previews_not_blank 为 false，优先检查视图缩放、模型是否为空、SaveBMP 是否成功。",
        "若 expected_outputs_exist 为 false，优先检查保存/导出路径和 COM 错误码。",
    ]

    report = {
        "model": summary,
        "previews": previews,
        "expected_outputs": expected,
        "checks": checks,
        "review_notes": review_notes,
    }
    report["evaluation"] = evaluate_review_report(report)
    return report


def evaluate_review_report(report):
    """
    对结构化审查报告做规则评分。

    返回:
        dict，包含 status、score、issues、recommendations、manual_review_required。
    """
    checks = report.get("checks", {})
    previews = report.get("previews", [])
    expected_outputs = report.get("expected_outputs", [])
    issues = []
    recommendations = []
    score = 100
    hard_fail = False

    def add_issue(code, severity, message, recommendation, penalty):
        nonlocal score, hard_fail
        issues.append({
            "code": code,
            "severity": severity,
            "message": message,
        })
        recommendations.append(recommendation)
        score -= penalty
        if severity == "fail":
            hard_fail = True

    if not checks.get("model_available"):
        add_issue(
            "model_missing",
            "fail",
            "没有可审查的 SolidWorks 模型对象。",
            "先确认连接成功并打开或新建了有效文档。",
            40,
        )

    if not checks.get("previews_created"):
        add_issue(
            "previews_missing",
            "fail",
            "预览图未成功生成。",
            "检查 SaveBMP、输出目录权限、模型视图是否可见。",
            35,
        )

    if checks.get("previews_created") and not checks.get("previews_not_blank"):
        add_issue(
            "previews_blank",
            "fail",
            "至少一张预览图疑似空白。",
            "检查模型是否为空、是否缩放到合适窗口、是否只停留在草图状态。",
            35,
        )

    if checks.get("expected_outputs_exist") is False:
        add_issue(
            "expected_outputs_missing",
            "fail",
            "期望输出文件不存在或大小为 0。",
            "重新检查保存/导出路径和 SolidWorks SaveAs 错误码。",
            30,
        )

    if checks.get("expected_outputs_exist") is None:
        add_issue(
            "expected_outputs_not_declared",
            "warn",
            "未声明期望输出文件，无法验证交付物是否完整。",
            "调用 run_review() 时传入 expected_outputs。",
            8,
        )

    if not checks.get("feature_summary_available"):
        add_issue(
            "feature_summary_unavailable",
            "warn",
            "无法读取特征树摘要。",
            "若几何预览正常可继续；若需调试特征树，检查 COM 成员兼容性。",
            8,
        )

    if len(previews) < 2:
        add_issue(
            "too_few_previews",
            "warn",
            "预览视角过少，难以判断三维几何。",
            "至少导出 isometric/front/top/right 四个视角。",
            8,
        )

    for preview in previews:
        if preview.get("exists") and preview.get("size_bytes", 0) < 10000:
            add_issue(
                "preview_file_too_small",
                "warn",
                f"预览图文件过小: {preview.get('path')}",
                "确认 BMP 是否完整导出，必要时重新导出预览图。",
                5,
            )
        if preview.get("width") and preview.get("height"):
            if preview["width"] < 640 or preview["height"] < 480:
                add_issue(
                    "preview_resolution_low",
                    "warn",
                    f"预览图分辨率偏低: {preview.get('path')}",
                    "使用默认 1600x1000 或更高分辨率导出。",
                    4,
                )

    for output in expected_outputs:
        if output.get("exists") and output.get("size_bytes", 0) < 1024:
            add_issue(
                "output_file_too_small",
                "warn",
                f"输出文件过小: {output.get('path')}",
                "检查文件是否只是空壳或导出失败残留。",
                6,
            )

    score = max(0, min(100, score))
    if hard_fail:
        status = "fail"
    elif issues:
        status = "warn"
    else:
        status = "pass"

    return {
        "status": status,
        "score": score,
        "issues": issues,
        "recommendations": list(dict.fromkeys(recommendations)),
        "manual_review_required": True,
        "manual_review_reason": "规则评分只能发现明显失败，最终几何是否符合用户意图仍需查看预览图或截图。",
    }


def write_review_report(report, output_path):
    """
    写入 JSON 审查报告。

    返回:
        报告路径字符串
    """
    output_path = _expand_path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as file:
        json.dump(report, file, ensure_ascii=False, indent=2)
    return str(output_path)


def run_review(model, output_dir, basename="review", views=None, expected_outputs=None):
    """
    一站式运行自审查并写入 `review_report.json`。

    返回:
        (report, report_path)
    """
    output_dir = _expand_path(output_dir)
    report = build_review_report(
        model,
        output_dir=output_dir,
        basename=basename,
        views=views,
        expected_outputs=expected_outputs,
    )
    report_path = write_review_report(report, output_dir / f"{basename}_review_report.json")
    return report, report_path


def _parse_args():
    """解析命令行参数。"""
    parser = argparse.ArgumentParser(description="导出 SolidWorks 多视角预览图并生成结构化自审查报告。")
    parser.add_argument("--file", help="要打开并审查的 SolidWorks 文件；不传则审查当前活动文档。")
    parser.add_argument("--output-dir", required=True, help="预览图和 review_report.json 输出目录。")
    parser.add_argument("--basename", default="review", help="输出文件名前缀。")
    parser.add_argument("--views", default="isometric,front,top,right", help="逗号分隔的视图列表。")
    parser.add_argument("--expected", action="append", default=[], help="期望存在的输出文件，可重复传入。")
    parser.add_argument("--version", type=int, help="SolidWorks 年份，例如 2024。")
    parser.add_argument("--silent-open", action="store_true", help="静默打开 --file。")
    return parser.parse_args()


def main():
    """命令行入口。"""
    args = _parse_args()
    sw, model = connect_solidworks(version=args.version)
    if args.file:
        model = open_document(sw, args.file, silent=args.silent_open, raise_on_error=True)
    if model is None:
        raise RuntimeError("没有可审查的活动 SolidWorks 文档")

    views = [item.strip() for item in args.views.split(",") if item.strip()]
    report, report_path = run_review(
        model,
        output_dir=args.output_dir,
        basename=args.basename,
        views=views,
        expected_outputs=args.expected,
    )
    evaluation = report["evaluation"]
    print(f"报告: {report_path}")
    print(f"状态: {evaluation['status']} / 分数: {evaluation['score']}")
    if evaluation["issues"]:
        print("问题:")
        for issue in evaluation["issues"]:
            print(f"- [{issue['severity']}] {issue['code']}: {issue['message']}")
    return 0 if evaluation["status"] in ("pass", "warn") else 2


if __name__ == "__main__":
    raise SystemExit(main())
